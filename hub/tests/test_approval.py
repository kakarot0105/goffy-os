from uuid import UUID, uuid4

import pytest

from goffy_hub.approval import (
    HUB_APPROVAL_TTL_MILLIS,
    ApprovalArtifactStore,
    ApprovalValidationError,
    canonical_arguments_sha256,
)
from goffy_protocol import ApprovalResponsePayload, ToolInvocationPayload


def invocation_payload(
    *,
    task_id: UUID | None = None,
    arguments: dict[str, object] | None = None,
) -> ToolInvocationPayload:
    return ToolInvocationPayload.model_validate(
        {
            "toolName": "mac.apps.open",
            "arguments": arguments or {"displayName": "Safari"},
            "taskId": str(task_id or uuid4()),
        }
    )


def response_payload(
    *,
    approval_id: UUID,
    task_id: UUID,
    approved: bool = True,
) -> ApprovalResponsePayload:
    return ApprovalResponsePayload.model_validate(
        {
            "schemaVersion": "goffy.approval.v1",
            "approvalId": str(approval_id),
            "taskId": str(task_id),
            "approved": approved,
        }
    )


def test_issue_binds_approval_to_principal_task_tool_arguments_and_expiry() -> None:
    store = ApprovalArtifactStore(now_millis=lambda: 1_000)
    invocation = invocation_payload()

    record = store.issue(principal_key="token:phone-a", invocation=invocation)
    payload = record.to_payload()

    assert payload.approval_id == record.approval_id
    assert payload.task_id == invocation.task_id
    assert payload.tool_name == "mac.apps.open"
    assert payload.arguments_sha256 == canonical_arguments_sha256({"displayName": "Safari"})
    assert payload.issued_at_epoch_millis == 1_000
    assert payload.expires_at_epoch_millis == 1_000 + HUB_APPROVAL_TTL_MILLIS


def test_consume_accepts_matching_approval_once() -> None:
    store = ApprovalArtifactStore(now_millis=lambda: 1_000)
    invocation = invocation_payload()
    record = store.issue(principal_key="token:phone-a", invocation=invocation)
    response = response_payload(
        approval_id=record.approval_id,
        task_id=record.task_id,
    )

    consumed = store.consume(
        principal_key="token:phone-a",
        response=response,
        invocation=invocation,
    )

    assert consumed == record
    with pytest.raises(ApprovalValidationError, match="unknown or already consumed"):
        store.consume(
            principal_key="token:phone-a",
            response=response,
            invocation=invocation,
        )


@pytest.mark.parametrize(
    ("principal_key", "response_task_id", "arguments", "expected_code"),
    [
        ("token:phone-b", None, {"displayName": "Safari"}, "approval_invalid"),
        ("token:phone-a", uuid4(), {"displayName": "Safari"}, "approval_invalid"),
        ("token:phone-a", None, {"displayName": "Terminal"}, "approval_invalid"),
    ],
)
def test_consume_rejects_mismatched_approval_data(
    principal_key: str,
    response_task_id: UUID | None,
    arguments: dict[str, object],
    expected_code: str,
) -> None:
    store = ApprovalArtifactStore(now_millis=lambda: 1_000)
    original = invocation_payload()
    replayed = invocation_payload(task_id=original.task_id, arguments=arguments)
    record = store.issue(principal_key="token:phone-a", invocation=original)
    response = response_payload(
        approval_id=record.approval_id,
        task_id=response_task_id or record.task_id,
    )

    with pytest.raises(ApprovalValidationError) as error:
        store.consume(
            principal_key=principal_key,
            response=response,
            invocation=replayed,
        )

    assert error.value.code == expected_code


def test_consume_rejects_denied_and_expired_approvals() -> None:
    now = 1_000
    store = ApprovalArtifactStore(now_millis=lambda: now)
    invocation = invocation_payload()
    denied_record = store.issue(principal_key="token:phone-a", invocation=invocation)

    with pytest.raises(ApprovalValidationError) as denied_error:
        store.consume(
            principal_key="token:phone-a",
            response=response_payload(
                approval_id=denied_record.approval_id,
                task_id=denied_record.task_id,
                approved=False,
            ),
            invocation=invocation,
        )

    assert denied_error.value.code == "approval_denied"

    now = 1_000
    expiring_store = ApprovalArtifactStore(now_millis=lambda: now)
    expiring_invocation = invocation_payload()
    expired_record = expiring_store.issue(
        principal_key="token:phone-a",
        invocation=expiring_invocation,
    )
    now = expired_record.expires_at_epoch_millis

    with pytest.raises(ApprovalValidationError) as expired_error:
        expiring_store.consume(
            principal_key="token:phone-a",
            response=response_payload(
                approval_id=expired_record.approval_id,
                task_id=expired_record.task_id,
            ),
            invocation=expiring_invocation,
        )

    assert expired_error.value.code == "approval_expired"
