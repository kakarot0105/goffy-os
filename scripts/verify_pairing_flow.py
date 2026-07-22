from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr
from starlette.testclient import TestClient

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings
from goffy_protocol import MCP_PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_pairing_qr import (  # noqa: E402
    canonical_bundle_payload,
    svg_qr,
    validate_pairing_bundle,
    write_private_text,
)

BOOTSTRAP_TOKEN = "local-pairing-smoke-bootstrap-token"  # noqa: S105
BOOTSTRAP_HEADERS = {"Authorization": f"Bearer {BOOTSTRAP_TOKEN}"}
EXPECTED_VERIFIER_TRUST_CONTRACT = {
    "schemaVersion": "goffy.hub.trust.v1",
    "proofKind": "loopback_fingerprint_only",
    "transportScope": "usb_loopback_only",
    "publicKeyPinStatus": "absent",
    "certificatePinStatus": "absent",
    "trustedLanSupported": False,
}


def approval_public_key_request() -> dict[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_spki_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return {
        "schemaVersion": "goffy.approval.public-key.v1",
        "algorithm": "ECDSA_P256_SHA256",
        "spkiDerBase64": base64.b64encode(public_key_spki_der).decode("ascii"),
        "spkiSha256": sha256(public_key_spki_der).hexdigest(),
    }


@dataclass(frozen=True)
class PairingSmokeResult:
    credential_id: str
    bundle_payload_bytes: int
    output: Path | None
    identity_status: int
    replay_status: int
    rotation_status: int
    old_token_status: int
    new_token_status: int
    credential_count: int


class PairingSmokeError(RuntimeError):
    pass


def require_status(response: Any, expected_status: int, label: str) -> None:
    if response.status_code != expected_status:
        raise PairingSmokeError(
            f"{label} returned HTTP {response.status_code}, expected {expected_status}."
        )


def require_no_store(response: Any, label: str) -> None:
    if (
        response.headers.get("cache-control") != "no-store"
        or response.headers.get("pragma") != "no-cache"
    ):
        raise PairingSmokeError(f"{label} did not return no-store cache headers.")


def create_smoke_app(database_path: Path) -> TestClient:
    settings = HubSettings(
        auth_token=SecretStr(BOOTSTRAP_TOKEN),
        pairing_database_path=database_path,
        pairing_challenge_ttl_seconds=120,
    )
    return TestClient(
        create_app(settings),
        base_url="http://127.0.0.1:8787",
        client=("127.0.0.1", 50_000),
    )


def initialize_mcp_response(client: TestClient, access_token: str) -> Any:
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pairing-smoke", "version": "1.0.0"},
            },
        },
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )


def verify_pairing_flow(output: Path | None = None, force: bool = False) -> PairingSmokeResult:
    with tempfile.TemporaryDirectory(prefix="goffy-pairing-smoke-") as temporary_directory:
        database_path = Path(temporary_directory).resolve() / "credentials.sqlite3"
        with create_smoke_app(database_path) as client:
            identity_response = client.get("/admin/v1/hub-identity", headers=BOOTSTRAP_HEADERS)
            require_status(identity_response, 200, "Hub identity retrieval")
            require_no_store(identity_response, "Hub identity retrieval")
            identity = identity_response.json()
            expected_identity_keys = {
                "schemaVersion",
                "hubId",
                "fingerprint",
                "createdAt",
                "verifiedBy",
                "trustedLanSupported",
                "trustContract",
            }
            if (
                set(identity) != expected_identity_keys
                or identity["schemaVersion"] != "goffy.hub.identity.v1"
                or not isinstance(identity["fingerprint"], str)
                or not identity["fingerprint"].startswith("sha256:")
                or identity["trustedLanSupported"]
                or identity["trustContract"] != EXPECTED_VERIFIER_TRUST_CONTRACT
                or "identitySeed" in identity_response.text
            ):
                raise PairingSmokeError("Hub identity response is invalid")
            repeated_identity_response = client.get(
                "/admin/v1/hub-identity",
                headers=BOOTSTRAP_HEADERS,
            )
            require_status(repeated_identity_response, 200, "repeated Hub identity retrieval")
            if repeated_identity_response.json() != identity:
                raise PairingSmokeError("Hub identity was not stable during the smoke run")

            bundle_response = client.post(
                "/admin/v1/pairing/bundles",
                headers=BOOTSTRAP_HEADERS,
            )
            require_status(bundle_response, 201, "pairing bundle creation")
            require_no_store(bundle_response, "pairing bundle creation")
            bundle = bundle_response.json()
            validate_pairing_bundle(bundle)
            if bundle["hubIdentity"].get("trustContract") != EXPECTED_VERIFIER_TRUST_CONTRACT:
                raise PairingSmokeError("Pairing bundle trust contract is invalid")

            payload = canonical_bundle_payload(bundle)
            if output is not None:
                write_private_text(output, svg_qr(payload), force=force)

            challenge = bundle["challenge"]
            if not isinstance(challenge, dict):
                raise PairingSmokeError("pairing bundle challenge is invalid")
            redemption_request = {
                "challengeId": challenge["challengeId"],
                "pairingToken": challenge["pairingToken"],
                "deviceId": "goffy-smoke-android",
                "displayName": "GOFFY smoke phone",
                "approvalPublicKey": approval_public_key_request(),
            }

            redemption_response = client.post("/pairing/v1/redeem", json=redemption_request)
            require_status(redemption_response, 201, "pairing redemption")
            require_no_store(redemption_response, "pairing redemption")
            credential = redemption_response.json()
            if credential.get("hubIdentity") != bundle["hubIdentity"]:
                raise PairingSmokeError("pairing redemption Hub identity did not match bundle")
            if "identitySeed" in redemption_response.text:
                raise PairingSmokeError("pairing redemption exposed private Hub identity material")

            replay_response = client.post("/pairing/v1/redeem", json=redemption_request)
            if replay_response.status_code == 201:
                raise PairingSmokeError("pairing challenge replay unexpectedly succeeded")

            rotation_response = client.post(
                "/pairing/v1/rotate",
                headers={"Authorization": f"Bearer {credential['accessToken']}"},
            )
            require_status(rotation_response, 200, "credential rotation")
            require_no_store(rotation_response, "credential rotation")
            rotated = rotation_response.json()
            if (
                rotated["credentialId"] != credential["credentialId"]
                or rotated["accessToken"] == credential["accessToken"]
            ):
                raise PairingSmokeError("credential rotation returned invalid authority")

            old_token_response = initialize_mcp_response(client, credential["accessToken"])
            if old_token_response.status_code != 401:
                raise PairingSmokeError("old credential token remained usable after rotation")
            new_token_response = initialize_mcp_response(client, rotated["accessToken"])
            require_status(new_token_response, 200, "rotated credential authentication")

            list_response = client.get("/admin/v1/credentials", headers=BOOTSTRAP_HEADERS)
            require_status(list_response, 200, "credential listing")
            listing_text = list_response.text
            if (
                credential["accessToken"] in listing_text
                or rotated["accessToken"] in listing_text
                or challenge["pairingToken"] in listing_text
            ):
                raise PairingSmokeError("credential listing leaked pairing material")
            credentials = list_response.json()["credentials"]
            if (
                len(credentials) != 1
                or credentials[0]["credentialId"] != credential["credentialId"]
            ):
                raise PairingSmokeError("credential listing did not contain the issued credential")

            return PairingSmokeResult(
                credential_id=credential["credentialId"],
                bundle_payload_bytes=len(payload.encode("utf-8")),
                output=output,
                identity_status=identity_response.status_code,
                replay_status=replay_response.status_code,
                rotation_status=rotation_response.status_code,
                old_token_status=old_token_response.status_code,
                new_token_status=new_token_response.status_code,
                credential_count=len(credentials),
            )


def result_json(result: PairingSmokeResult) -> str:
    return json.dumps(
        {
            "verified": True,
            "credentialId": result.credential_id,
            "bundlePayloadBytes": result.bundle_payload_bytes,
            "qrOutput": str(result.output) if result.output is not None else None,
            "identityStatus": result.identity_status,
            "replayStatus": result.replay_status,
            "rotationStatus": result.rotation_status,
            "oldTokenStatus": result.old_token_status,
            "newTokenStatus": result.new_token_status,
            "credentialCount": result.credential_count,
        },
        indent=2,
        sort_keys=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional SVG QR output path. Treat this artifact as a short-lived secret.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite --output if it exists.")
    args = parser.parse_args()
    try:
        result = verify_pairing_flow(output=args.output, force=args.force)
    except PairingSmokeError as error:
        raise SystemExit(str(error)) from error
    print(result_json(result))
    if args.output is not None:
        print("Delete the QR SVG after inspection; it encodes a short-lived pairing challenge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
