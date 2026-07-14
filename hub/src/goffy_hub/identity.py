from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal
from uuid import UUID, uuid4

HubIdentitySchemaVersion = Literal["goffy.hub.identity.v1"]

HUB_IDENTITY_SCHEMA_VERSION: Final[HubIdentitySchemaVersion] = "goffy.hub.identity.v1"
HUB_IDENTITY_SEED_BYTES: Final = 32
HUB_IDENTITY_FILENAME: Final = "hub-identity.json"
MAX_IDENTITY_FILE_BYTES: Final = 2_048
FINGERPRINT_DOMAIN: Final = b"goffy-hub-identity-fingerprint-v1\x00"

Clock = Callable[[], datetime]
SeedFactory = Callable[[], bytes]
IdFactory = Callable[[], UUID]


class HubIdentityStoreError(Exception):
    """Base class for safe Hub identity-store failures."""


class HubIdentityStoreUnavailableError(HubIdentityStoreError):
    pass


@dataclass(frozen=True, slots=True)
class HubIdentity:
    hub_id: UUID
    fingerprint: str
    created_at: datetime
    schema_version: HubIdentitySchemaVersion = HUB_IDENTITY_SCHEMA_VERSION


class HubIdentityStore:
    """Owner-only local identity material for future Hub pinning."""

    def __init__(
        self,
        identity_path: Path,
        *,
        clock: Clock | None = None,
        seed_factory: SeedFactory | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        if not identity_path.is_absolute():
            raise HubIdentityStoreUnavailableError("Hub identity path must be absolute")
        self._identity_path = identity_path
        self._clock = clock or _utc_now
        self._seed_factory = seed_factory or (lambda: os.urandom(HUB_IDENTITY_SEED_BYTES))
        self._id_factory = id_factory or uuid4
        self._prepare_identity_path()

    @property
    def identity_path(self) -> Path:
        return self._identity_path

    def load_or_create(self) -> HubIdentity:
        if self._identity_path.exists():
            return self._load_existing()
        return self._create()

    def _prepare_identity_path(self) -> None:
        path = self._identity_path
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise HubIdentityStoreUnavailableError("Hub identity path must be a regular file")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _validate_private_directory_chain(path.parent)

    def _create(self) -> HubIdentity:
        identity_seed = self._seed_factory()
        if len(identity_seed) != HUB_IDENTITY_SEED_BYTES:
            raise HubIdentityStoreUnavailableError("generated Hub identity material is invalid")
        created_at = _as_utc(self._clock())
        hub_id = self._id_factory()
        payload = {
            "schemaVersion": HUB_IDENTITY_SCHEMA_VERSION,
            "hubId": str(hub_id),
            "identitySeed": _encode_identity_seed(identity_seed),
            "createdAt": _serialize_datetime(created_at),
        }
        encoded_payload = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        _validate_private_directory_chain(self._identity_path.parent)
        try:
            descriptor = os.open(self._identity_path, flags, 0o600)
        except FileExistsError:
            return self._load_existing()
        except OSError as error:
            raise HubIdentityStoreUnavailableError(
                "Hub identity file could not be created safely"
            ) from error

        try:
            with os.fdopen(descriptor, "wb") as identity_file:
                identity_file.write(encoded_payload)
        except OSError as error:
            raise HubIdentityStoreUnavailableError(
                "Hub identity file could not be written"
            ) from error

        if os.name == "posix":
            self._identity_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return HubIdentity(
            hub_id=hub_id,
            fingerprint=_fingerprint_identity_seed(identity_seed),
            created_at=created_at,
        )

    def _load_existing(self) -> HubIdentity:
        path = self._identity_path
        if path.is_symlink() or not path.is_file():
            raise HubIdentityStoreUnavailableError("Hub identity path must be a regular file")
        _validate_private_directory_chain(path.parent)
        try:
            payload = json.loads(_read_identity_file(path))
        except (OSError, json.JSONDecodeError) as error:
            raise HubIdentityStoreUnavailableError("Hub identity file is unavailable") from error
        if not isinstance(payload, dict):
            raise HubIdentityStoreUnavailableError("Hub identity file is invalid")
        return _parse_identity_payload(payload)


def identity_path_for_credential_database(database_path: Path) -> Path:
    return database_path.with_name(HUB_IDENTITY_FILENAME)


def _validate_private_directory_chain(directory: Path) -> None:
    if os.name != "posix":
        return
    current_user = os.getuid()
    for directory_part in (directory, *directory.parents):
        try:
            directory_stat = directory_part.lstat()
        except OSError as error:
            raise HubIdentityStoreUnavailableError(
                "Hub identity directory is unavailable"
            ) from error
        if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
            raise HubIdentityStoreUnavailableError("Hub identity directory must not be a symlink")
        directory_mode = stat.S_IMODE(directory_stat.st_mode)
        if directory_mode & (stat.S_IWGRP | stat.S_IWOTH) and not (directory_mode & stat.S_ISVTX):
            raise HubIdentityStoreUnavailableError(
                "Hub identity directory chain must not be group/world writable"
            )

    parent_stat = directory.stat()
    if parent_stat.st_uid != current_user:
        raise HubIdentityStoreUnavailableError("Hub identity parent must be owned by this user")


def _read_identity_file(path: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise HubIdentityStoreUnavailableError("Hub identity file could not be opened") from error

    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise HubIdentityStoreUnavailableError("Hub identity path must be a regular file")
        if os.name == "posix":
            if stat.S_IMODE(file_stat.st_mode) & 0o077:
                raise HubIdentityStoreUnavailableError("Hub identity file must be owner-only")
            if file_stat.st_uid != os.getuid():
                raise HubIdentityStoreUnavailableError(
                    "Hub identity file must be owned by this user"
                )
        if file_stat.st_size > MAX_IDENTITY_FILE_BYTES:
            raise HubIdentityStoreUnavailableError("Hub identity file is too large")
        with os.fdopen(descriptor, "r", encoding="utf-8") as identity_file:
            descriptor = -1
            return identity_file.read(MAX_IDENTITY_FILE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _parse_identity_payload(payload: Mapping[object, object]) -> HubIdentity:
    if set(payload) != {"schemaVersion", "hubId", "identitySeed", "createdAt"}:
        raise HubIdentityStoreUnavailableError("Hub identity file is invalid")
    schema_version = _read_required_string(payload, "schemaVersion")
    if schema_version != HUB_IDENTITY_SCHEMA_VERSION:
        raise HubIdentityStoreUnavailableError("Hub identity schema is unsupported")
    raw_hub_id = _read_required_string(payload, "hubId")
    try:
        hub_id = UUID(raw_hub_id)
    except ValueError as error:
        raise HubIdentityStoreUnavailableError("Hub identity ID is invalid") from error
    if str(hub_id) != raw_hub_id:
        raise HubIdentityStoreUnavailableError("Hub identity ID must be canonical")
    identity_seed = _decode_identity_seed(_read_required_string(payload, "identitySeed"))
    created_at = _parse_datetime(_read_required_string(payload, "createdAt"))
    return HubIdentity(
        hub_id=hub_id,
        fingerprint=_fingerprint_identity_seed(identity_seed),
        created_at=created_at,
    )


def _read_required_string(payload: Mapping[object, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise HubIdentityStoreUnavailableError("Hub identity file is invalid")
    return value


def _encode_identity_seed(identity_seed: bytes) -> str:
    return base64.urlsafe_b64encode(identity_seed).decode("ascii").rstrip("=")


def _decode_identity_seed(encoded_identity_seed: str) -> bytes:
    padding = "=" * (-len(encoded_identity_seed) % 4)
    try:
        identity_seed = base64.urlsafe_b64decode(encoded_identity_seed + padding)
    except (binascii.Error, ValueError) as error:
        raise HubIdentityStoreUnavailableError("Hub identity material is invalid") from error
    if len(identity_seed) != HUB_IDENTITY_SEED_BYTES:
        raise HubIdentityStoreUnavailableError("Hub identity material is invalid")
    return identity_seed


def _fingerprint_identity_seed(identity_seed: bytes) -> str:
    if len(identity_seed) != HUB_IDENTITY_SEED_BYTES:
        raise HubIdentityStoreUnavailableError("Hub identity material is invalid")
    digest = hashlib.sha256(FINGERPRINT_DOMAIN + identity_seed).hexdigest()
    return f"sha256:{digest}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HubIdentityStoreUnavailableError("Hub identity timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _serialize_datetime(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HubIdentityStoreUnavailableError("Hub identity timestamp is invalid") from error
    return _as_utc(parsed)
