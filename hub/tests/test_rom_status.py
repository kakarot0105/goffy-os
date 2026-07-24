from __future__ import annotations

import json
from pathlib import Path

import pytest

from goffy_hub.registry import ToolRegistry
from goffy_hub.tools.rom_status import (
    CHECKLIST_TOOL_NAME,
    LATEST_REFRESH_SCHEMA,
    TOOL_NAME,
    build_goffy_rom_checklist_tool,
    build_goffy_rom_status_tool,
    goffy_rom_checklist_snapshot,
    goffy_rom_status_snapshot,
)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def refresh_payload(
    *,
    schema_version: str = LATEST_REFRESH_SCHEMA,
    rom_ready: bool = False,
    destructive_actions: str = "withheld",
    status: str | None = None,
    refresh_succeeded: bool = True,
    packet_status: str | None = None,
    bootloader_visibility_status: str | None = None,
    blocked_by: list[str] | None = None,
    evidence_inputs: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    refresh_status = status or ("BLOCKED" if not rom_ready else "READY_FOR_ROM0_READINESS_REVIEW")
    packet_status_value = packet_status or (
        "BLOCKED_MANUAL_EVIDENCE" if not rom_ready else "READY_FOR_ROM0_READINESS_REVIEW"
    )
    bootloader_status = bootloader_visibility_status or (
        "READY_FOR_MANUAL_BOOTLOADER_CHECK" if not rom_ready else "MANUAL_BOOTLOADER_VISIBLE"
    )
    default_evidence_status = "LOADED" if rom_ready else "MISSING"
    return {
        "schema_version": schema_version,
        "generated_at": "2026-07-22T15:00:00+00:00",
        "status": refresh_status,
        "refresh_succeeded": refresh_succeeded,
        "rom_ready": rom_ready,
        "destructive_actions": destructive_actions,
        "packet_status": packet_status_value,
        "bootloader_visibility_status": bootloader_status,
        "operator_checklist_status": "BLOCKED_EVIDENCE"
        if not rom_ready
        else "READY_FOR_ROM0_READINESS_REVIEW",
        "blocked_by": blocked_by
        if blocked_by is not None
        else ["exact stock restore evidence is missing"],
        "evidence_inputs": evidence_inputs
        if evidence_inputs is not None
        else [
            evidence_input("unlock_eligibility", default_evidence_status),
            evidence_input("stock_restore", default_evidence_status),
            evidence_input("gsi_candidate", default_evidence_status),
            evidence_input("dsu_preflight", default_evidence_status),
            evidence_input("fastboot_evidence", default_evidence_status),
        ],
        "errors": [],
    }


def evidence_input(name: str, status: str) -> dict[str, str]:
    return {
        "name": name,
        "path": f".goffy-validation/{name}.json",
        "status": status,
        "detail": "test fixture",
    }


def operator_payload(
    *,
    status: str = "BLOCKED_EVIDENCE",
    steps: list[dict[str, object]] | None = None,
    destructive_actions: str = "withheld",
) -> dict[str, object]:
    ready = status == "READY_FOR_ROM0_READINESS_REVIEW"
    return {
        "schema_version": "goffy.rom0-operator-checklist.v1",
        "generated_at": "2026-07-22T15:00:01+00:00",
        "ok": ready,
        "status": status,
        "destructive_actions": destructive_actions,
        "source_refresh_report": ".goffy-validation/rom-0-refresh-report.json",
        "blocked_by": [] if ready else ["exact stock restore evidence is missing"],
        "steps": steps if steps is not None else [],
        "reuse_decision": "Reuse GOFFY typed evidence validators.",
    }


def checklist_step(
    step_id: str,
    *,
    title: str,
    status: str,
    kind: str = "HUMAN_ONLY",
    summary: str = "Collect bounded ROM-0 evidence.",
    blockers: list[str] | None = None,
) -> dict[str, object]:
    return {
        "step_id": step_id,
        "title": title,
        "kind": kind,
        "status": status,
        "summary": summary,
        "must_follow_after": [],
        "safe_commands": [
            ".venv/bin/python scripts/create_rom_stock_restore_evidence.py --archive example.zip"
        ],
        "evidence_paths": [".goffy-validation/example.json"],
        "blockers": blockers if blockers is not None else [],
    }


def test_rom_status_reports_missing_refresh_artifact(tmp_path: Path) -> None:
    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "missing"
    assert result["romReady"] is False
    assert result["checkedRefreshReport"] is False
    assert result["destructiveActions"] == "withheld"
    assert "refresh evidence is missing" in result["summary"]


def test_rom_status_summarizes_current_refresh_and_operator_artifacts(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(validation_dir / "rom-0-refresh-report.json", refresh_payload())
    write_json(validation_dir / "rom-0-operator-checklist.json", operator_payload())

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "available"
    assert result["milestone"] == "ROM-0"
    assert result["refreshSchemaVersion"] == LATEST_REFRESH_SCHEMA
    assert result["operatorChecklistStatus"] == "BLOCKED_EVIDENCE"
    assert result["installDecision"] == "BLOCKED"
    assert result["unlockGateStatus"] == "MISSING"
    assert result["stockRestoreGateStatus"] == "MISSING"
    assert result["gsiCandidateGateStatus"] == "MISSING"
    assert result["dsuPreflightGateStatus"] == "MISSING"
    assert result["fastbootGateStatus"] == "MISSING"
    assert result["destructiveApprovalStatus"] == "WITHHELD"
    assert result["blockerCount"] == 2
    assert result["blockers"] == [
        "exact stock restore evidence is missing",
        "ROM-0 operator checklist status is BLOCKED_EVIDENCE",
    ]
    assert result["checkedOperatorChecklist"] is True
    assert result["staleReport"] is False


def test_rom_status_marks_legacy_refresh_as_stale(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(schema_version="goffy.rom0-refresh-report.v1"),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "available"
    assert result["staleReport"] is True
    assert result["checkedOperatorChecklist"] is False
    assert "refresh report is stale" in result["summary"]
    assert any("stale" in blocker for blocker in result["blockers"])


def test_rom_status_never_marks_stale_ready_report_as_ready(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(
            schema_version="goffy.rom0-refresh-report.v1",
            rom_ready=True,
            blocked_by=[],
        ),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "available"
    assert result["romReady"] is False
    assert result["staleReport"] is True
    assert result["blockerCount"] == 2


def test_rom_status_requires_operator_checklist_for_ready_state(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(rom_ready=True, blocked_by=[]),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "available"
    assert result["romReady"] is False
    assert result["checkedOperatorChecklist"] is False
    assert result["operatorChecklistStatus"] == "MISSING"
    assert "ROM-0 operator checklist evidence is missing" in result["blockers"]


def test_rom_status_merges_blocked_operator_checklist_into_not_ready_state(
    tmp_path: Path,
) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(rom_ready=True, blocked_by=[]),
    )
    write_json(validation_dir / "rom-0-operator-checklist.json", operator_payload())

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "available"
    assert result["romReady"] is False
    assert result["checkedOperatorChecklist"] is True
    assert result["operatorChecklistStatus"] == "BLOCKED_EVIDENCE"
    assert "exact stock restore evidence is missing" in result["blockers"]
    assert "ROM-0 operator checklist status is BLOCKED_EVIDENCE" in result["blockers"]


def test_rom_status_allows_ready_only_when_refresh_and_operator_are_ready(
    tmp_path: Path,
) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(rom_ready=True, blocked_by=[]),
    )
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(status="READY_FOR_ROM0_READINESS_REVIEW"),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "available"
    assert result["romReady"] is True
    assert result["installDecision"] == "READY_FOR_MANUAL_REVIEW"
    assert result["unlockGateStatus"] == "READY"
    assert result["stockRestoreGateStatus"] == "READY"
    assert result["gsiCandidateGateStatus"] == "READY"
    assert result["dsuPreflightGateStatus"] == "READY"
    assert result["fastbootGateStatus"] == "READY"
    assert result["destructiveApprovalStatus"] == "WITHHELD"
    assert result["checkedOperatorChecklist"] is True
    assert result["operatorChecklistStatus"] == "READY_FOR_ROM0_READINESS_REVIEW"
    assert result["blockerCount"] == 0
    assert result["blockers"] == []


def test_rom_status_rejects_ready_claim_without_gate_evidence(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(
            rom_ready=True,
            blocked_by=[],
            evidence_inputs=[],
        ),
    )
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(status="READY_FOR_ROM0_READINESS_REVIEW"),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["romReady"] is False
    assert result["installDecision"] == "BLOCKED"
    assert "ROM-0 install gate statuses are incomplete" in result["blockers"]


def test_rom_status_rejects_ready_claim_without_dsu_preflight(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(
            rom_ready=True,
            blocked_by=[],
            evidence_inputs=[
                evidence_input("unlock_eligibility", "LOADED"),
                evidence_input("stock_restore", "LOADED"),
                evidence_input("gsi_candidate", "LOADED"),
                evidence_input("fastboot_evidence", "LOADED"),
            ],
        ),
    )
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(status="READY_FOR_ROM0_READINESS_REVIEW"),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["romReady"] is False
    assert result["dsuPreflightGateStatus"] == "MISSING"
    assert result["installDecision"] == "BLOCKED"
    assert "ROM-0 install gate statuses are incomplete" in result["blockers"]


def test_rom_status_marks_loaded_fastboot_without_manual_visibility_as_host_only(
    tmp_path: Path,
) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(
            bootloader_visibility_status="READY_FOR_MANUAL_BOOTLOADER_CHECK",
            evidence_inputs=[
                evidence_input("unlock_eligibility", "LOADED"),
                evidence_input("stock_restore", "LOADED"),
                evidence_input("gsi_candidate", "LOADED"),
                evidence_input("dsu_preflight", "LOADED"),
                evidence_input("fastboot_evidence", "LOADED"),
            ],
        ),
    )
    write_json(validation_dir / "rom-0-operator-checklist.json", operator_payload())

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["fastbootGateStatus"] == "HOST_READY_ONLY"
    assert result["installDecision"] == "BLOCKED"


def test_rom_status_marks_semantically_rejected_unlock_as_blocked(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(
            blocked_by=[
                "manual OEM or Motorola unlock eligibility evidence is missing or not eligible"
            ],
            evidence_inputs=[
                evidence_input("unlock_eligibility", "LOADED"),
                evidence_input("stock_restore", "LOADED"),
                evidence_input("gsi_candidate", "LOADED"),
                evidence_input("dsu_preflight", "LOADED"),
                evidence_input("fastboot_evidence", "LOADED"),
            ],
        ),
    )
    write_json(validation_dir / "rom-0-operator-checklist.json", operator_payload())

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["unlockGateStatus"] == "BLOCKED"
    assert result["installDecision"] == "BLOCKED"


def test_rom_status_rejects_contradictory_refresh_ready_fields(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(
            rom_ready=True,
            status="BLOCKED",
            packet_status="BLOCKED_MANUAL_EVIDENCE",
            blocked_by=[],
        ),
    )
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(status="READY_FOR_ROM0_READINESS_REVIEW"),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "available"
    assert result["romReady"] is False
    assert "ROM-0 refresh status is BLOCKED" in result["blockers"]
    assert "ROM-0 packet status is BLOCKED_MANUAL_EVIDENCE" in result["blockers"]


def test_rom_status_fails_closed_for_destructive_artifact(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(destructive_actions="allowed"),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "invalid"
    assert result["romReady"] is False
    assert result["destructiveActions"] == "withheld"
    assert "withhold destructive actions" in result["summary"]


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "safe\u202ehidden",
        "safe\u009fhidden",
        "/Users/example/private/rom-stock-restore-evidence.json",
        "file:///Users/example/private/rom-stock-restore-evidence.json",
    ],
)
def test_rom_status_fails_closed_for_unsafe_display_text(
    tmp_path: Path,
    unsafe_text: str,
) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-refresh-report.json",
        refresh_payload(blocked_by=[unsafe_text]),
    )

    result = goffy_rom_status_snapshot(root=tmp_path)

    assert result["status"] == "invalid"
    assert result["romReady"] is False
    assert "unsafe display text" in result["summary"]


@pytest.mark.asyncio
async def test_rom_status_tool_registers_with_safe_metadata(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(build_goffy_rom_status_tool(tmp_path, timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    capability = registry.discover(TOOL_NAME)[0]

    assert capability.name == TOOL_NAME
    assert capability.meta.permission.value == "SAFE"
    assert capability.meta.execution_target.value == "MAC"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False
    assert capability.input_schema["properties"] == {}
    assert capability.output_schema["properties"]["blockers"]["maxItems"] == 8


@pytest.mark.asyncio
async def test_rom_status_tool_invocation_returns_missing_as_schema_valid(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(build_goffy_rom_status_tool(tmp_path, timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    result = await registry.invoke(TOOL_NAME, {})

    assert result.definition.name == TOOL_NAME
    assert result.structured_content["status"] == "missing"
    assert result.structured_content["checkedRefreshReport"] is False


def test_rom_checklist_reports_missing_operator_artifact(tmp_path: Path) -> None:
    result = goffy_rom_checklist_snapshot(root=tmp_path)

    assert result["status"] == "missing"
    assert result["milestone"] == "ROM-0"
    assert result["destructiveActions"] == "withheld"
    assert result["checkedOperatorChecklist"] is False
    assert result["nextSteps"] == []
    assert result["blockerCount"] == 1


def test_rom_checklist_summarizes_next_steps_without_paths_or_commands(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(
            steps=[
                checklist_step(
                    "refresh_rom0_evidence",
                    title="Refresh ROM-0 evidence",
                    status="DONE",
                    kind="LOCAL_READ_ONLY",
                    summary="Read-only probe and action packet are current.",
                ),
                checklist_step(
                    "record_stock_restore",
                    title="Record exact stock restore evidence",
                    status="READY",
                    summary="Record the official Motorola restore archive name and checksum.",
                ),
                checklist_step(
                    "record_dsu_preflight",
                    title="Record read-only DSU preflight",
                    status="BLOCKED",
                    kind="LOCAL_READ_ONLY",
                    summary="Check DSU prerequisites from local evidence only.",
                    blockers=[
                        "stock restore evidence must be recorded before DSU decisions advance"
                    ],
                ),
            ],
        ),
    )

    result = goffy_rom_checklist_snapshot(root=tmp_path)
    serialized = json.dumps(result)

    assert result["status"] == "available"
    assert result["checklistStatus"] == "BLOCKED_EVIDENCE"
    assert result["totalStepCount"] == 3
    assert result["doneStepCount"] == 1
    assert result["remainingStepCount"] == 2
    assert result["nextStepTitle"] == "Record exact stock restore evidence"
    assert result["nextStepStatus"] == "READY"
    assert result["nextSteps"] == [
        {
            "stepIndex": 2,
            "title": "Record exact stock restore evidence",
            "kind": "HUMAN_ONLY",
            "status": "READY",
            "summary": "Record the official Motorola restore archive name and checksum.",
            "blocked": False,
            "blockerCount": 0,
        },
        {
            "stepIndex": 3,
            "title": "Record read-only DSU preflight",
            "kind": "LOCAL_READ_ONLY",
            "status": "BLOCKED",
            "summary": "Check DSU prerequisites from local evidence only.",
            "blocked": True,
            "blockerCount": 1,
        },
    ]
    assert "safe_commands" not in serialized
    assert "evidence_paths" not in serialized
    assert ".goffy-validation" not in serialized
    assert "scripts/create_rom" not in serialized


def test_rom_checklist_allows_safe_acronym_slash_terms(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(
            steps=[
                checklist_step(
                    "record_gsi_candidate",
                    title="Record official GSI archive evidence",
                    status="READY",
                    summary="Record DSU/GSI readiness evidence without paths.",
                    blockers=[
                        "stock restore evidence must be recorded before DSU/GSI decisions advance"
                    ],
                )
            ],
        ),
    )

    result = goffy_rom_checklist_snapshot(root=tmp_path)

    assert result["status"] == "available"
    assert result["checklistStatus"] == "BLOCKED_EVIDENCE"
    assert result["nextSteps"][0]["summary"] == "Record DSU/GSI readiness evidence without paths."


def test_rom_checklist_fails_closed_for_destructive_operator_artifact(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(
            destructive_actions="allowed",
            steps=[
                checklist_step(
                    "record_stock_restore",
                    title="Record exact stock restore evidence",
                    status="READY",
                )
            ],
        ),
    )

    result = goffy_rom_checklist_snapshot(root=tmp_path)

    assert result["status"] == "invalid"
    assert result["destructiveActions"] == "withheld"
    assert result["checkedOperatorChecklist"] is False


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "/Users/example/private/stock.zip",
        "adb reboot bootloader now",
        "Run fastboot flash boot boot.img next",
        "Use shell to continue",
    ],
)
def test_rom_checklist_fails_closed_for_unsafe_step_text(
    tmp_path: Path,
    unsafe_text: str,
) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(
            steps=[
                checklist_step(
                    "record_stock_restore",
                    title="Record exact stock restore evidence",
                    status="READY",
                    summary=unsafe_text,
                )
            ],
        ),
    )

    result = goffy_rom_checklist_snapshot(root=tmp_path)

    assert result["status"] == "invalid"
    assert result["checklistStatus"] == "INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "ROOT_SHELL"),
        ("status", "REBOOT_REQUIRED"),
    ],
)
def test_rom_checklist_fails_closed_for_unknown_step_enums(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    step = checklist_step(
        "record_stock_restore",
        title="Record exact stock restore evidence",
        status="READY",
    )
    step[field] = value
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(steps=[step]),
    )

    result = goffy_rom_checklist_snapshot(root=tmp_path)

    assert result["status"] == "invalid"
    assert result["checklistStatus"] == "INVALID"


def test_rom_checklist_fails_closed_for_command_like_blockers(tmp_path: Path) -> None:
    validation_dir = tmp_path / ".goffy-validation"
    write_json(
        validation_dir / "rom-0-operator-checklist.json",
        operator_payload(
            steps=[
                checklist_step(
                    "record_stock_restore",
                    title="Record exact stock restore evidence",
                    status="READY",
                )
            ],
        )
        | {"blocked_by": ["Run fastboot boot boot.img next"]},
    )

    result = goffy_rom_checklist_snapshot(root=tmp_path)

    assert result["status"] == "invalid"
    assert result["checklistStatus"] == "INVALID"


@pytest.mark.asyncio
async def test_rom_checklist_tool_registers_with_safe_metadata(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(build_goffy_rom_checklist_tool(tmp_path, timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    capability = registry.discover(CHECKLIST_TOOL_NAME)[0]

    assert capability.name == CHECKLIST_TOOL_NAME
    assert capability.meta.permission.value == "SAFE"
    assert capability.meta.execution_target.value == "MAC"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False
    assert capability.input_schema["properties"] == {}
    assert capability.output_schema["properties"]["nextSteps"]["maxItems"] == 6
    assert capability.output_schema["properties"]["blockers"]["maxItems"] == 8
    assert capability.output_schema["properties"]["checklistStatus"]["enum"] == [
        "BLOCKED_EVIDENCE",
        "READY_FOR_ROM0_READINESS_REVIEW",
        "MISSING",
        "INVALID",
    ]
    step_schema = capability.output_schema["$defs"]["GoffyRomChecklistStepOutput"]
    assert step_schema["properties"]["kind"]["enum"] == [
        "LOCAL_READ_ONLY",
        "HUMAN_ONLY",
        "TEMPLATE_ONLY",
        "HUMAN_DECISION",
    ]
    assert step_schema["properties"]["status"]["enum"] == ["DONE", "READY", "BLOCKED"]


@pytest.mark.asyncio
async def test_rom_checklist_tool_invocation_returns_missing_as_schema_valid(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry()
    registry.register(build_goffy_rom_checklist_tool(tmp_path, timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    result = await registry.invoke(CHECKLIST_TOOL_NAME, {})

    assert result.definition.name == CHECKLIST_TOOL_NAME
    assert result.structured_content["status"] == "missing"
    assert result.structured_content["checkedOperatorChecklist"] is False
