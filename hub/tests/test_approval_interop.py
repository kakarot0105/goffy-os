from __future__ import annotations

import base64
from uuid import UUID

from goffy_hub.approval import (
    IssuedApprovalRecord,
    approval_public_key_sha256,
    approval_signing_payload,
    verify_approval_response_proof,
)
from goffy_protocol import ApprovalResponsePayload

JVM_PUBLIC_KEY_SPKI_DER_BASE64 = (
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEPAwvDfIIsnpWwu0cyWBn87UsLWa49lWAXrAU4"
    "tyPtJoq59Z7RxEfMhKwtHEvQZMxZJvG/7QA+42ml0dlpp6dHw=="
)
JVM_PUBLIC_KEY_SHA256 = "266901bd170b0ebdd37317e8b3fca8cb47e89774df9e3f7dc7f5a562d03b334e"
JVM_SIGNATURE_BASE64 = (
    "MEQCIA26s/1ZpNBGU+nLpfcWd9xFJ7h6Ync7yvJcQiWGHX+wAiA/a2x3OFLa/lbDS0dMW+UB"
    "0iEUkWLlPVlyEOsICXD43Q=="
)
EXPECTED_CANONICAL_PAYLOAD = (
    '{"approvalId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","approved":true,'
    '"argumentsSha256":"48bcd955f3fdbcaddfc3844e3a9bdc8a9a3791bab296bec333e8e7231244793e",'
    '"credentialId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",'
    '"expiresAtEpochMillis":1784300461000,"issuedAtEpochMillis":1784300401000,'
    '"schemaVersion":"goffy.approval.signed-payload.v1",'
    '"taskId":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","toolName":"mac.apps.open"}'
)


def test_python_hub_accepts_jvm_ecdsa_approval_proof_fixture() -> None:
    # Generated once with JDK 17 Signature("SHA256withECDSA") over
    # EXPECTED_CANONICAL_PAYLOAD. Only the public key and signature are stored.
    public_key_spki_der = base64.b64decode(JVM_PUBLIC_KEY_SPKI_DER_BASE64)
    record = IssuedApprovalRecord(
        approval_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        principal_key="paired:bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        task_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        tool_name="mac.apps.open",
        arguments_sha256="48bcd955f3fdbcaddfc3844e3a9bdc8a9a3791bab296bec333e8e7231244793e",
        issued_at_epoch_millis=1_784_300_401_000,
        expires_at_epoch_millis=1_784_300_461_000,
    )
    response = ApprovalResponsePayload.model_validate(
        {
            "schemaVersion": "goffy.approval.v1",
            "approvalId": str(record.approval_id),
            "taskId": str(record.task_id),
            "approved": True,
            "proof": {
                "schemaVersion": "goffy.approval.proof.v1",
                "algorithm": "ECDSA_P256_SHA256",
                "publicKeySha256": JVM_PUBLIC_KEY_SHA256,
                "signatureBase64": JVM_SIGNATURE_BASE64,
            },
        }
    )

    assert approval_public_key_sha256(public_key_spki_der) == JVM_PUBLIC_KEY_SHA256
    assert (
        approval_signing_payload(
            record=record,
            credential_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            approved=True,
        ).decode("utf-8")
        == EXPECTED_CANONICAL_PAYLOAD
    )
    verify_approval_response_proof(
        record=record,
        response=response,
        credential_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        approval_public_key_spki_der=public_key_spki_der,
    )
