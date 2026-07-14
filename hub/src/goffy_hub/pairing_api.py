from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from ipaddress import ip_address
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
from pydantic.alias_generators import to_camel

from goffy_hub.auth import (
    BEARER_PREFIX,
    PAIRING_ADMIN_SCOPE,
    CredentialAuthenticator,
    PrincipalKind,
)
from goffy_hub.credentials import (
    CredentialCapacityError,
    CredentialStoreError,
    InvalidCredentialMetadataError,
    PairedCredential,
)
from goffy_hub.identity import HUB_IDENTITY_SCHEMA_VERSION, HubIdentity, HubIdentitySchemaVersion
from goffy_hub.pairing import (
    InvalidPairingChallengeError,
    PairingAttemptLimitError,
    PairingBusyError,
    PairingService,
)

RevokeCallback = Callable[[UUID], Awaitable[None]]
DEVICE_ID_PATTERN = r"^[A-Za-z0-9._:-]{1,64}$"
DISPLAY_NAME_PATTERN = r"^[^\x00-\x1F\x7F]{1,80}$"
MAX_PAIRING_REQUEST_BYTES = 2_048
PAIRING_BUNDLE_VERSION: Literal["goffy.pairing.bundle.v2"] = "goffy.pairing.bundle.v2"


class PairingApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )


class PairingChallengeResponse(PairingApiModel):
    challenge_id: UUID
    pairing_token: str = Field(repr=False)
    expires_at: datetime


class PairingBundleHubIdentity(PairingApiModel):
    schema_version: HubIdentitySchemaVersion
    hub_id: UUID
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime
    mode: Literal["usb_loopback"]
    verified_by: Literal["loopback_admin_session"]
    trusted_lan_supported: Literal[False]


class HubIdentityResponse(PairingApiModel):
    schema_version: HubIdentitySchemaVersion
    hub_id: UUID
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime
    verified_by: Literal["loopback_admin_session"]
    trusted_lan_supported: Literal[False]


class PairingBundleResponse(PairingApiModel):
    bundle_version: Literal["goffy.pairing.bundle.v2"]
    hub_endpoint: str = Field(min_length=1, max_length=2048)
    hub_identity: PairingBundleHubIdentity
    challenge: PairingChallengeResponse


class PairingRedemptionRequest(PairingApiModel):
    challenge_id: UUID
    pairing_token: SecretStr = Field(min_length=32, max_length=128)
    device_id: str = Field(pattern=DEVICE_ID_PATTERN)
    display_name: str = Field(pattern=DISPLAY_NAME_PATTERN)

    @field_validator("challenge_id", mode="before")
    @classmethod
    def parse_challenge_id(cls, value: UUID | str) -> UUID:
        return UUID(value) if isinstance(value, str) else value


class PairingSuccessResponse(PairingApiModel):
    credential_id: UUID
    access_token: str = Field(repr=False)
    created_at: datetime
    hub_identity: PairingBundleHubIdentity


class TokenRotationResponse(PairingApiModel):
    credential_id: UUID
    access_token: str = Field(repr=False)
    rotated_at: datetime


class PairedCredentialResponse(PairingApiModel):
    credential_id: UUID
    device_id: str
    display_name: str
    created_at: datetime
    revoked_at: datetime | None


class PairedCredentialListResponse(PairingApiModel):
    credentials: list[PairedCredentialResponse] = Field(max_length=64)


class RevocationResponse(PairingApiModel):
    credential_id: UUID
    revoked: bool


def build_pairing_router(
    authenticator: CredentialAuthenticator,
    pairing_service: PairingService,
    hub_identity: HubIdentity,
    *,
    on_revoke: RevokeCallback,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/admin/v1/hub-identity",
        response_model=HubIdentityResponse,
        response_model_by_alias=True,
    )
    async def read_hub_identity(
        request: Request,
        response: Response,
    ) -> HubIdentityResponse:
        await _require_loopback_admin(request, authenticator)
        _prevent_secret_caching(response)
        return _hub_identity_response(hub_identity)

    @router.post(
        "/admin/v1/pairing/challenges",
        response_model=PairingChallengeResponse,
        response_model_by_alias=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_pairing_challenge(
        request: Request,
        response: Response,
    ) -> PairingChallengeResponse:
        await _require_loopback_admin(request, authenticator)
        challenge = await _begin_pairing_challenge(pairing_service)
        _prevent_secret_caching(response)
        return challenge

    @router.post(
        "/admin/v1/pairing/bundles",
        response_model=PairingBundleResponse,
        response_model_by_alias=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_pairing_bundle(
        request: Request,
        response: Response,
    ) -> PairingBundleResponse:
        await _require_loopback_admin(request, authenticator)
        hub_endpoint = _websocket_endpoint_from_request(request)
        challenge = await _begin_pairing_challenge(pairing_service)
        _prevent_secret_caching(response)
        return PairingBundleResponse(
            bundle_version=PAIRING_BUNDLE_VERSION,
            hub_endpoint=hub_endpoint,
            hub_identity=_pairing_bundle_identity(hub_identity),
            challenge=challenge,
        )

    async def _begin_pairing_challenge(
        service: PairingService,
    ) -> PairingChallengeResponse:
        try:
            await service.check_store()
            challenge = await service.begin()
        except PairingBusyError as error:
            raise _api_error(429, "pairing_busy", "Pairing is temporarily unavailable.") from error
        except CredentialStoreError as error:
            raise _credential_store_unavailable() from error
        return PairingChallengeResponse(
            challenge_id=challenge.challenge_id,
            pairing_token=challenge.pairing_token,
            expires_at=challenge.expires_at,
        )

    @router.post(
        "/pairing/v1/redeem",
        response_model=PairingSuccessResponse,
        response_model_by_alias=True,
        status_code=status.HTTP_201_CREATED,
    )
    async def redeem_pairing_challenge(
        request: Request,
        response: Response,
    ) -> PairingSuccessResponse:
        _require_loopback(request)
        redemption = await _read_redemption(request)
        try:
            issued = await pairing_service.complete(
                redemption.challenge_id,
                redemption.pairing_token.get_secret_value(),
                redemption.device_id,
                redemption.display_name,
            )
        except InvalidPairingChallengeError as error:
            raise _api_error(
                400,
                "invalid_pairing_challenge",
                "Pairing challenge is invalid or expired.",
            ) from error
        except PairingAttemptLimitError as error:
            raise _api_error(
                429, "pairing_attempt_limit", "Pairing attempt limit reached."
            ) from error
        except CredentialCapacityError as error:
            raise _api_error(409, "credential_capacity", "Paired device limit reached.") from error
        except InvalidCredentialMetadataError as error:
            raise _api_error(
                400, "invalid_device_metadata", "Device metadata is invalid."
            ) from error
        except CredentialStoreError as error:
            raise _api_error(
                503,
                "credential_store_unavailable",
                "Credential storage is temporarily unavailable.",
            ) from error

        _prevent_secret_caching(response)
        return PairingSuccessResponse(
            credential_id=issued.credential.credential_id,
            access_token=issued.access_token,
            created_at=issued.credential.created_at,
            hub_identity=_pairing_bundle_identity(hub_identity),
        )

    @router.get(
        "/admin/v1/credentials",
        response_model=PairedCredentialListResponse,
        response_model_by_alias=True,
    )
    async def list_paired_credentials(request: Request) -> PairedCredentialListResponse:
        await _require_loopback_admin(request, authenticator)
        try:
            credentials = await pairing_service.list_credentials()
        except CredentialStoreError as error:
            raise _credential_store_unavailable() from error
        return PairedCredentialListResponse(
            credentials=[_credential_response(credential) for credential in credentials]
        )

    @router.delete(
        "/pairing/v1/self",
        response_model=RevocationResponse,
        response_model_by_alias=True,
    )
    async def revoke_own_paired_credential(
        request: Request,
        response: Response,
    ) -> RevocationResponse:
        _require_loopback(request)
        credential_id = await _require_paired_credential_id(request, authenticator)
        try:
            revoked = await pairing_service.revoke(credential_id)
        except CredentialStoreError as error:
            raise _credential_store_unavailable() from error
        if revoked is None:
            raise _api_error(409, "credential_not_active", "Paired credential is not active.")
        await on_revoke(credential_id)
        _prevent_secret_caching(response)
        return RevocationResponse(credential_id=credential_id, revoked=True)

    @router.post(
        "/pairing/v1/rotate",
        response_model=TokenRotationResponse,
        response_model_by_alias=True,
        status_code=status.HTTP_200_OK,
    )
    async def rotate_own_paired_credential(
        request: Request,
        response: Response,
    ) -> TokenRotationResponse:
        _require_loopback(request)
        credential_id = await _require_paired_credential_id(request, authenticator)
        current_token = _bearer_token_from_request(request)
        if current_token is None:
            raise _api_error(401, "authentication_required", "Paired authentication required.")

        try:
            rotated = await pairing_service.rotate(credential_id, current_token)
        except CredentialStoreError as error:
            raise _credential_store_unavailable() from error
        if rotated is None:
            raise _api_error(
                409,
                "credential_rotation_conflict",
                "Paired credential could not be rotated.",
            )

        await on_revoke(credential_id)
        _prevent_secret_caching(response)
        return TokenRotationResponse(
            credential_id=rotated.credential.credential_id,
            access_token=rotated.access_token,
            rotated_at=rotated.rotated_at,
        )

    @router.delete(
        "/admin/v1/credentials/{credential_id}",
        response_model=RevocationResponse,
        response_model_by_alias=True,
    )
    async def revoke_paired_credential(
        request: Request,
        credential_id: UUID,
    ) -> RevocationResponse:
        await _require_loopback_admin(request, authenticator)
        try:
            revoked = await pairing_service.revoke(credential_id)
        except CredentialStoreError as error:
            raise _credential_store_unavailable() from error
        if revoked is None:
            raise _api_error(404, "credential_not_found", "Active credential was not found.")
        await on_revoke(credential_id)
        return RevocationResponse(credential_id=credential_id, revoked=True)

    return router


async def _require_paired_credential_id(
    request: Request,
    authenticator: CredentialAuthenticator,
) -> UUID:
    principal = await authenticator.authenticate_header(request.headers.get("authorization"))
    if principal is None:
        raise _api_error(401, "authentication_required", "Paired authentication required.")
    if principal.kind is not PrincipalKind.PAIRED or principal.credential_id is None:
        raise _api_error(403, "paired_principal_required", "Paired authentication required.")
    return principal.credential_id


def _bearer_token_from_request(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if authorization is None or not authorization.startswith(BEARER_PREFIX):
        return None
    return authorization.removeprefix(BEARER_PREFIX)


async def _require_loopback_admin(
    request: Request,
    authenticator: CredentialAuthenticator,
) -> None:
    _require_loopback(request)
    principal = await authenticator.authenticate_header(request.headers.get("authorization"))
    if principal is None:
        raise _api_error(401, "authentication_required", "Bootstrap authentication required.")
    if not principal.has_scope(PAIRING_ADMIN_SCOPE):
        raise _api_error(403, "insufficient_scope", "Bootstrap administrator scope required.")


def _require_loopback(request: Request) -> None:
    client = request.client
    if client is None:
        raise _api_error(403, "loopback_required", "Pairing is available on loopback only.")
    try:
        loopback = ip_address(client.host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise _api_error(403, "loopback_required", "Pairing is available on loopback only.")


def _websocket_endpoint_from_request(request: Request) -> str:
    host = request.url.hostname
    if host is None or not _is_loopback_host(host):
        raise _api_error(
            400,
            "loopback_host_required",
            "Pairing bundles require a loopback Host header.",
        )
    settings = request.app.state.settings
    websocket_scheme = "wss" if settings.tls_cert_file is not None else "ws"
    return f"{websocket_scheme}://127.0.0.1:{settings.port}/ws/v1"


def _is_loopback_host(host: str) -> bool:
    normalized = host.lower().removeprefix("[").removesuffix("]")
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _credential_response(credential: PairedCredential) -> PairedCredentialResponse:
    return PairedCredentialResponse(
        credential_id=credential.credential_id,
        device_id=credential.device_id,
        display_name=credential.display_name,
        created_at=credential.created_at,
        revoked_at=credential.revoked_at,
    )


def _hub_identity_response(hub_identity: HubIdentity) -> HubIdentityResponse:
    return HubIdentityResponse(
        schema_version=HUB_IDENTITY_SCHEMA_VERSION,
        hub_id=hub_identity.hub_id,
        fingerprint=hub_identity.fingerprint,
        created_at=hub_identity.created_at,
        verified_by="loopback_admin_session",
        trusted_lan_supported=False,
    )


def _pairing_bundle_identity(hub_identity: HubIdentity) -> PairingBundleHubIdentity:
    return PairingBundleHubIdentity(
        schema_version=HUB_IDENTITY_SCHEMA_VERSION,
        hub_id=hub_identity.hub_id,
        fingerprint=hub_identity.fingerprint,
        created_at=hub_identity.created_at,
        mode="usb_loopback",
        verified_by="loopback_admin_session",
        trusted_lan_supported=False,
    )


async def _read_redemption(request: Request) -> PairingRedemptionRequest:
    content_type = request.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
    if content_type != "application/json":
        raise _api_error(415, "json_required", "Pairing redemption requires JSON.")

    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > MAX_PAIRING_REQUEST_BYTES:
            raise _api_error(413, "pairing_request_too_large", "Pairing request is too large.")
        chunks.append(chunk)
    try:
        return PairingRedemptionRequest.model_validate_json(b"".join(chunks))
    except ValidationError as error:
        raise _api_error(400, "invalid_pairing_request", "Pairing request is invalid.") from error


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _prevent_secret_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _credential_store_unavailable() -> HTTPException:
    return _api_error(
        503,
        "credential_store_unavailable",
        "Credential storage is temporarily unavailable.",
    )
