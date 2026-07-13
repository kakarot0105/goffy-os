from __future__ import annotations

import os
from pathlib import Path

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
        return self

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
        )


def _optional_path(environment_name: str) -> Path | None:
    value = os.getenv(environment_name)
    return Path(value).expanduser() if value else None
