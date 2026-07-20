from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from goffy_hub.auth import PAIRING_ADMIN_SCOPE, AuthenticatedPrincipal, CredentialAuthenticator
from goffy_hub.operator_audit import OperatorAuditEvent, OperatorAuditLog


class OperatorAuditApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )


class OperatorAuditEventResponse(OperatorAuditApiModel):
    sequence: int
    recorded_at: datetime
    source: str
    action: str
    outcome: str
    principal_kind: str
    credential_id: UUID | None
    detail_code: str | None
    previous_hash: str | None
    event_hash: str | None


class OperatorAuditListResponse(OperatorAuditApiModel):
    storage_kind: str
    integrity: str
    events: list[OperatorAuditEventResponse] = Field(max_length=256)


def build_operator_audit_router(
    authenticator: CredentialAuthenticator,
    audit_log: OperatorAuditLog,
) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/admin/v1/audit/events",
        response_model=OperatorAuditListResponse,
        response_model_by_alias=True,
    )
    async def list_operator_audit_events(
        request: Request,
        response: Response,
        limit: int = Query(default=50, ge=1, le=256),
    ) -> OperatorAuditListResponse:
        await _require_loopback_admin(request, authenticator)
        _prevent_caching(response)
        snapshot = audit_log.snapshot(limit=limit)
        return OperatorAuditListResponse(
            storage_kind=snapshot.storage_kind,
            integrity=snapshot.integrity,
            events=[_event_response(event) for event in snapshot.events],
        )

    return router


async def _require_loopback_admin(
    request: Request,
    authenticator: CredentialAuthenticator,
) -> AuthenticatedPrincipal:
    _require_loopback(request)
    principal = await authenticator.authenticate_header(request.headers.get("authorization"))
    if principal is None:
        raise _api_error(401, "authentication_required", "Bootstrap authentication required.")
    if not principal.has_scope(PAIRING_ADMIN_SCOPE):
        raise _api_error(403, "insufficient_scope", "Bootstrap administrator scope required.")
    return principal


def _require_loopback(request: Request) -> None:
    client = request.client
    if client is None:
        raise _api_error(403, "loopback_required", "Audit retrieval is available on loopback only.")
    try:
        loopback = ip_address(client.host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise _api_error(403, "loopback_required", "Audit retrieval is available on loopback only.")


def _event_response(event: OperatorAuditEvent) -> OperatorAuditEventResponse:
    return OperatorAuditEventResponse(
        sequence=event.sequence,
        recorded_at=event.recorded_at,
        source=event.source,
        action=event.action,
        outcome=event.outcome,
        principal_kind=event.principal_kind,
        credential_id=event.credential_id,
        detail_code=event.detail_code,
        previous_hash=event.previous_hash,
        event_hash=event.event_hash,
    )


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _prevent_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
