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
        mcp_allowed_hosts=("goffy.local:8787",),
    )

    assert settings.allow_lan is True


def test_local_mcp_transport_defaults_are_exact() -> None:
    settings = HubSettings()

    assert settings.resolved_mcp_allowed_hosts == [
        "127.0.0.1:8787",
        "localhost:8787",
        "[::1]:8787",
    ]
    assert settings.resolved_mcp_allowed_origins == [
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://[::1]:8787",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mcp_allowed_hosts", ("*",)),
        ("mcp_allowed_hosts", ("goffy.local:*",)),
        ("mcp_allowed_hosts", ("https://goffy.local",)),
        ("mcp_allowed_origins", ("https://goffy.local:*",)),
        ("mcp_allowed_origins", ("https://goffy.local/path",)),
        ("mcp_allowed_origins", ("file://goffy.local",)),
    ],
)
def test_mcp_transport_allowlists_reject_ambiguous_values(
    field: str, value: tuple[str, ...]
) -> None:
    with pytest.raises(ValidationError):
        HubSettings.model_validate({field: value})


def test_mcp_environment_allowlists_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOFFY_MCP_ALLOWED_HOSTS", "goffy.local:8787, goffy.test:8787")
    monkeypatch.setenv("GOFFY_MCP_ALLOWED_ORIGINS", "https://goffy.local:8787")
    monkeypatch.setenv("GOFFY_MCP_MAX_CONCURRENT_CALLS", "3")
    monkeypatch.setenv("GOFFY_MCP_MAX_ACTIVE_SESSIONS", "4")
    monkeypatch.setenv("GOFFY_TOOL_HEALTH_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("GOFFY_TOOL_HEALTH_INTERVAL_SECONDS", "45")

    settings = HubSettings.from_environment()

    assert settings.mcp_allowed_hosts == ("goffy.local:8787", "goffy.test:8787")
    assert settings.mcp_allowed_origins == ("https://goffy.local:8787",)
    assert settings.mcp_max_concurrent_calls == 3
    assert settings.mcp_max_active_sessions == 4
    assert settings.tool_health_timeout_seconds == 2
    assert settings.tool_health_interval_seconds == 45


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_health_timeout_seconds", 0),
        ("tool_health_timeout_seconds", 5.1),
        ("tool_health_interval_seconds", 4.9),
        ("tool_health_interval_seconds", 301),
    ],
)
def test_tool_health_settings_are_bounded(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        HubSettings.model_validate({field: value})
