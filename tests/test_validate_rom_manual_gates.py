from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_rom_manual_gates import (
    JSON_SCHEMA_VERSION,
    ROLLBACK_REQUIRED_HEADINGS,
    ManualGateStatus,
    load_manual_gates,
    validate_manual_gates,
)


def complete_payload(rollback_doc: str) -> dict[str, object]:
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "backup_confirmed": True,
        "oem_unlocking_enabled": True,
        "motorola_unlock_eligibility": "eligible",
        "destructive_approval": "not_requested",
        "stock_restore": {
            "source_url": "https://en-us.support.motorola.com/app/softwarefix",
            "archive_name": "kansas-stock.zip",
            "sha256": "A" * 64,
            "rollback_doc": rollback_doc,
        },
    }


def complete_rollback_doc(archive_name: str = "kansas-stock.zip", sha256: str = "A" * 64) -> str:
    return "\n".join(
        (
            "# Kansas Stock Rollback",
            "",
            "## Device Baseline",
            "- Model: moto g - 2025",
            "- Codename: kansas",
            "- Product: kansas_g_sys",
            "- Android release/build: recorded from ROM probe",
            "- Carrier/channel: recorded by user without private identifiers",
            "",
            "## Stock Restore Source",
            "- Source: https://en-us.support.motorola.com/app/softwarefix",
            f"- Firmware archive: {archive_name}",
            "",
            "## SHA-256 Evidence",
            f"- SHA-256: {sha256}",
            "",
            "## Rollback Procedure",
            "- Restore with Motorola Software Fix before any further experiment.",
            "",
            "## Data Wipe Expectations",
            "- Unlocking or restore may wipe local user data.",
            "",
            "## Approval Record",
            "- Destructive approval is not granted by this document.",
            "",
        )
    )


def test_complete_manual_gate_evidence_is_ready_for_human_review(tmp_path: Path) -> None:
    rollback_doc = tmp_path / "docs" / "setup" / "kansas-rollback.md"
    rollback_doc.parent.mkdir(parents=True)
    rollback_doc.write_text(complete_rollback_doc(), encoding="utf-8")
    payload = complete_payload("docs/setup/kansas-rollback.md")

    report = validate_manual_gates(payload, root=tmp_path)

    assert report.ok
    assert report.status is ManualGateStatus.READY_FOR_HUMAN_REVIEW
    assert report.accepted_evidence["stock_restore.sha256"] == "a" * 64


def test_rollback_doc_must_include_required_sections_and_evidence(tmp_path: Path) -> None:
    rollback_doc = tmp_path / "docs" / "setup" / "kansas-rollback.md"
    rollback_doc.parent.mkdir(parents=True)
    rollback_doc.write_text("# Rollback\n", encoding="utf-8")
    payload = complete_payload("docs/setup/kansas-rollback.md")

    report = validate_manual_gates(payload, root=tmp_path)

    assert not report.ok
    for heading in ROLLBACK_REQUIRED_HEADINGS:
        assert f"stock_restore.rollback_doc missing heading {heading}" in report.blockers
    assert "stock_restore.rollback_doc must include the exact archive name" in report.blockers
    assert "stock_restore.rollback_doc must include the exact SHA-256" in report.blockers


def test_missing_manual_gate_evidence_blocks(tmp_path: Path) -> None:
    report = validate_manual_gates({"schema_version": JSON_SCHEMA_VERSION}, root=tmp_path)

    assert not report.ok
    assert report.status is ManualGateStatus.BLOCKED_MANUAL_GATES
    assert "backup_confirmed must be true" in report.blockers
    assert "oem_unlocking_enabled must be true" in report.blockers


def test_bad_stock_restore_evidence_blocks(tmp_path: Path) -> None:
    payload = complete_payload("/rollback.txt")
    payload["stock_restore"] = {
        "source_url": "http://example.invalid/firmware.zip",
        "archive_name": "../firmware.zip",
        "sha256": "not-a-sha",
        "rollback_doc": "/rollback.txt",
    }

    report = validate_manual_gates(payload, root=tmp_path)

    assert not report.ok
    assert any("source_url must be an https URL" in blocker for blocker in report.blockers)
    assert any("archive_name must be a filename" in blocker for blocker in report.blockers)
    assert any("sha256 must be 64 hex" in blocker for blocker in report.blockers)
    assert any("rollback_doc must be a relative path" in blocker for blocker in report.blockers)


def test_load_manual_gates_rejects_sensitive_keys(tmp_path: Path) -> None:
    path = tmp_path / "manual-gates.json"
    payload = complete_payload("docs/setup/kansas-rollback.md")
    payload["device"] = {"device_serial": "ZY32LBQLMQ"}
    path.write_text(json.dumps(payload), encoding="utf-8")

    try:
        load_manual_gates(path)
    except ValueError as exc:
        assert "sensitive key" in str(exc)
    else:
        raise AssertionError("expected ValueError")
