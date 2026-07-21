from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from goffy_protocol import ApprovalRequestPayload, ApprovalResponsePayload, ToolInvocationPayload

HUB_APPROVAL_TTL_MILLIS = 60_000
MAX_PENDING_APPROVALS = 1_024


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
    ) -> IssuedApprovalRecord:
        record = self._pending_approvals.pop(response.approval_id, None)
        if record is None:
            raise ApprovalValidationError(
                "approval_invalid",
                "Approval request is unknown or already consumed.",
            )
        if not response.approved:
            raise ApprovalValidationError(
                "approval_denied",
                "Approval was denied; no tool was invoked.",
            )
        self._validate(record, principal_key, response, invocation)
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
