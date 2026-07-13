from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

import goffy_hub.credentials as credentials_module
from goffy_hub.credentials import (
    CredentialCapacityError,
    CredentialStore,
    CredentialStoreError,
)

ACCESS_TOKEN = "paired-access-token-" + "a" * 32  # noqa: S105
CREDENTIAL_ID = UUID("10101010-1010-4010-8010-101010101010")
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def build_store(path: Path, *, now: datetime = NOW) -> CredentialStore:
    return CredentialStore(
        path,
        clock=lambda: now,
        token_factory=lambda: ACCESS_TOKEN,
        id_factory=lambda: CREDENTIAL_ID,
    )


def test_credential_store_persists_only_digest_and_authenticates_after_reopen(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "credentials.sqlite3"
    store = build_store(database_path)

    issued = store.issue("setup-observation-1", "Moto G")
    reopened = CredentialStore(database_path)
    authenticated = reopened.authenticate(ACCESS_TOKEN)
    raw_database = database_path.read_bytes()

    assert issued.access_token == ACCESS_TOKEN
    assert ACCESS_TOKEN not in repr(issued)
    assert issued.credential.credential_id == CREDENTIAL_ID
    assert authenticated == issued.credential
    assert ACCESS_TOKEN.encode() not in raw_database
    with sqlite3.connect(database_path) as connection:
        digest = connection.execute("SELECT token_digest FROM paired_credentials").fetchone()[0]
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert isinstance(digest, bytes)
    assert len(digest) == 32
    assert schema_version == 1
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600


def test_revoke_fails_authentication_and_persists_revoked_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "credentials.sqlite3"
    store = build_store(database_path)
    store.issue("setup-observation-1", "Moto G")

    revoked = CredentialStore(
        database_path,
        clock=lambda: NOW + timedelta(minutes=5),
    ).revoke(CREDENTIAL_ID)
    reopened = CredentialStore(database_path)

    assert revoked is not None
    assert revoked.revoked_at == NOW + timedelta(minutes=5)
    assert reopened.authenticate(ACCESS_TOKEN) is None
    assert reopened.list_credentials() == (revoked,)


def test_revoke_unknown_or_already_revoked_credential_is_idempotent(tmp_path: Path) -> None:
    store = build_store(tmp_path / "credentials.sqlite3")

    assert store.revoke(CREDENTIAL_ID) is None
    store.issue("setup-observation-1", "Moto G")
    assert store.revoke(CREDENTIAL_ID) is not None
    assert store.revoke(CREDENTIAL_ID) is None


def test_active_credential_capacity_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credentials_module, "MAX_ACTIVE_CREDENTIALS", 1)
    ids = iter(
        [
            UUID("10101010-1010-4010-8010-101010101010"),
            UUID("20202020-2020-4020-8020-202020202020"),
        ]
    )
    tokens = iter([ACCESS_TOKEN, "paired-access-token-" + "b" * 32])
    store = CredentialStore(
        tmp_path / "credentials.sqlite3",
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
        token_factory=lambda: next(tokens),
    )
    store.issue("observation-1", "First phone")

    with pytest.raises(CredentialCapacityError, match="limit"):
        store.issue("observation-2", "Second phone")

    assert store.active_count() == 1


def test_revoked_credential_retention_prunes_oldest_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credentials_module, "MAX_RETAINED_CREDENTIALS", 2)
    credential_ids = [UUID(int=value) for value in (1, 2, 3)]
    ids = iter(credential_ids)
    tokens = iter(f"paired-access-token-{value}-" + "x" * 32 for value in range(3))
    store = CredentialStore(
        tmp_path / "credentials.sqlite3",
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
        token_factory=lambda: next(tokens),
    )
    store.issue("observation-1", "First phone")
    store.revoke(credential_ids[0])
    store.issue("observation-2", "Second phone")
    store.revoke(credential_ids[1])
    store.issue("observation-3", "Third phone")

    retained_ids = {credential.credential_id for credential in store.list_credentials()}

    assert retained_ids == {credential_ids[1], credential_ids[2]}


def test_database_symlink_is_rejected(tmp_path: Path) -> None:
    real_database = tmp_path / "real.sqlite3"
    real_database.touch()
    linked_database = tmp_path / "linked.sqlite3"
    linked_database.symlink_to(real_database)

    with pytest.raises(CredentialStoreError, match="regular file"):
        CredentialStore(linked_database)


def test_generated_access_token_must_be_bounded_credential_material(tmp_path: Path) -> None:
    store = CredentialStore(
        tmp_path / "credentials.sqlite3",
        token_factory=lambda: "short",
    )

    with pytest.raises(CredentialStoreError, match="too short"):
        store.issue("observation-1", "Moto G")

    assert store.active_count() == 0


@pytest.mark.parametrize(
    ("device_id", "display_name"),
    [
        ("contains space", "Moto G"),
        ("a" * 65, "Moto G"),
        ("observation-1", ""),
        ("observation-1", "line\nbreak"),
        ("observation-1", "a" * 81),
    ],
)
def test_credential_metadata_is_strictly_bounded(
    tmp_path: Path,
    device_id: str,
    display_name: str,
) -> None:
    store = build_store(tmp_path / "credentials.sqlite3")

    with pytest.raises(CredentialStoreError, match="invalid"):
        store.issue(device_id, display_name)

    assert store.active_count() == 0


def test_database_path_must_be_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(CredentialStoreError, match="absolute"):
        CredentialStore(Path("credentials.sqlite3"))


def test_unknown_database_schema_version_fails_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "credentials.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 99")

    with pytest.raises(CredentialStoreError, match="unsupported"):
        CredentialStore(database_path)


def test_corrupt_database_failure_does_not_expose_sqlite_details(tmp_path: Path) -> None:
    database_path = tmp_path / "credentials.sqlite3"
    database_path.write_bytes(b"not-a-sqlite-database")

    with pytest.raises(
        CredentialStoreError,
        match="credential database operation failed",
    ):
        CredentialStore(database_path)


def test_deleted_runtime_database_is_not_silently_recreated(tmp_path: Path) -> None:
    database_path = tmp_path / "credentials.sqlite3"
    store = build_store(database_path)
    store.issue("observation-1", "Moto G")
    database_path.unlink()

    with pytest.raises(CredentialStoreError, match="operation failed"):
        store.authenticate(ACCESS_TOKEN)

    assert database_path.exists() is False
