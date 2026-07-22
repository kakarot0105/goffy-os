from __future__ import annotations

import base64
from dataclasses import dataclass
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from goffy_hub.approval import (
    IssuedApprovalRecord,
    approval_public_key_sha256,
    approval_signing_payload,
)
from goffy_protocol import ApprovalResponsePayload


@dataclass(frozen=True, slots=True)
class ApprovalKeyFixture:
    private_key: ec.EllipticCurvePrivateKey
    public_key_spki_der: bytes

    @property
    def public_key_sha256(self) -> str:
        return approval_public_key_sha256(self.public_key_spki_der)

    @property
    def pairing_request(self) -> dict[str, str]:
        return {
            "schemaVersion": "goffy.approval.public-key.v1",
            "algorithm": "ECDSA_P256_SHA256",
            "spkiDerBase64": base64.b64encode(self.public_key_spki_der).decode("ascii"),
            "spkiSha256": self.public_key_sha256,
        }


def approval_key_fixture() -> ApprovalKeyFixture:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_spki_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return ApprovalKeyFixture(
        private_key=private_key,
        public_key_spki_der=public_key_spki_der,
    )


def signed_approval_response(
    *,
    record: IssuedApprovalRecord,
    credential_id: UUID,
    key: ApprovalKeyFixture,
    approved: bool = True,
    approval_id: UUID | None = None,
    task_id: UUID | None = None,
) -> ApprovalResponsePayload:
    payload: dict[str, object] = {
        "schemaVersion": "goffy.approval.v1",
        "approvalId": str(approval_id or record.approval_id),
        "taskId": str(task_id or record.task_id),
        "approved": approved,
    }
    if approved:
        signature = key.private_key.sign(
            approval_signing_payload(
                record=record,
                credential_id=credential_id,
                approved=approved,
            ),
            ec.ECDSA(hashes.SHA256()),
        )
        payload["proof"] = {
            "schemaVersion": "goffy.approval.proof.v1",
            "algorithm": "ECDSA_P256_SHA256",
            "publicKeySha256": key.public_key_sha256,
            "signatureBase64": base64.b64encode(signature).decode("ascii"),
        }
    return ApprovalResponsePayload.model_validate(payload)
