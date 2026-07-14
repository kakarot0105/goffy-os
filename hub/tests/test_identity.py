from __future__ import annotations

import base64
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr

from goffy_hub.app import create_app
from goffy_hub.identity import (
    HUB_IDENTITY_SCHEMA_VERSION,
    HUB_IDENTITY_SEED_BYTES,
    HubIdentityStore,
    HubIdentityStoreError,
    identity_path_for_credential_database,
)
from goffy_hub.settings import HubSettings

FIXED_HUB_ID = UUID("11111111-1111-4111-8111-111111111111")
FIXED_CREATED_AT = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)
FIXED_IDENTITY_SEED = bytes(range(HUB_IDENTITY_SEED_BYTES))
BOOTSTRAP_TOKEN = "bootstrap-token-that-is-long-enough"  # noqa: S105


def valid_identity_payload() -> dict[str, str]:
    return {
        "schemaVersion": HUB_IDENTITY_SCHEMA_VERSION,
        "hubId": str(FIXED_HUB_ID),
        "identitySeed": base64.urlsafe_b64encode(FIXED_IDENTITY_SEED).decode("ascii").rstrip("="),
        "createdAt": "2026-07-14T12:00:00Z",
    }


def test_identity_path_lives_next_to_pairing_database(tmp_path: Path) -> None:
    database_path = tmp_path / "state" / "credentials.sqlite3"

    assert identity_path_for_credential_database(database_path) == (
        tmp_path / "state" / "hub-identity.json"
    )


def test_identity_store_creates_owner_only_identity_and_reloads(tmp_path: Path) -> None:
    identity_path = tmp_path / "state" / "hub-identity.json"

    identity = HubIdentityStore(
        identity_path,
        clock=lambda: FIXED_CREATED_AT,
        seed_factory=lambda: FIXED_IDENTITY_SEED,
        id_factory=lambda: FIXED_HUB_ID,
    ).load_or_create()
    reloaded = HubIdentityStore(
        identity_path,
        clock=lambda: datetime(2030, 1, 1, tzinfo=UTC),
        seed_factory=lambda: b"x" * HUB_IDENTITY_SEED_BYTES,
        id_factory=lambda: UUID("22222222-2222-4222-8222-222222222222"),
    ).load_or_create()

    assert identity.schema_version == HUB_IDENTITY_SCHEMA_VERSION
    assert identity.hub_id == FIXED_HUB_ID
    assert identity.created_at == FIXED_CREATED_AT
    assert identity.fingerprint.startswith("sha256:")
    assert len(identity.fingerprint) == len("sha256:") + 64
    assert reloaded == identity
    payload = json.loads(identity_path.read_text(encoding="utf-8"))
    assert set(payload) == {"schemaVersion", "hubId", "identitySeed", "createdAt"}
    assert payload["identitySeed"]
    if os.name == "posix":
        assert stat.S_IMODE(identity_path.stat().st_mode) & 0o077 == 0


def test_identity_store_rejects_relative_path() -> None:
    with pytest.raises(HubIdentityStoreError, match="absolute"):
        HubIdentityStore(Path("hub-identity.json"))


def test_identity_store_rejects_group_writable_parent(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("POSIX file-mode check")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_dir.chmod(0o770)
    try:
        with pytest.raises(HubIdentityStoreError, match="directory chain"):
            HubIdentityStore(state_dir / "hub-identity.json")
    finally:
        state_dir.chmod(0o700)


def test_identity_store_rejects_group_writable_ancestor(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("POSIX file-mode check")
    unsafe_ancestor = tmp_path / "unsafe"
    unsafe_ancestor.mkdir()
    unsafe_ancestor.chmod(0o777)
    try:
        with pytest.raises(HubIdentityStoreError, match="directory chain"):
            HubIdentityStore(unsafe_ancestor / "state" / "hub-identity.json")
    finally:
        unsafe_ancestor.chmod(0o700)


def test_identity_store_rejects_symlinked_parent(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("POSIX symlink check")
    real_state = tmp_path / "real-state"
    real_state.mkdir()
    symlinked_state = tmp_path / "state"
    symlinked_state.symlink_to(real_state, target_is_directory=True)

    with pytest.raises(HubIdentityStoreError, match="symlink"):
        HubIdentityStore(symlinked_state / "hub-identity.json")


def test_identity_store_rejects_public_existing_file(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("POSIX file-mode check")
    identity_path = tmp_path / "hub-identity.json"
    identity_path.write_text(json.dumps(valid_identity_payload()), encoding="utf-8")
    identity_path.chmod(0o644)

    with pytest.raises(HubIdentityStoreError, match="owner-only"):
        HubIdentityStore(identity_path).load_or_create()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "schemaVersion": "goffy.hub.identity.v0",
            "hubId": str(FIXED_HUB_ID),
            "identitySeed": "abc",
            "createdAt": "2026-07-14T12:00:00Z",
        },
        {
            "schemaVersion": HUB_IDENTITY_SCHEMA_VERSION,
            "hubId": str(FIXED_HUB_ID).upper(),
            "identitySeed": "abc",
            "createdAt": "2026-07-14T12:00:00Z",
        },
        {
            **valid_identity_payload(),
            "identitySeed": "not-valid-base64!!!",
        },
        {
            **valid_identity_payload(),
            "createdAt": "not-a-date",
        },
    ],
)
def test_identity_store_rejects_invalid_existing_payload(
    tmp_path: Path,
    payload: dict[str, str],
) -> None:
    identity_path = tmp_path / "hub-identity.json"
    identity_path.write_text(json.dumps(payload), encoding="utf-8")
    if os.name == "posix":
        identity_path.chmod(0o600)

    with pytest.raises(HubIdentityStoreError):
        HubIdentityStore(identity_path).load_or_create()


def test_paired_app_startup_rejects_unsafe_identity_file(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("POSIX file-mode check")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    identity_path = state_dir / "hub-identity.json"
    identity_path.write_text(json.dumps(valid_identity_payload()), encoding="utf-8")
    identity_path.chmod(0o644)

    settings = HubSettings(
        auth_token=SecretStr(BOOTSTRAP_TOKEN),
        pairing_database_path=state_dir / "credentials.sqlite3",
    )

    with pytest.raises(HubIdentityStoreError, match="owner-only"):
        create_app(settings)
