from __future__ import annotations

import argparse
import json
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from ipaddress import ip_address
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import UUID

PAIRING_BUNDLE_PATH = "/admin/v1/pairing/bundles"
DEFAULT_HUB_URL = "http://127.0.0.1:8787"
DEFAULT_OUTPUT = Path("goffy-pairing-bundle.svg")
MAX_BUNDLE_BYTES = 4096
TIMEOUT_SECONDS = 5.0
PAIRING_BUNDLE_VERSION = "goffy.pairing.bundle.v3"
PAIRING_QR_ARTIFACT_MARKER = "GOFFY_PAIRING_QR_ARTIFACT_V1"
EXPECTED_HUB_TRUST_CONTRACT = {
    "schemaVersion": "goffy.hub.trust.v1",
    "proofKind": "loopback_fingerprint_only",
    "transportScope": "usb_loopback_only",
    "publicKeyPinStatus": "absent",
    "certificatePinStatus": "absent",
    "trustedLanSupported": False,
}
PAIRING_ENDPOINT_PATTERN = re.compile(r"^wss?://127\.0\.0\.1(?::[0-9]{1,5})?/ws/v1$")
TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)

UrlOpen = Callable[[Request, float], Any]


@dataclass(frozen=True)
class PairingQrArtifact:
    output: Path
    expires_at: str
    hub_endpoint: str
    payload_bytes: int


class PairingQrError(RuntimeError):
    pass


def is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    normalized = hostname.strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def pairing_bundle_url(hub_url: str) -> str:
    parsed = urlparse(hub_url)
    if parsed.scheme != "http" or not is_loopback_host(parsed.hostname):
        raise PairingQrError("Pairing QR creation currently requires an http loopback Hub URL.")
    if parsed.username or parsed.password:
        raise PairingQrError("Credentials are not allowed in the Hub URL.")
    base = hub_url.rstrip("/") + "/"
    return urljoin(base, PAIRING_BUNDLE_PATH.lstrip("/"))


def read_bounded_response(response: Any) -> bytes:
    data = cast(bytes, response.read(MAX_BUNDLE_BYTES + 1))
    if len(data) > MAX_BUNDLE_BYTES:
        raise PairingQrError("Hub pairing bundle response is too large.")
    return data


def default_urlopen(request: Request, timeout: float) -> Any:
    return urlopen(request, timeout=timeout)  # noqa: S310 - request URL is loopback-guarded.


def fetch_pairing_bundle(
    hub_url: str,
    token: str,
    *,
    timeout: float = TIMEOUT_SECONDS,
    opener: UrlOpen = default_urlopen,
) -> Mapping[str, Any]:
    if not token:
        raise PairingQrError("Set GOFFY_HUB_TOKEN or pass --token.")
    url = pairing_bundle_url(hub_url)
    request = Request(  # noqa: S310 - URL is restricted to loopback above.
        url,
        method="POST",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with opener(request, timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise PairingQrError("Hub returned a non-JSON pairing bundle response.")
            data = read_bounded_response(response)
    except HTTPError as error:
        message = f"Hub rejected pairing bundle creation with HTTP {error.code}."
        raise PairingQrError(message) from error
    except URLError as error:
        raise PairingQrError("Hub pairing endpoint could not be reached.") from error

    try:
        bundle = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PairingQrError("Hub returned malformed pairing bundle JSON.") from error
    if not isinstance(bundle, dict):
        raise PairingQrError("Hub returned a non-object pairing bundle.")
    validate_pairing_bundle(bundle)
    return bundle


def validate_pairing_bundle(bundle: Mapping[str, Any]) -> None:
    expected_keys = {"bundleVersion", "hubEndpoint", "hubIdentity", "challenge"}
    if set(bundle) != expected_keys:
        raise PairingQrError("Hub pairing bundle has an unexpected shape.")
    if bundle["bundleVersion"] != PAIRING_BUNDLE_VERSION:
        raise PairingQrError("Hub pairing bundle version is unsupported.")
    if not _is_hub_endpoint(bundle["hubEndpoint"]):
        raise PairingQrError("Hub pairing bundle endpoint is invalid.")
    identity = bundle["hubIdentity"]
    challenge = bundle["challenge"]
    if not isinstance(identity, dict) or set(identity) != {
        "schemaVersion",
        "hubId",
        "fingerprint",
        "createdAt",
        "mode",
        "verifiedBy",
        "trustedLanSupported",
        "trustContract",
    }:
        raise PairingQrError("Hub pairing bundle identity is invalid.")
    if (
        identity["schemaVersion"] != "goffy.hub.identity.v1"
        or not _is_uuid(identity["hubId"])
        or not isinstance(identity["fingerprint"], str)
        or not identity["fingerprint"].startswith("sha256:")
        or len(identity["fingerprint"]) != len("sha256:") + 64
        or any(character not in "0123456789abcdef" for character in identity["fingerprint"][7:])
        or not _is_datetime(identity["createdAt"])
        or identity["mode"] != "usb_loopback"
        or identity["verifiedBy"] != "loopback_admin_session"
        or identity["trustedLanSupported"] is not False
        or identity["trustContract"] != EXPECTED_HUB_TRUST_CONTRACT
    ):
        raise PairingQrError("Hub pairing bundle identity is not USB-loopback-only.")
    if not isinstance(challenge, dict) or set(challenge) != {
        "challengeId",
        "pairingToken",
        "expiresAt",
    }:
        raise PairingQrError("Hub pairing bundle challenge is invalid.")
    if (
        not _is_uuid(challenge["challengeId"])
        or not isinstance(challenge["pairingToken"], str)
        or not 32 <= len(challenge["pairingToken"]) <= 128
        or not _is_datetime(challenge["expiresAt"])
    ):
        raise PairingQrError("Hub pairing bundle challenge fields are invalid.")


def _is_hub_endpoint(value: object) -> bool:
    if not isinstance(value, str) or not PAIRING_ENDPOINT_PATTERN.fullmatch(value):
        return False
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    if port is not None and not 1 <= port <= 65_535:
        return False
    return parsed.hostname == "127.0.0.1" and parsed.path == "/ws/v1"


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    with suppress(ValueError):
        return str(UUID(value)) == value.lower()
    return False


def _is_datetime(value: object) -> bool:
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        return False
    with suppress(ValueError):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    return False


def canonical_bundle_payload(bundle: Mapping[str, Any]) -> str:
    return json.dumps(bundle, separators=(",", ":"), sort_keys=True)


def write_private_text(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise PairingQrError(f"{path} already exists. Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    if not force:
        flags |= os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise PairingQrError(f"{path} could not be opened safely for writing.") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise PairingQrError("QR output must be a regular file.")
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            descriptor = -1
            file.write(content)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise


def svg_qr(payload: str) -> str:
    try:
        import segno
    except ImportError as error:
        raise PairingQrError(
            "Install development dependencies with `.venv/bin/pip install -e '.[dev]'`."
        ) from error
    qr = segno.make(payload, error="m", encoding="utf-8")
    buffer = BytesIO()
    qr.save(buffer, kind="svg", scale=8, border=4, xmldecl=True)
    svg = buffer.getvalue().decode("utf-8")
    return svg.replace(
        "\n",
        f"\n<!-- {PAIRING_QR_ARTIFACT_MARKER}: short-lived local pairing secret -->\n",
        1,
    )


def create_pairing_qr(
    *,
    hub_url: str,
    token: str,
    output: Path,
    force: bool,
    opener: UrlOpen = default_urlopen,
) -> PairingQrArtifact:
    bundle = fetch_pairing_bundle(hub_url, token, opener=opener)
    payload = canonical_bundle_payload(bundle)
    write_private_text(output, svg_qr(payload), force=force)
    challenge = bundle["challenge"]
    if not isinstance(challenge, Mapping):
        raise PairingQrError("Hub pairing bundle challenge is invalid.")
    expires_at = challenge["expiresAt"]
    hub_endpoint = bundle["hubEndpoint"]
    if not isinstance(expires_at, str) or not isinstance(hub_endpoint, str):
        raise PairingQrError("Hub pairing bundle fields are invalid.")
    return PairingQrArtifact(
        output=output,
        expires_at=expires_at,
        hub_endpoint=hub_endpoint,
        payload_bytes=len(payload.encode("utf-8")),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub-url", default=DEFAULT_HUB_URL)
    parser.add_argument("--token", default=os.environ.get("GOFFY_HUB_TOKEN", ""))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        artifact = create_pairing_qr(
            hub_url=args.hub_url,
            token=args.token,
            output=args.output,
            force=args.force,
        )
    except PairingQrError as error:
        raise SystemExit(str(error)) from error

    print(f"Wrote pairing QR SVG: {artifact.output}")
    print(f"Hub endpoint: {artifact.hub_endpoint}")
    print(f"Bundle expires at: {artifact.expires_at}")
    print(f"QR payload bytes: {artifact.payload_bytes}")
    print("Treat the SVG as a short-lived secret and delete it after pairing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
