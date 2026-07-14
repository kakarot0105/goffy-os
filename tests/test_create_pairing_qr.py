from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from scripts import create_pairing_qr
from scripts.create_pairing_qr import (
    PAIRING_QR_ARTIFACT_MARKER,
    PairingQrError,
    canonical_bundle_payload,
    fetch_pairing_bundle,
    pairing_bundle_url,
    svg_qr,
    validate_pairing_bundle,
    write_private_text,
)
from scripts.create_pairing_qr import (
    create_pairing_qr as create_artifact,
)

TEST_BOOTSTRAP_TOKEN = "bootstrap-" + "token"
PAIRING_BUNDLE: dict[str, Any] = {
    "bundleVersion": "goffy.pairing.bundle.v2",
    "hubEndpoint": "ws://127.0.0.1:8787/ws/v1",
    "hubIdentity": {
        "schemaVersion": "goffy.hub.identity.v1",
        "hubId": "22222222-2222-4222-8222-222222222222",
        "fingerprint": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "createdAt": "2026-07-14T12:00:00Z",
        "mode": "usb_loopback",
        "verifiedBy": "loopback_admin_session",
        "trustedLanSupported": False,
    },
    "challenge": {
        "challengeId": "30303030-3030-4030-8030-303030303030",
        "pairingToken": "p" * 32,
        "expiresAt": "2026-07-14T12:00:00Z",
    },
}


class FakeHeaders:
    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = values

    def get(self, key: str, default: str = "") -> str:
        return self._values.get(key, default)


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self.body = body
        self.headers = FakeHeaders({"Content-Type": content_type})

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return self.body


def test_pairing_bundle_url_requires_loopback_http() -> None:
    assert pairing_bundle_url("http://127.0.0.1:8787") == (
        "http://127.0.0.1:8787/admin/v1/pairing/bundles"
    )
    assert pairing_bundle_url("http://localhost:8787/") == (
        "http://localhost:8787/admin/v1/pairing/bundles"
    )

    with pytest.raises(PairingQrError):
        pairing_bundle_url("https://127.0.0.1:8787")
    with pytest.raises(PairingQrError):
        pairing_bundle_url("http://hub.example:8787")
    with pytest.raises(PairingQrError):
        pairing_bundle_url("http://token@127.0.0.1:8787")


def test_fetch_pairing_bundle_posts_admin_token_without_query_secret() -> None:
    seen: dict[str, object] = {}

    def opener(request: Any, timeout: float) -> FakeResponse:
        seen["url"] = request.full_url
        seen["method"] = request.method
        seen["timeout"] = timeout
        seen["authorization"] = request.headers.get("Authorization")
        return FakeResponse(json.dumps(PAIRING_BUNDLE).encode("utf-8"))

    bundle = fetch_pairing_bundle(
        "http://127.0.0.1:8787",
        TEST_BOOTSTRAP_TOKEN,
        opener=opener,
    )

    assert bundle == PAIRING_BUNDLE
    assert seen == {
        "url": "http://127.0.0.1:8787/admin/v1/pairing/bundles",
        "method": "POST",
        "timeout": 5.0,
        "authorization": f"Bearer {TEST_BOOTSTRAP_TOKEN}",
    }
    assert TEST_BOOTSTRAP_TOKEN not in str(seen["url"])


def test_fetch_pairing_bundle_rejects_malformed_or_extended_payload() -> None:
    bad_bundle = dict(PAIRING_BUNDLE)
    bad_bundle["unexpected"] = True

    def opener(_request: Any, _timeout: float) -> FakeResponse:
        return FakeResponse(json.dumps(bad_bundle).encode("utf-8"))

    with pytest.raises(PairingQrError):
        fetch_pairing_bundle("http://127.0.0.1:8787", TEST_BOOTSTRAP_TOKEN, opener=opener)


def test_validate_pairing_bundle_rejects_trusted_lan_claim() -> None:
    bad_bundle = json.loads(json.dumps(PAIRING_BUNDLE))
    bad_bundle["hubIdentity"]["trustedLanSupported"] = True

    with pytest.raises(PairingQrError):
        validate_pairing_bundle(bad_bundle)


def test_validate_pairing_bundle_requires_hub_identity_fingerprint() -> None:
    bad_bundle = json.loads(json.dumps(PAIRING_BUNDLE))
    del bad_bundle["hubIdentity"]["fingerprint"]

    with pytest.raises(PairingQrError):
        validate_pairing_bundle(bad_bundle)


def test_validate_pairing_bundle_requires_typed_hub_identity_fields() -> None:
    bad_hub_id = json.loads(json.dumps(PAIRING_BUNDLE))
    bad_hub_id["hubIdentity"]["hubId"] = "not-a-uuid"
    bad_timestamp = json.loads(json.dumps(PAIRING_BUNDLE))
    bad_timestamp["hubIdentity"]["createdAt"] = "not-a-timestamp"
    naive_timestamp = json.loads(json.dumps(PAIRING_BUNDLE))
    naive_timestamp["hubIdentity"]["createdAt"] = "2026-07-14T12:00:00"

    with pytest.raises(PairingQrError):
        validate_pairing_bundle(bad_hub_id)
    with pytest.raises(PairingQrError):
        validate_pairing_bundle(bad_timestamp)
    with pytest.raises(PairingQrError):
        validate_pairing_bundle(naive_timestamp)


def test_validate_pairing_bundle_requires_typed_endpoint_and_challenge_fields() -> None:
    bad_endpoint = json.loads(json.dumps(PAIRING_BUNDLE))
    bad_endpoint["hubEndpoint"] = "not-a-ws-endpoint"
    bad_challenge_id = json.loads(json.dumps(PAIRING_BUNDLE))
    bad_challenge_id["challenge"]["challengeId"] = "not-a-uuid"
    short_token = json.loads(json.dumps(PAIRING_BUNDLE))
    short_token["challenge"]["pairingToken"] = "x"
    bad_expiry = json.loads(json.dumps(PAIRING_BUNDLE))
    bad_expiry["challenge"]["expiresAt"] = "not-a-timestamp"

    for bad_bundle in (bad_endpoint, bad_challenge_id, short_token, bad_expiry):
        with pytest.raises(PairingQrError):
            validate_pairing_bundle(bad_bundle)


def test_canonical_payload_is_stable_and_secret_stays_in_payload_only() -> None:
    payload = canonical_bundle_payload(PAIRING_BUNDLE)

    assert " " not in payload
    assert payload == canonical_bundle_payload(json.loads(payload))
    assert PAIRING_BUNDLE["challenge"]["pairingToken"] in payload


def test_write_private_text_rejects_overwrite_without_force(tmp_path: Path) -> None:
    output = tmp_path / "qr.svg"
    write_private_text(output, "first", force=False)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(PairingQrError):
        write_private_text(output, "second", force=False)

    write_private_text(output, "second", force=True)
    assert output.read_text(encoding="utf-8") == "second"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_write_private_text_rejects_symlink_output(tmp_path: Path) -> None:
    if getattr(os, "O_NOFOLLOW", 0) == 0:
        pytest.skip("O_NOFOLLOW is unavailable on this platform")
    target = tmp_path / "target.svg"
    output = tmp_path / "qr.svg"
    output.symlink_to(target)

    with pytest.raises(PairingQrError):
        write_private_text(output, "secret", force=True)

    assert not target.exists()


def test_svg_qr_uses_local_renderer() -> None:
    svg = svg_qr(canonical_bundle_payload(PAIRING_BUNDLE))

    assert svg.startswith("<?xml")
    assert PAIRING_QR_ARTIFACT_MARKER in svg
    assert "<svg" in svg
    assert PAIRING_BUNDLE["challenge"]["pairingToken"] not in svg


def test_create_pairing_qr_writes_svg_without_printing_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def opener(_request: Any, _timeout: float) -> FakeResponse:
        return FakeResponse(json.dumps(PAIRING_BUNDLE).encode("utf-8"))

    monkeypatch.setattr(
        create_pairing_qr,
        "svg_qr",
        lambda payload: f"<svg>{len(payload)}</svg>",
    )
    output = tmp_path / "pairing.svg"

    artifact = create_artifact(
        hub_url="http://127.0.0.1:8787",
        token=TEST_BOOTSTRAP_TOKEN,
        output=output,
        force=False,
        opener=opener,
    )

    assert artifact.output == output
    assert artifact.hub_endpoint == "ws://127.0.0.1:8787/ws/v1"
    assert artifact.expires_at == "2026-07-14T12:00:00Z"
    assert output.read_text(encoding="utf-8").startswith("<svg>")
    assert TEST_BOOTSTRAP_TOKEN not in output.read_text(encoding="utf-8")
