from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from goffy_hub.identity import identity_path_for_credential_database

LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class HubSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)
    allow_lan: bool = False
    auth_token: SecretStr | None = Field(default=None, min_length=24)
    pairing_database_path: Path | None = None
    pairing_challenge_ttl_seconds: int = Field(default=120, ge=30, le=300)
    tls_cert_file: Path | None = None
    tls_key_file: Path | None = None
    max_message_bytes: int = Field(default=32_768, ge=1_024, le=1_048_576)
    tool_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    tool_health_timeout_seconds: float = Field(default=1.0, gt=0, le=5)
    tool_health_interval_seconds: float = Field(default=30.0, ge=5, le=300)
    mcp_allowed_hosts: tuple[str, ...] = ()
    mcp_allowed_origins: tuple[str, ...] = ()
    mcp_max_concurrent_calls: int = Field(default=2, ge=1, le=8)
    mcp_max_active_sessions: int = Field(default=8, ge=1, le=64)
    operator_audit_max_events: int = Field(default=256, ge=16, le=2048)
    mac_files_roots: tuple[Path, ...] = Field(default=(), max_length=8)
    git_repo_roots: tuple[Path, ...] = Field(default=(), max_length=8)
    mac_clipboard_read_enabled: bool = False

    @model_validator(mode="after")
    def guard_network_binding(self) -> HubSettings:
        if (self.tls_cert_file is None) != (self.tls_key_file is None):
            raise ValueError("TLS certificate and key must be configured together")

        for tls_file in (self.tls_cert_file, self.tls_key_file):
            if tls_file is not None and not tls_file.is_file():
                raise ValueError("configured TLS files must exist and be regular files")

        if self.pairing_database_path is not None and not self.pairing_database_path.is_absolute():
            raise ValueError("GOFFY_PAIRING_DATABASE_PATH must be absolute")
        if self.pairing_database_path is not None and self.host not in LOCAL_HOSTS:
            raise ValueError("paired mode requires a local Hub binding")

        if self.host not in LOCAL_HOSTS and not self.allow_lan:
            raise ValueError("non-local Hub binding requires GOFFY_HUB_ALLOW_LAN=true")
        if self.host not in LOCAL_HOSTS and self.tls_cert_file is None:
            raise ValueError("non-local Hub binding requires TLS certificate and key files")
        if self.host not in LOCAL_HOSTS and not self.mcp_allowed_hosts:
            raise ValueError("non-local Hub binding requires GOFFY_MCP_ALLOWED_HOSTS")
        if len(set(self.mcp_allowed_hosts)) != len(self.mcp_allowed_hosts):
            raise ValueError("MCP allowed hosts must be unique")
        if len(set(self.mcp_allowed_origins)) != len(self.mcp_allowed_origins):
            raise ValueError("MCP allowed origins must be unique")

        for allowed_host in self.mcp_allowed_hosts:
            _validate_allowed_host(allowed_host)
        for allowed_origin in self.mcp_allowed_origins:
            _validate_allowed_origin(allowed_origin)
        resolved_mac_roots: list[Path] = []
        for root in self.mac_files_roots:
            if not root.is_absolute():
                raise ValueError("GOFFY_MAC_FILES_ROOTS entries must be absolute directories")
            try:
                resolved = root.expanduser().resolve(strict=True)
            except OSError as exc:
                raise ValueError(
                    "GOFFY_MAC_FILES_ROOTS entries must be existing directories"
                ) from exc
            if not resolved.is_dir():
                raise ValueError("GOFFY_MAC_FILES_ROOTS entries must be existing directories")
            resolved_mac_roots.append(resolved)
        if len(set(resolved_mac_roots)) != len(resolved_mac_roots):
            raise ValueError("GOFFY_MAC_FILES_ROOTS entries must be unique")
        self.mac_files_roots = tuple(resolved_mac_roots)
        resolved_git_roots: list[Path] = []
        for root in self.git_repo_roots:
            if not root.is_absolute():
                raise ValueError("GOFFY_GIT_REPO_ROOTS entries must be absolute directories")
            try:
                resolved = root.expanduser().resolve(strict=True)
            except OSError as exc:
                raise ValueError(
                    "GOFFY_GIT_REPO_ROOTS entries must be existing directories"
                ) from exc
            if not resolved.is_dir():
                raise ValueError("GOFFY_GIT_REPO_ROOTS entries must be existing directories")
            resolved_git_roots.append(resolved)
        if len(set(resolved_git_roots)) != len(resolved_git_roots):
            raise ValueError("GOFFY_GIT_REPO_ROOTS entries must be unique")
        self.git_repo_roots = tuple(resolved_git_roots)
        return self

    @property
    def resolved_mcp_allowed_hosts(self) -> list[str]:
        if self.mcp_allowed_hosts:
            return list(self.mcp_allowed_hosts)
        return [
            f"127.0.0.1:{self.port}",
            f"localhost:{self.port}",
            f"[::1]:{self.port}",
        ]

    @property
    def resolved_mcp_allowed_origins(self) -> list[str]:
        if self.mcp_allowed_origins:
            return list(self.mcp_allowed_origins)
        scheme = "https" if self.tls_cert_file is not None else "http"
        return [
            f"{scheme}://127.0.0.1:{self.port}",
            f"{scheme}://localhost:{self.port}",
            f"{scheme}://[::1]:{self.port}",
        ]

    @property
    def resolved_hub_identity_path(self) -> Path | None:
        if self.pairing_database_path is None:
            return None
        return identity_path_for_credential_database(self.pairing_database_path)

    @property
    def resolved_operator_audit_path(self) -> Path | None:
        if self.pairing_database_path is None:
            return None
        return self.pairing_database_path.parent / "operator-audit.sqlite3"

    @classmethod
    def from_environment(cls) -> HubSettings:
        token = os.getenv("GOFFY_HUB_TOKEN")
        return cls(
            host=os.getenv("GOFFY_HUB_HOST", "127.0.0.1"),
            port=int(os.getenv("GOFFY_HUB_PORT", "8787")),
            allow_lan=_boolean_environment("GOFFY_HUB_ALLOW_LAN"),
            auth_token=SecretStr(token) if token else None,
            pairing_database_path=_optional_path("GOFFY_PAIRING_DATABASE_PATH"),
            pairing_challenge_ttl_seconds=int(
                os.getenv("GOFFY_PAIRING_CHALLENGE_TTL_SECONDS", "120")
            ),
            tls_cert_file=_optional_path("GOFFY_HUB_TLS_CERT_FILE"),
            tls_key_file=_optional_path("GOFFY_HUB_TLS_KEY_FILE"),
            tool_health_timeout_seconds=float(os.getenv("GOFFY_TOOL_HEALTH_TIMEOUT_SECONDS", "1")),
            tool_health_interval_seconds=float(
                os.getenv("GOFFY_TOOL_HEALTH_INTERVAL_SECONDS", "30")
            ),
            mcp_allowed_hosts=_comma_separated("GOFFY_MCP_ALLOWED_HOSTS"),
            mcp_allowed_origins=_comma_separated("GOFFY_MCP_ALLOWED_ORIGINS"),
            mcp_max_concurrent_calls=int(os.getenv("GOFFY_MCP_MAX_CONCURRENT_CALLS", "2")),
            mcp_max_active_sessions=int(os.getenv("GOFFY_MCP_MAX_ACTIVE_SESSIONS", "8")),
            operator_audit_max_events=int(os.getenv("GOFFY_OPERATOR_AUDIT_MAX_EVENTS", "256")),
            mac_files_roots=_path_tuple("GOFFY_MAC_FILES_ROOTS"),
            git_repo_roots=_path_tuple("GOFFY_GIT_REPO_ROOTS"),
            mac_clipboard_read_enabled=_boolean_environment("GOFFY_MAC_CLIPBOARD_READ_ENABLED"),
        )


def _optional_path(environment_name: str) -> Path | None:
    value = os.getenv(environment_name)
    return Path(value).expanduser() if value else None


def _comma_separated(environment_name: str) -> tuple[str, ...]:
    value = os.getenv(environment_name)
    if value is None or not value.strip():
        return ()
    entries = tuple(part.strip() for part in value.split(","))
    if any(not entry for entry in entries):
        raise ValueError(f"{environment_name} contains an empty entry")
    return entries


def _path_tuple(environment_name: str) -> tuple[Path, ...]:
    return tuple(Path(value).expanduser() for value in _comma_separated(environment_name))


def _boolean_environment(environment_name: str) -> bool:
    value = os.getenv(environment_name, "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{environment_name} must be true or false")
    return value == "true"


def _validate_allowed_host(value: str) -> None:
    if (
        not value
        or "*" in value
        or len(value) > 255
        or any(character.isspace() for character in value)
        or "/" in value
        or "\\" in value
        or "://" in value
    ):
        raise ValueError("MCP allowed hosts must be exact Host header values")


def _validate_allowed_origin(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or "*" in value
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("MCP allowed origins must be exact HTTP or HTTPS origins")
