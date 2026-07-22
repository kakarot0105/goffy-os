from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key

from goffy_protocol import (
    APPROVAL_PROOF_ALGORITHM,
    APPROVAL_PROOF_SCHEMA_VERSION,
    ApprovalRequestPayload,
    ApprovalResponsePayload,
    ToolInvocationPayload,
)

HUB_APPROVAL_TTL_MILLIS = 60_000
MAX_PENDING_APPROVALS = 1_024
MIN_APPROVAL_PUBLIC_KEY_DER_BYTES = 64
MAX_APPROVAL_PUBLIC_KEY_DER_BYTES = 256
MAX_APPROVAL_SIGNATURE_BYTES = 256
APPROVAL_SIGNING_PAYLOAD_SCHEMA_VERSION = "goffy.approval.signed-payload.v1"


class ApprovalValidationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class IssuedApprovalRecord:
    approval_id: UUID
    principal_key: str
    task_id: UUID
    tool_name: str
    arguments_sha256: str
    issued_at_epoch_millis: int
    expires_at_epoch_millis: int

    def to_payload(self) -> ApprovalRequestPayload:
        return ApprovalRequestPayload(
            schema_version="goffy.approval.v1",
            approval_id=self.approval_id,
            task_id=self.task_id,
            tool_name=self.tool_name,
            arguments_sha256=self.arguments_sha256,
            issued_at_epoch_millis=self.issued_at_epoch_millis,
            expires_at_epoch_millis=self.expires_at_epoch_millis,
        )


class ApprovalArtifactStore:
    def __init__(self, *, now_millis: Callable[[], int] | None = None) -> None:
        self._now_millis = now_millis or (lambda: int(time.time() * 1_000))
        self._pending_approvals: dict[UUID, IssuedApprovalRecord] = {}

    def issue(
        self,
        *,
        principal_key: str,
        invocation: ToolInvocationPayload,
    ) -> IssuedApprovalRecord:
        if invocation.task_id is None:
            raise ApprovalValidationError(
                "approval_required",
                "A Hub-issued approval request requires a task ID.",
            )
        self._prune_expired()
        if len(self._pending_approvals) >= MAX_PENDING_APPROVALS:
            raise ApprovalValidationError(
                "approval_capacity_exceeded",
                "Too many approval requests are pending.",
            )
        issued_at = self._now_millis()
        record = IssuedApprovalRecord(
            approval_id=uuid4(),
            principal_key=principal_key,
            task_id=invocation.task_id,
            tool_name=invocation.tool_name,
            arguments_sha256=canonical_arguments_sha256(invocation.arguments),
            issued_at_epoch_millis=issued_at,
            expires_at_epoch_millis=issued_at + HUB_APPROVAL_TTL_MILLIS,
        )
        self._pending_approvals[record.approval_id] = record
        return record

    def consume(
        self,
        *,
        principal_key: str,
        response: ApprovalResponsePayload,
        invocation: ToolInvocationPayload,
        credential_id: UUID | None,
        approval_public_key_spki_der: bytes | None,
    ) -> IssuedApprovalRecord:
        record = self._pending_approvals.get(response.approval_id)
        if record is None:
            raise ApprovalValidationError(
                "approval_invalid",
                "Approval request is unknown or already consumed.",
            )
        if not response.approved:
            self._pending_approvals.pop(response.approval_id, None)
            raise ApprovalValidationError(
                "approval_denied",
                "Approval was denied; no tool was invoked.",
            )
        self._validate(record, principal_key, response, invocation)
        verify_approval_response_proof(
            record=record,
            response=response,
            credential_id=credential_id,
            approval_public_key_spki_der=approval_public_key_spki_der,
        )
        self._pending_approvals.pop(response.approval_id, None)
        return record

    def discard(self, approval_id: UUID) -> None:
        self._pending_approvals.pop(approval_id, None)

    def _validate(
        self,
        record: IssuedApprovalRecord,
        principal_key: str,
        response: ApprovalResponsePayload,
        invocation: ToolInvocationPayload,
    ) -> None:
        if record.principal_key != principal_key:
            raise ApprovalValidationError(
                "approval_invalid",
                "Approval request does not match this principal.",
            )
        if record.task_id != response.task_id or record.task_id != invocation.task_id:
            raise ApprovalValidationError(
                "approval_invalid",
                "Approval request does not match this task.",
            )
        if record.tool_name != invocation.tool_name:
            raise ApprovalValidationError(
                "approval_invalid",
                "Approval request does not match this tool.",
            )
        if record.arguments_sha256 != canonical_arguments_sha256(invocation.arguments):
            raise ApprovalValidationError(
                "approval_invalid",
                "Approval request does not match these arguments.",
            )
        if self._now_millis() >= record.expires_at_epoch_millis:
            raise ApprovalValidationError(
                "approval_expired",
                "Approval request has expired.",
            )

    def _prune_expired(self) -> None:
        now = self._now_millis()
        expired = [
            approval_id
            for approval_id, record in self._pending_approvals.items()
            if now >= record.expires_at_epoch_millis
        ]
        for approval_id in expired:
            del self._pending_approvals[approval_id]


def canonical_arguments_sha256(arguments: dict[str, Any]) -> str:
    encoded = json.dumps(
        arguments,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def approval_public_key_sha256(public_key_spki_der: bytes) -> str:
    validate_approval_public_key_spki_der(public_key_spki_der)
    return sha256(public_key_spki_der).hexdigest()


def validate_approval_public_key_spki_der(public_key_spki_der: bytes) -> None:
    if not (
        MIN_APPROVAL_PUBLIC_KEY_DER_BYTES
        <= len(public_key_spki_der)
        <= MAX_APPROVAL_PUBLIC_KEY_DER_BYTES
    ):
        raise ApprovalValidationError(
            "approval_public_key_invalid",
            "Approval public key is outside the supported size range.",
        )
    try:
        public_key = load_der_public_key(public_key_spki_der)
    except (ValueError, UnsupportedAlgorithm) as error:
        raise ApprovalValidationError(
            "approval_public_key_invalid",
            "Approval public key could not be decoded.",
        ) from error
    if not isinstance(public_key, ec.EllipticCurvePublicKey) or not isinstance(
        public_key.curve,
        ec.SECP256R1,
    ):
        raise ApprovalValidationError(
            "approval_public_key_invalid",
            "Approval public key must be an ECDSA P-256 key.",
        )


def approval_signing_payload(
    *,
    record: IssuedApprovalRecord,
    credential_id: UUID,
    approved: bool,
) -> bytes:
    payload = {
        "schemaVersion": APPROVAL_SIGNING_PAYLOAD_SCHEMA_VERSION,
        "approvalId": str(record.approval_id),
        "taskId": str(record.task_id),
        "credentialId": str(credential_id),
        "toolName": record.tool_name,
        "argumentsSha256": record.arguments_sha256,
        "issuedAtEpochMillis": record.issued_at_epoch_millis,
        "expiresAtEpochMillis": record.expires_at_epoch_millis,
        "approved": approved,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def verify_approval_response_proof(
    *,
    record: IssuedApprovalRecord,
    response: ApprovalResponsePayload,
    credential_id: UUID | None,
    approval_public_key_spki_der: bytes | None,
) -> None:
    if credential_id is None or approval_public_key_spki_der is None:
        raise ApprovalValidationError(
            "approval_proof_required",
            "A paired Android approval public key is required for this action.",
        )
    proof = response.proof
    if proof is None:
        raise ApprovalValidationError(
            "approval_proof_required",
            "A device-bound Android approval proof is required for this action.",
        )
    if (
        proof.schema_version != APPROVAL_PROOF_SCHEMA_VERSION
        or proof.algorithm != APPROVAL_PROOF_ALGORITHM
    ):
        raise ApprovalValidationError(
            "approval_proof_invalid",
            "Approval proof metadata is invalid.",
        )
    expected_key_hash = approval_public_key_sha256(approval_public_key_spki_der)
    if proof.public_key_sha256 != expected_key_hash:
        raise ApprovalValidationError(
            "approval_proof_invalid",
            "Approval proof key does not match this paired credential.",
        )
    try:
        signature = base64.b64decode(proof.signature_base64, validate=True)
    except ValueError as error:
        raise ApprovalValidationError(
            "approval_proof_invalid",
            "Approval proof signature is invalid.",
        ) from error
    if not 1 <= len(signature) <= MAX_APPROVAL_SIGNATURE_BYTES:
        raise ApprovalValidationError(
            "approval_proof_invalid",
            "Approval proof signature is outside the supported size range.",
        )
    public_key = load_der_public_key(approval_public_key_spki_der)
    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise ApprovalValidationError(
            "approval_public_key_invalid",
            "Approval public key must be an ECDSA key.",
        )
    payload = approval_signing_payload(
        record=record,
        credential_id=credential_id,
        approved=response.approved,
    )
    try:
        public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise ApprovalValidationError(
            "approval_proof_invalid",
            "Approval proof signature did not verify.",
        ) from error
