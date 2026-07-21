from __future__ import annotations

import json
from pathlib import Path

from scripts.create_rom_unlock_eligibility_evidence import (
    JSON_SCHEMA_VERSION,
    MOTOROLA_BOOTLOADER_SUPPORT_URL,
    create_unlock_eligibility_evidence,
    load_unlock_eligibility_evidence,
    main,
    render_json,
)


def test_unlock_eligibility_evidence_records_redacted_manual_result() -> None:
    evidence = create_unlock_eligibility_evidence(
        oem_unlocking_visible=True,
        oem_unlocking_enabled=True,
        motorola_unlock_eligibility="eligible",
        operator_note_code="checked_no_identifiers_stored",
    )
    payload = json.loads(render_json(evidence))

    assert payload["schema_version"] == JSON_SCHEMA_VERSION
    assert payload["unlock_eligibility"] == {
        "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
        "oem_unlocking_visible": True,
        "oem_unlocking_enabled": True,
        "motorola_unlock_eligibility": "eligible",
        "operator_note_code": "checked_no_identifiers_stored",
    }
    assert "generated_at" in payload


def test_unlock_eligibility_rejects_impossible_oem_toggle_state() -> None:
    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=False,
            oem_unlocking_enabled=True,
            motorola_unlock_eligibility="unknown",
        )
    except ValueError as exc:
        assert "cannot be enabled when the toggle is not visible" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unlock_eligibility_rejects_unofficial_source_and_invalid_status() -> None:
    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=False,
            motorola_unlock_eligibility="maybe",
            source_url="https://example.invalid/unlock",
        )
    except ValueError as exc:
        assert "motorola eligibility must be one of" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=False,
            motorola_unlock_eligibility="not_eligible",
            source_url="https://example.invalid/unlock",
        )
    except ValueError as exc:
        assert "source URL must be the Motorola bootloader support URL" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unlock_eligibility_rejects_freeform_note_values() -> None:
    try:
        create_unlock_eligibility_evidence(
            oem_unlocking_visible=True,
            oem_unlocking_enabled=False,
            motorola_unlock_eligibility="unknown",
            operator_note_code="ZY32LBQLMQ",
        )
    except ValueError as exc:
        assert "operator note code must be one of" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_rejects_sensitive_keys(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                    "device_serial": "ZY32LBQLMQ",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "sensitive key" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_rejects_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                    "screenshot_path": "redacted-oem.png",
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "unsupported keys" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_rejects_top_level_extra_keys(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                },
                "screenshot_path": "redacted-oem.png",
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "unsupported top-level keys" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_unlock_eligibility_evidence_requires_string_fields(tmp_path: Path) -> None:
    path = tmp_path / "unlock.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "generated_at": "2026-07-21T00:00:00+00:00",
                "unlock_eligibility": {
                    "source_url": MOTOROLA_BOOTLOADER_SUPPORT_URL,
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": 123,
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        load_unlock_eligibility_evidence(path)
    except ValueError as exc:
        assert "operator_note_code must be a string" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_emits_redacted_stdout(capsys) -> None:
    exit_code = main(
        [
            "--oem-unlocking-visible",
            "yes",
            "--oem-unlocking-enabled",
            "no",
            "--motorola-eligibility",
            "not_eligible",
            "--stdout",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["unlock_eligibility"]["motorola_unlock_eligibility"] == "not_eligible"
