from __future__ import annotations

import argparse
import json
import os
import stat
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from io import BytesIO
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

PAIRING_BUNDLE_PATH = "/admin/v1/pairing/bundles"
DEFAULT_HUB_URL = "http://127.0.0.1:8787"
DEFAULT_OUTPUT = Path("goffy-pairing-bundle.svg")
MAX_BUNDLE_BYTES = 4096
TIMEOUT_SECONDS = 5.0
PAIRING_BUNDLE_VERSION = "goffy.pairing.bundle.v1"

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
    data = response.read(MAX_BUNDLE_BYTES + 1)
    if len(data) > MAX_BUNDLE_BYTES:
        raise PairingQrError("Hub pairing bundle response is too large.")
    return data


def fetch_pairing_bundle(
    hub_url: str,
    token: str,
    *,
    timeout: float = TIMEOUT_SECONDS,
    opener: UrlOpen = urlopen,
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
    if not isinstance(bundle["hubEndpoint"], str) or not bundle["hubEndpoint"]:
        raise PairingQrError("Hub pairing bundle endpoint is invalid.")
    identity = bundle["hubIdentity"]
    challenge = bundle["challenge"]
    if not isinstance(identity, dict) or set(identity) != {
        "mode",
        "verifiedBy",
        "trustedLanSupported",
    }:
        raise PairingQrError("Hub pairing bundle identity is invalid.")
    if identity != {
        "mode": "usb_loopback",
        "verifiedBy": "loopback_admin_session",
        "trustedLanSupported": False,
    }:
        raise PairingQrError("Hub pairing bundle identity is not USB-loopback-only.")
    if not isinstance(challenge, dict) or set(challenge) != {
        "challengeId",
        "pairingToken",
        "expiresAt",
    }:
        raise PairingQrError("Hub pairing bundle challenge is invalid.")
    if not all(isinstance(challenge[key], str) and challenge[key] for key in challenge):
        raise PairingQrError("Hub pairing bundle challenge fields are invalid.")


def canonical_bundle_payload(bundle: Mapping[str, Any]) -> str:
    return json.dumps(bundle, separators=(",", ":"), sort_keys=True)


def write_private_text(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise PairingQrError(f"{path} already exists. Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if not force:
        flags |= os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        with suppress(OSError):
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
    return buffer.getvalue().decode("utf-8")


def create_pairing_qr(
    *,
    hub_url: str,
    token: str,
    output: Path,
    force: bool,
    opener: UrlOpen = urlopen,
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
