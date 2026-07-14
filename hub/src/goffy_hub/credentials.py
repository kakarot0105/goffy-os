from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hmac import compare_digest
from pathlib import Path
from secrets import token_urlsafe
from uuid import UUID, uuid4

TOKEN_DIGEST_DOMAIN = b"goffy-paired-credential-v1\x00"
MAX_ACTIVE_CREDENTIALS = 32
MAX_RETAINED_CREDENTIALS = 64
MIN_GENERATED_TOKEN_LENGTH = 32
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]
IdFactory = Callable[[], UUID]


class CredentialStoreError(Exception):
    """Base class for safe credential-store failures."""


class CredentialStoreUnavailableError(CredentialStoreError):
    pass


class InvalidCredentialMetadataError(CredentialStoreError):
    pass


class CredentialCapacityError(CredentialStoreError):
    pass


@dataclass(frozen=True, slots=True)
class PairedCredential:
    credential_id: UUID
    device_id: str
    display_name: str
    created_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    credential: PairedCredential
    access_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class RotatedCredential:
    credential: PairedCredential
    access_token: str = field(repr=False)
    rotated_at: datetime


class CredentialStore:
    """Small file-backed store that persists only digests of generated bearers."""

    def __init__(
        self,
        database_path: Path,
        *,
        clock: Clock | None = None,
        token_factory: TokenFactory | None = None,
        id_factory: IdFactory | None = None,
    ) -> None:
        if not database_path.is_absolute():
            raise CredentialStoreUnavailableError("credential database path must be absolute")
        if database_path.is_symlink():
            raise CredentialStoreUnavailableError("credential database path must be a regular file")
        self._database_path = database_path.resolve(strict=False)
        self._clock = clock or _utc_now
        self._token_factory = token_factory or (lambda: token_urlsafe(32))
        self._id_factory = id_factory or uuid4
        self._prepare_database_path()
        self._initialize_schema()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def issue(self, device_id: str, display_name: str) -> IssuedCredential:
        if DEVICE_ID_PATTERN.fullmatch(device_id) is None:
            raise InvalidCredentialMetadataError("device observation ID is invalid")
        if not 1 <= len(display_name) <= 80 or any(
            ord(character) < 32 or ord(character) == 127 for character in display_name
        ):
            raise InvalidCredentialMetadataError("device display name is invalid")
        access_token = self._token_factory()
        if len(access_token) < MIN_GENERATED_TOKEN_LENGTH:
            raise CredentialStoreError("generated credential token is too short")

        credential = PairedCredential(
            credential_id=self._id_factory(),
            device_id=device_id,
            display_name=display_name,
            created_at=_as_utc(self._clock()),
            revoked_at=None,
        )
        digest = _token_digest(access_token)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active_count = connection.execute(
                "SELECT COUNT(*) FROM paired_credentials WHERE revoked_at IS NULL"
            ).fetchone()[0]
            if active_count >= MAX_ACTIVE_CREDENTIALS:
                raise CredentialCapacityError("active credential limit reached")

            self._prune_revoked(connection)
            connection.execute(
                """
                INSERT INTO paired_credentials (
                    credential_id, device_id, display_name, token_digest, created_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    str(credential.credential_id),
                    credential.device_id,
                    credential.display_name,
                    digest,
                    _serialize_datetime(credential.created_at),
                ),
            )

        return IssuedCredential(credential=credential, access_token=access_token)

    def authenticate(self, access_token: str) -> PairedCredential | None:
        if not access_token or len(access_token) > 512:
            return None
        presented_digest = _token_digest(access_token)

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT credential_id, device_id, display_name, token_digest, created_at, revoked_at
                FROM paired_credentials
                WHERE revoked_at IS NULL
                ORDER BY created_at, credential_id
                """
            ).fetchall()

        for row in rows:
            if compare_digest(presented_digest, bytes(row[3])):
                return _row_to_credential(row)
        return None

    def list_credentials(self) -> tuple[PairedCredential, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT credential_id, device_id, display_name, token_digest, created_at, revoked_at
                FROM paired_credentials
                ORDER BY created_at DESC, credential_id DESC
                LIMIT ?
                """,
                (MAX_RETAINED_CREDENTIALS,),
            ).fetchall()
        return tuple(_row_to_credential(row) for row in rows)

    def revoke(self, credential_id: UUID) -> PairedCredential | None:
        revoked_at = _as_utc(self._clock())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT credential_id, device_id, display_name, token_digest, created_at, revoked_at
                FROM paired_credentials
                WHERE credential_id = ? AND revoked_at IS NULL
                """,
                (str(credential_id),),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE paired_credentials SET revoked_at = ? WHERE credential_id = ?",
                (_serialize_datetime(revoked_at), str(credential_id)),
            )

        credential = _row_to_credential(row)
        return PairedCredential(
            credential_id=credential.credential_id,
            device_id=credential.device_id,
            display_name=credential.display_name,
            created_at=credential.created_at,
            revoked_at=revoked_at,
        )

    def rotate(self, credential_id: UUID, current_access_token: str) -> RotatedCredential | None:
        if not current_access_token or len(current_access_token) > 512:
            return None
        rotated_at = _as_utc(self._clock())
        current_digest = _token_digest(current_access_token)

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT credential_id, device_id, display_name, token_digest, created_at, revoked_at
                FROM paired_credentials
                WHERE credential_id = ? AND revoked_at IS NULL
                """,
                (str(credential_id),),
            ).fetchone()
            if row is None or not compare_digest(current_digest, bytes(row[3])):
                return None
            new_access_token = self._token_factory()
            if len(new_access_token) < MIN_GENERATED_TOKEN_LENGTH:
                raise CredentialStoreError("generated credential token is too short")
            new_digest = _token_digest(new_access_token)
            if compare_digest(current_digest, new_digest):
                raise CredentialStoreError("generated credential token did not rotate")
            connection.execute(
                """
                UPDATE paired_credentials
                SET token_digest = ?
                WHERE credential_id = ? AND revoked_at IS NULL AND token_digest = ?
                """,
                (new_digest, str(credential_id), current_digest),
            )

        return RotatedCredential(
            credential=_row_to_credential(row),
            access_token=new_access_token,
            rotated_at=rotated_at,
        )

    def active_count(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM paired_credentials WHERE revoked_at IS NULL"
                ).fetchone()[0]
            )

    def is_active(self, credential_id: UUID) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    """
                    SELECT 1 FROM paired_credentials
                    WHERE credential_id = ? AND revoked_at IS NULL
                    """,
                    (str(credential_id),),
                ).fetchone()
                is not None
            )

    def _prepare_database_path(self) -> None:
        path = self._database_path
        if not path.is_absolute():
            raise CredentialStoreUnavailableError("credential database path must be absolute")
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise CredentialStoreUnavailableError("credential database path must be a regular file")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix" and stat.S_IMODE(path.parent.stat().st_mode) & (
            stat.S_IWGRP | stat.S_IWOTH
        ):
            raise CredentialStoreUnavailableError(
                "credential database parent must not be group/world writable"
            )

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            descriptor = None
        except OSError as error:
            raise CredentialStoreUnavailableError(
                "credential database could not be created safely"
            ) from error
        if descriptor is not None:
            os.close(descriptor)

        if path.is_symlink() or not path.is_file():
            raise CredentialStoreUnavailableError("credential database path must be a regular file")
        if os.name == "posix":
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def _initialize_schema(self) -> None:
        try:
            with self._connect() as connection:
                schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
                if schema_version not in {0, 1}:
                    raise CredentialStoreUnavailableError(
                        "credential database schema is unsupported"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS paired_credentials (
                        credential_id TEXT PRIMARY KEY,
                        device_id TEXT NOT NULL,
                        display_name TEXT NOT NULL,
                        token_digest BLOB NOT NULL UNIQUE CHECK(length(token_digest) = 32),
                        created_at TEXT NOT NULL,
                        revoked_at TEXT
                    ) STRICT
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(paired_credentials)")
                }
                if columns != {
                    "credential_id",
                    "device_id",
                    "display_name",
                    "token_digest",
                    "created_at",
                    "revoked_at",
                }:
                    raise CredentialStoreUnavailableError("credential database schema is invalid")
                connection.execute("PRAGMA user_version = 1")
        except sqlite3.DatabaseError as error:
            raise CredentialStoreUnavailableError(
                "credential database could not be initialized"
            ) from error

    def _prune_revoked(self, connection: sqlite3.Connection) -> None:
        total_count = connection.execute("SELECT COUNT(*) FROM paired_credentials").fetchone()[0]
        delete_count = max(0, total_count - MAX_RETAINED_CREDENTIALS + 1)
        if delete_count == 0:
            return
        connection.execute(
            """
            DELETE FROM paired_credentials
            WHERE credential_id IN (
                SELECT credential_id FROM paired_credentials
                WHERE revoked_at IS NOT NULL
                ORDER BY revoked_at, credential_id
                LIMIT ?
            )
            """,
            (delete_count,),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._database_path.is_symlink() or not self._database_path.is_file():
            raise CredentialStoreUnavailableError("credential database operation failed")
        if os.name == "posix" and stat.S_IMODE(self._database_path.stat().st_mode) & 0o077:
            raise CredentialStoreUnavailableError("credential database operation failed")
        try:
            connection = sqlite3.connect(
                f"{self._database_path.as_uri()}?mode=rw",
                timeout=3,
                uri=True,
            )
        except sqlite3.DatabaseError as error:
            raise CredentialStoreUnavailableError("credential database operation failed") from error
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        except sqlite3.DatabaseError as error:
            raise CredentialStoreUnavailableError("credential database operation failed") from error
        finally:
            connection.close()


def _token_digest(token: str) -> bytes:
    return hashlib.sha256(TOKEN_DIGEST_DOMAIN + token.encode("utf-8")).digest()


def _row_to_credential(row: sqlite3.Row | tuple[object, ...]) -> PairedCredential:
    return PairedCredential(
        credential_id=UUID(str(row[0])),
        device_id=str(row[1]),
        display_name=str(row[2]),
        created_at=_parse_datetime(str(row[4])),
        revoked_at=_parse_datetime(str(row[5])) if row[5] is not None else None,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise CredentialStoreError("credential timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _serialize_datetime(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
