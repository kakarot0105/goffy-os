from pathlib import Path

import pytest
from pydantic import ValidationError

from goffy_hub.settings import HubSettings


def test_non_local_binding_requires_explicit_lan_mode() -> None:
    with pytest.raises(ValidationError, match="GOFFY_HUB_ALLOW_LAN"):
        HubSettings(host="0.0.0.0")


def test_explicit_lan_mode_without_tls_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires TLS"):
        HubSettings(host="0.0.0.0", allow_lan=True)


def test_lan_mode_requires_existing_tls_pair(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.pem"
    private_key = tmp_path / "private-key.pem"
    certificate.write_text("test certificate", encoding="utf-8")
    private_key.write_text("test key", encoding="utf-8")

    settings = HubSettings(
        host="0.0.0.0",
        allow_lan=True,
        tls_cert_file=certificate,
        tls_key_file=private_key,
    )

    assert settings.allow_lan is True
