from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.create_rom0_operator_checklist import (
    ChecklistStatus,
    StepStatus,
    build_operator_checklist,
    load_refresh_report,
    main,
    render_markdown,
)


def test_operator_checklist_blocks_stock_restore_before_unlock_or_dsu() -> None:
    report = refresh_report(
        stock=False,
        unlock=True,
        gsi=True,
        fastboot=True,
        bootloader_status="MANUAL_BOOTLOADER_VISIBLE",
        blocked_by=("exact stock restore evidence is missing",),
    )

    checklist = build_operator_checklist(report)
    steps = {step.step_id: step for step in checklist.steps}
    markdown = render_markdown(checklist).lower()

    assert not checklist.ok
    assert checklist.status is ChecklistStatus.BLOCKED_EVIDENCE
    assert (
        "stock restore evidence must be recorded before any unlock, DSU, flash, or boot decision"
        in checklist.blocked_by
    )
    assert steps["record_stock_restore"].status is StepStatus.READY
    assert steps["record_unlock_eligibility"].blockers == (
        "stock restore evidence must be recorded before unlock decisions advance",
    )
    assert steps["record_gsi_candidate"].blockers == (
        "stock restore evidence must be recorded before DSU/GSI decisions advance",
    )
    assert "fastboot flash" not in markdown
    assert "adb reboot bootloader" not in markdown


def test_operator_checklist_keeps_host_only_fastboot_blocked() -> None:
    report = refresh_report(
        stock=True,
        unlock=True,
        gsi=True,
        fastboot=True,
        bootloader_status="READY_FOR_MANUAL_BOOTLOADER_CHECK",
        blocked_by=("manual bootloader-mode fastboot visibility evidence is missing",),
    )

    checklist = build_operator_checklist(report)
    steps = {step.step_id: step for step in checklist.steps}

    assert not checklist.ok
    assert checklist.status is ChecklistStatus.BLOCKED_EVIDENCE
    assert steps["record_manual_bootloader_visibility"].status is StepStatus.READY
    assert steps["record_manual_bootloader_visibility"].safe_commands == (
        ".venv/bin/python scripts/create_rom_fastboot_evidence.py --manual-bootloader-check",
    )
    assert steps["rom0_readiness_review"].status is StepStatus.BLOCKED


def test_operator_checklist_ready_for_readiness_review_without_destructive_authority() -> None:
    report = refresh_report(
        stock=True,
        unlock=True,
        gsi=True,
        dsu=True,
        fastboot=True,
        bootloader_status="MANUAL_BOOTLOADER_VISIBLE",
        rom_ready=True,
        packet_status="PacketStatus.READY_FOR_ROM0_READINESS_REVIEW",
    )

    checklist = build_operator_checklist(report)
    steps = {step.step_id: step for step in checklist.steps}
    markdown = render_markdown(checklist).lower()

    assert checklist.ok
    assert checklist.status is ChecklistStatus.READY_FOR_ROM0_READINESS_REVIEW
    assert checklist.destructive_actions == "withheld"
    assert steps["record_dsu_preflight"].status is StepStatus.DONE
    assert steps["rom0_readiness_review"].status is StepStatus.READY
    assert steps["destructive_unlock_or_boot_decision"].status is StepStatus.BLOCKED
    assert "fastboot flashing unlock" not in markdown
    assert "fastboot boot" not in markdown


def test_operator_checklist_keeps_semantically_rejected_unlock_required() -> None:
    report = refresh_report(
        stock=True,
        unlock=True,
        gsi=True,
        fastboot=True,
        bootloader_status="MANUAL_BOOTLOADER_VISIBLE",
        blocked_by=(
            "manual OEM or Motorola unlock eligibility evidence is missing or not eligible",
        ),
    )

    checklist = build_operator_checklist(report)
    steps = {step.step_id: step for step in checklist.steps}

    assert not checklist.ok
    assert checklist.status is ChecklistStatus.BLOCKED_EVIDENCE
    assert steps["record_unlock_eligibility"].status is StepStatus.READY
    assert steps["create_manual_gates"].status is StepStatus.BLOCKED


def test_operator_checklist_accepts_refresh_report_v4() -> None:
    report = refresh_report()
    report["schema_version"] = "goffy.rom0-refresh-report.v4"

    checklist = build_operator_checklist(report)

    assert checklist.status is ChecklistStatus.BLOCKED_EVIDENCE


def test_operator_checklist_rejects_unsupported_refresh_schema() -> None:
    report = refresh_report()
    report["schema_version"] = "goffy.rom0-refresh-report.v1"

    with pytest.raises(ValueError, match="unsupported ROM-0 refresh schema"):
        build_operator_checklist(report)


def test_load_refresh_report_rejects_path_outside_validation_dir(tmp_path: Path) -> None:
    outside = tmp_path / "rom-0-refresh-report.json"
    outside.write_text(json.dumps(refresh_report()), encoding="utf-8")

    with pytest.raises(ValueError, match="under .goffy-validation"):
        load_refresh_report(outside, root=tmp_path)


def test_operator_checklist_cli_writes_outputs_only_under_validation_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validation = tmp_path / ".goffy-validation"
    validation.mkdir()
    refresh_path = validation / "rom-0-refresh-report.json"
    json_output = validation / "rom-0-operator-checklist.json"
    markdown_output = validation / "rom-0-operator-checklist.md"
    blocked_output = tmp_path / "rom-0-operator-checklist.json"
    refresh_path.write_text(
        json.dumps(
            refresh_report(
                stock=True,
                unlock=True,
                gsi=True,
                dsu=True,
                fastboot=True,
                bootloader_status="MANUAL_BOOTLOADER_VISIBLE",
                rom_ready=True,
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("scripts.create_rom0_operator_checklist.ROOT", tmp_path)

    assert (
        main(
            [
                "--refresh-report",
                str(refresh_path),
                "--output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
            ]
        )
        == 0
    )
    payload = json_output.read_text(encoding="utf-8")
    assert json.loads(payload)["ok"] is True
    assert str(tmp_path) not in payload
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# GOFFY ROM-0 Operator Checklist"
    )
    assert (
        main(
            [
                "--refresh-report",
                str(refresh_path),
                "--output",
                str(blocked_output),
                "--markdown-output",
                str(markdown_output),
            ]
        )
        == 1
    )
    assert not blocked_output.exists()


def refresh_report(
    *,
    stock: bool = False,
    unlock: bool = False,
    gsi: bool = False,
    dsu: bool = False,
    fastboot: bool = False,
    bootloader_status: str = "HOST_EVIDENCE_MISSING",
    rom_ready: bool = False,
    packet_status: str = "PacketStatus.BLOCKED_MANUAL_EVIDENCE",
    blocked_by: tuple[str, ...] = (),
) -> dict[str, object]:
    evidence_inputs = [
        evidence_input("unlock_eligibility", unlock),
        evidence_input("stock_restore", stock),
        evidence_input("gsi_candidate", gsi),
        evidence_input("dsu_preflight", dsu),
        evidence_input("fastboot_evidence", fastboot),
        evidence_input("bootloader_visibility_guide", True),
    ]
    return {
        "schema_version": "goffy.rom0-refresh-report.v2",
        "generated_at": "2026-07-22T00:00:00+00:00",
        "ok": rom_ready,
        "status": "READY_FOR_ROM0_READINESS_REVIEW" if rom_ready else "BLOCKED",
        "refresh_succeeded": True,
        "rom_ready": rom_ready,
        "destructive_actions": "withheld",
        "probe_json": ".goffy-validation/rom-feasibility-current.json",
        "packet_markdown": ".goffy-validation/rom-0-manual-action-packet.md",
        "packet_json": ".goffy-validation/rom-0-manual-action-packet.json",
        "bootloader_guide_markdown": ".goffy-validation/rom-bootloader-visibility-guide.md",
        "bootloader_guide_json": ".goffy-validation/rom-bootloader-visibility-guide.json",
        "refresh_report_json": ".goffy-validation/rom-0-refresh-report.json",
        "packet_status": packet_status,
        "bootloader_visibility_status": bootloader_status,
        "blocked_by": blocked_by,
        "evidence_inputs": evidence_inputs,
        "errors": [],
    }


def evidence_input(name: str, loaded: bool) -> dict[str, str]:
    return {
        "name": name,
        "path": f".goffy-validation/{name}.json",
        "status": "LOADED" if loaded else "MISSING",
        "detail": "validated and consumed" if loaded else "not present",
    }
