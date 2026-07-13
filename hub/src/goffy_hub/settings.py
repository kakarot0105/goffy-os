from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class HubSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)
    allow_lan: bool = False
    auth_token: SecretStr | None = Field(default=None, min_length=24)
    tls_cert_file: Path | None = None
    tls_key_file: Path | None = None
    max_message_bytes: int = Field(default=32_768, ge=1_024, le=1_048_576)
    tool_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    mcp_allowed_hosts: tuple[str, ...] = ()
    mcp_allowed_origins: tuple[str, ...] = ()
    mcp_max_concurrent_calls: int = Field(default=2, ge=1, le=8)
    mcp_max_active_sessions: int = Field(default=8, ge=1, le=64)

    @model_validator(mode="after")
    def guard_network_binding(self) -> HubSettings:
        if (self.tls_cert_file is None) != (self.tls_key_file is None):
            raise ValueError("TLS certificate and key must be configured together")

        for tls_file in (self.tls_cert_file, self.tls_key_file):
            if tls_file is not None and not tls_file.is_file():
                raise ValueError("configured TLS files must exist and be regular files")

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

    @classmethod
    def from_environment(cls) -> HubSettings:
        allow_lan = os.getenv("GOFFY_HUB_ALLOW_LAN", "false").strip().lower()
        if allow_lan not in {"true", "false"}:
            raise ValueError("GOFFY_HUB_ALLOW_LAN must be true or false")

        token = os.getenv("GOFFY_HUB_TOKEN")
        return cls(
            host=os.getenv("GOFFY_HUB_HOST", "127.0.0.1"),
            port=int(os.getenv("GOFFY_HUB_PORT", "8787")),
            allow_lan=allow_lan == "true",
            auth_token=SecretStr(token) if token else None,
            tls_cert_file=_optional_path("GOFFY_HUB_TLS_CERT_FILE"),
            tls_key_file=_optional_path("GOFFY_HUB_TLS_KEY_FILE"),
            mcp_allowed_hosts=_comma_separated("GOFFY_MCP_ALLOWED_HOSTS"),
            mcp_allowed_origins=_comma_separated("GOFFY_MCP_ALLOWED_ORIGINS"),
            mcp_max_concurrent_calls=int(os.getenv("GOFFY_MCP_MAX_CONCURRENT_CALLS", "2")),
            mcp_max_active_sessions=int(os.getenv("GOFFY_MCP_MAX_ACTIVE_SESSIONS", "8")),
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
