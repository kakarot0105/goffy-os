from uuid import UUID, uuid4

import pytest

from approval_key_helpers import approval_key_fixture, signed_approval_response
from goffy_hub.approval import (
    HUB_APPROVAL_TTL_MILLIS,
    ApprovalArtifactStore,
    ApprovalValidationError,
    canonical_arguments_sha256,
)
from goffy_protocol import ApprovalResponsePayload, ToolInvocationPayload

PAIRING_CREDENTIAL_ID = UUID("60606060-6060-4060-8060-606060606060")


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
    key = approval_key_fixture()
    response = signed_approval_response(
        record=record,
        credential_id=PAIRING_CREDENTIAL_ID,
        key=key,
    )

    consumed = store.consume(
        principal_key="token:phone-a",
        response=response,
        invocation=invocation,
        credential_id=PAIRING_CREDENTIAL_ID,
        approval_public_key_spki_der=key.public_key_spki_der,
    )

    assert consumed == record
    with pytest.raises(ApprovalValidationError, match="unknown or already consumed"):
        store.consume(
            principal_key="token:phone-a",
            response=response,
            invocation=invocation,
            credential_id=PAIRING_CREDENTIAL_ID,
            approval_public_key_spki_der=key.public_key_spki_der,
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
    key = approval_key_fixture()
    response = signed_approval_response(
        record=record,
        credential_id=PAIRING_CREDENTIAL_ID,
        key=key,
        task_id=response_task_id,
    )

    with pytest.raises(ApprovalValidationError) as error:
        store.consume(
            principal_key=principal_key,
            response=response,
            invocation=replayed,
            credential_id=PAIRING_CREDENTIAL_ID,
            approval_public_key_spki_der=key.public_key_spki_der,
        )

    assert error.value.code == expected_code


def test_consume_rejects_denied_and_expired_approvals() -> None:
    now = 1_000
    store = ApprovalArtifactStore(now_millis=lambda: now)
    invocation = invocation_payload()
    denied_record = store.issue(principal_key="token:phone-a", invocation=invocation)
    key = approval_key_fixture()

    with pytest.raises(ApprovalValidationError) as denied_error:
        store.consume(
            principal_key="token:phone-a",
            response=response_payload(
                approval_id=denied_record.approval_id,
                task_id=denied_record.task_id,
                approved=False,
            ),
            invocation=invocation,
            credential_id=PAIRING_CREDENTIAL_ID,
            approval_public_key_spki_der=key.public_key_spki_der,
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
    expired_response = signed_approval_response(
        record=expired_record,
        credential_id=PAIRING_CREDENTIAL_ID,
        key=key,
    )

    with pytest.raises(ApprovalValidationError) as expired_error:
        expiring_store.consume(
            principal_key="token:phone-a",
            response=expired_response,
            invocation=expiring_invocation,
            credential_id=PAIRING_CREDENTIAL_ID,
            approval_public_key_spki_der=key.public_key_spki_der,
        )

    assert expired_error.value.code == "approval_expired"


def test_consume_requires_device_bound_proof_for_approved_confirm_action() -> None:
    store = ApprovalArtifactStore(now_millis=lambda: 1_000)
    invocation = invocation_payload()
    record = store.issue(principal_key="token:phone-a", invocation=invocation)
    key = approval_key_fixture()
    response = response_payload(
        approval_id=record.approval_id,
        task_id=record.task_id,
    )

    with pytest.raises(ApprovalValidationError) as error:
        store.consume(
            principal_key="token:phone-a",
            response=response,
            invocation=invocation,
            credential_id=PAIRING_CREDENTIAL_ID,
            approval_public_key_spki_der=key.public_key_spki_der,
        )

    assert error.value.code == "approval_proof_required"


def test_consume_rejects_approval_signed_by_another_device_key() -> None:
    store = ApprovalArtifactStore(now_millis=lambda: 1_000)
    invocation = invocation_payload()
    record = store.issue(principal_key="token:phone-a", invocation=invocation)
    paired_key = approval_key_fixture()
    attacker_key = approval_key_fixture()
    response = signed_approval_response(
        record=record,
        credential_id=PAIRING_CREDENTIAL_ID,
        key=attacker_key,
    )

    with pytest.raises(ApprovalValidationError) as error:
        store.consume(
            principal_key="token:phone-a",
            response=response,
            invocation=invocation,
            credential_id=PAIRING_CREDENTIAL_ID,
            approval_public_key_spki_der=paired_key.public_key_spki_der,
        )

    assert error.value.code == "approval_proof_invalid"

    recovered_response = signed_approval_response(
        record=record,
        credential_id=PAIRING_CREDENTIAL_ID,
        key=paired_key,
    )
    assert (
        store.consume(
            principal_key="token:phone-a",
            response=recovered_response,
            invocation=invocation,
            credential_id=PAIRING_CREDENTIAL_ID,
            approval_public_key_spki_der=paired_key.public_key_spki_der,
        )
        == record
    )
