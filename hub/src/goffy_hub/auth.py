from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from hmac import compare_digest
from uuid import UUID

from goffy_hub.credentials import CredentialStore, CredentialStoreError, PairedCredential
from goffy_hub.settings import HubSettings

BEARER_PREFIX = "Bearer "
MAX_BEARER_LENGTH = 512
HUB_ISSUER = "goffy-hub"
SAFE_TOOL_SCOPE = "goffy.tools.safe"
PAIRING_ADMIN_SCOPE = "goffy.pairing.admin"


class PrincipalKind(StrEnum):
    BOOTSTRAP = "bootstrap"
    PAIRED = "paired"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    kind: PrincipalKind
    client_id: str
    subject: str
    scopes: tuple[str, ...]
    credential_id: UUID | None = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


class CredentialAuthenticator:
    def __init__(
        self,
        settings: HubSettings,
        credential_store: CredentialStore | None,
    ) -> None:
        self._settings = settings
        self._credential_store = credential_store

    @property
    def pairing_enabled(self) -> bool:
        return self._credential_store is not None

    async def authenticate_header(self, authorization: str | None) -> AuthenticatedPrincipal | None:
        if authorization is None or not authorization.startswith(BEARER_PREFIX):
            return None
        return await self.authenticate_token(authorization.removeprefix(BEARER_PREFIX))

    async def authenticate_token(self, token: str) -> AuthenticatedPrincipal | None:
        if not token or len(token) > MAX_BEARER_LENGTH:
            return None

        bootstrap = self._settings.auth_token
        if bootstrap is not None and compare_digest(token, bootstrap.get_secret_value()):
            scopes = (PAIRING_ADMIN_SCOPE,) if self.pairing_enabled else (SAFE_TOOL_SCOPE,)
            return AuthenticatedPrincipal(
                kind=PrincipalKind.BOOTSTRAP,
                client_id="goffy-bootstrap",
                subject="bootstrap-operator",
                scopes=scopes,
            )

        if self._credential_store is None:
            return None
        try:
            credential = await asyncio.to_thread(self._credential_store.authenticate, token)
        except CredentialStoreError:
            return None
        return _paired_principal(credential) if credential is not None else None

    async def is_active(self, principal: AuthenticatedPrincipal) -> bool:
        if principal.kind is PrincipalKind.BOOTSTRAP:
            return self._settings.auth_token is not None
        if self._credential_store is None or principal.credential_id is None:
            return False
        try:
            return await asyncio.to_thread(
                self._credential_store.is_active,
                principal.credential_id,
            )
        except CredentialStoreError:
            return False

    async def tool_access_enabled(self) -> bool:
        if self._credential_store is None:
            return self._settings.auth_token is not None
        try:
            return await asyncio.to_thread(self._credential_store.active_count) > 0
        except CredentialStoreError:
            return False


def _paired_principal(credential: PairedCredential) -> AuthenticatedPrincipal:
    credential_id = credential.credential_id
    principal_id = paired_client_id(credential_id)
    return AuthenticatedPrincipal(
        kind=PrincipalKind.PAIRED,
        client_id=principal_id,
        subject=principal_id,
        scopes=(SAFE_TOOL_SCOPE,),
        credential_id=credential_id,
    )


def paired_client_id(credential_id: UUID) -> str:
    return f"goffy-paired:{credential_id}"
