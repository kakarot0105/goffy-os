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


def test_paired_mode_rejects_non_local_binding_even_with_lan_tls(tmp_path: Path) -> None:
    certificate = tmp_path / "certificate.pem"
    private_key = tmp_path / "private-key.pem"
    certificate.write_text("test certificate", encoding="utf-8")
    private_key.write_text("test key", encoding="utf-8")

    with pytest.raises(ValidationError, match="paired mode requires a local"):
        HubSettings(
            host="0.0.0.0",
            allow_lan=True,
            tls_cert_file=certificate,
            tls_key_file=private_key,
            mcp_allowed_hosts=("goffy.local:8787",),
            pairing_database_path=tmp_path / "credentials.sqlite3",
        )


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
    monkeypatch.setenv("GOFFY_OPERATOR_AUDIT_MAX_EVENTS", "128")
    monkeypatch.setenv("GOFFY_TOOL_HEALTH_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("GOFFY_TOOL_HEALTH_INTERVAL_SECONDS", "45")
    pairing_database = Path("/Users/test/.goffy/credentials.sqlite3")
    monkeypatch.setenv("GOFFY_PAIRING_DATABASE_PATH", str(pairing_database))
    monkeypatch.setenv("GOFFY_PAIRING_CHALLENGE_TTL_SECONDS", "90")

    settings = HubSettings.from_environment()

    assert settings.mcp_allowed_hosts == ("goffy.local:8787", "goffy.test:8787")
    assert settings.mcp_allowed_origins == ("https://goffy.local:8787",)
    assert settings.mcp_max_concurrent_calls == 3
    assert settings.mcp_max_active_sessions == 4
    assert settings.operator_audit_max_events == 128
    assert settings.tool_health_timeout_seconds == 2
    assert settings.tool_health_interval_seconds == 45
    assert settings.pairing_database_path == pairing_database
    assert settings.pairing_challenge_ttl_seconds == 90


def test_clipboard_read_is_disabled_by_default() -> None:
    assert HubSettings().mac_clipboard_read_enabled is False


def test_clipboard_read_environment_flag_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOFFY_MAC_CLIPBOARD_READ_ENABLED", " TRUE ")

    settings = HubSettings.from_environment()

    assert settings.mac_clipboard_read_enabled is True


def test_clipboard_read_environment_flag_rejects_ambiguous_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOFFY_MAC_CLIPBOARD_READ_ENABLED", "yes")

    with pytest.raises(ValueError, match="GOFFY_MAC_CLIPBOARD_READ_ENABLED"):
        HubSettings.from_environment()


def test_mac_files_roots_are_explicit_existing_directories(tmp_path: Path) -> None:
    root = tmp_path / "approved"
    root.mkdir()

    settings = HubSettings(mac_files_roots=(root,))

    assert settings.mac_files_roots == (root.resolve(),)


def test_mac_files_roots_environment_is_parsed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv("GOFFY_MAC_FILES_ROOTS", f"{first}, {second}")

    settings = HubSettings.from_environment()

    assert settings.mac_files_roots == (first.resolve(), second.resolve())


@pytest.mark.parametrize("value", [Path("relative"), Path("/definitely/not/goffy-os")])
def test_mac_files_roots_reject_unsafe_entries(value: Path) -> None:
    with pytest.raises(ValidationError, match="GOFFY_MAC_FILES_ROOTS"):
        HubSettings(mac_files_roots=(value,))


def test_mac_files_roots_reject_duplicates(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unique"):
        HubSettings(mac_files_roots=(tmp_path, tmp_path))


def test_git_repo_roots_are_explicit_existing_directories(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    settings = HubSettings(git_repo_roots=(root,))

    assert settings.git_repo_roots == (root.resolve(),)


def test_git_repo_roots_environment_is_parsed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.setenv("GOFFY_GIT_REPO_ROOTS", f"{first}, {second}")

    settings = HubSettings.from_environment()

    assert settings.git_repo_roots == (first.resolve(), second.resolve())


@pytest.mark.parametrize("value", [Path("relative"), Path("/definitely/not/goffy-os")])
def test_git_repo_roots_reject_unsafe_entries(value: Path) -> None:
    with pytest.raises(ValidationError, match="GOFFY_GIT_REPO_ROOTS"):
        HubSettings(git_repo_roots=(value,))


def test_git_repo_roots_reject_duplicates(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unique"):
        HubSettings(git_repo_roots=(tmp_path, tmp_path))


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


def test_pairing_database_path_must_be_absolute() -> None:
    with pytest.raises(ValidationError, match="GOFFY_PAIRING_DATABASE_PATH"):
        HubSettings(pairing_database_path=Path("relative.sqlite3"))


def test_state_paths_are_derived_only_in_paired_mode(tmp_path: Path) -> None:
    database_path = tmp_path / "state" / "credentials.sqlite3"

    assert HubSettings().resolved_hub_identity_path is None
    assert HubSettings().resolved_operator_audit_path is None
    assert HubSettings(pairing_database_path=database_path).resolved_hub_identity_path == (
        tmp_path / "state" / "hub-identity.json"
    )
    assert HubSettings(pairing_database_path=database_path).resolved_operator_audit_path == (
        tmp_path / "state" / "operator-audit.sqlite3"
    )


@pytest.mark.parametrize("value", [29, 301])
def test_pairing_challenge_ttl_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        HubSettings(pairing_challenge_ttl_seconds=value)


def test_operator_audit_max_events_is_bounded() -> None:
    with pytest.raises(ValidationError):
        HubSettings(operator_audit_max_events=15)
