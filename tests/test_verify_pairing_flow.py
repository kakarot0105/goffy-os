from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from scripts.create_pairing_qr import PAIRING_QR_ARTIFACT_MARKER
from scripts.verify_pairing_flow import result_json, verify_pairing_flow


def test_verify_pairing_flow_redeems_once_and_rejects_replay() -> None:
    result = verify_pairing_flow()

    assert result.credential_count == 1
    assert result.bundle_payload_bytes > 100
    assert result.replay_status in {400, 429}
    assert result.rotation_status == 200
    assert result.old_token_status == 401
    assert result.new_token_status == 200


def test_verify_pairing_flow_can_write_private_qr_artifact(tmp_path: Path) -> None:
    output = tmp_path / "pairing.svg"

    result = verify_pairing_flow(output=output)

    assert result.output == output
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    svg = output.read_text(encoding="utf-8")
    assert PAIRING_QR_ARTIFACT_MARKER in svg
    assert "<svg" in svg


def test_result_json_reports_success_without_secrets() -> None:
    result = verify_pairing_flow()

    decoded = json.loads(result_json(result))

    assert decoded["verified"] is True
    assert decoded["credentialId"] == result.credential_id
    assert decoded["rotationStatus"] == 200
    assert decoded["oldTokenStatus"] == 401
    assert decoded["newTokenStatus"] == 200
    assert "accessToken" not in decoded
    assert "pairingToken" not in decoded


def test_verify_pairing_flow_refuses_to_overwrite_qr_artifact(tmp_path: Path) -> None:
    output = tmp_path / "pairing.svg"
    output.write_text("existing", encoding="utf-8")

    with pytest.raises(RuntimeError):
        verify_pairing_flow(output=output)
