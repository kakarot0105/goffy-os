from __future__ import annotations

import json
from pathlib import Path

import pytest

from goffy_hub.registry import ToolRegistry
from goffy_hub.tools.rom_status import (
    LATEST_REFRESH_SCHEMA,
    TOOL_NAME,
    build_goffy_rom_status_tool,
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
    blocked_by: list[str] | None = None,
) -> dict[str, object]:
    refresh_status = status or ("BLOCKED" if not rom_ready else "READY_FOR_ROM0_READINESS_REVIEW")
    packet_status_value = packet_status or (
        "BLOCKED_MANUAL_EVIDENCE" if not rom_ready else "READY_FOR_ROM0_READINESS_REVIEW"
    )
    return {
        "schema_version": schema_version,
        "generated_at": "2026-07-22T15:00:00+00:00",
        "status": refresh_status,
        "refresh_succeeded": refresh_succeeded,
        "rom_ready": rom_ready,
        "destructive_actions": destructive_actions,
        "packet_status": packet_status_value,
        "bootloader_visibility_status": "READY_FOR_MANUAL_BOOTLOADER_CHECK",
        "operator_checklist_status": "BLOCKED_EVIDENCE"
        if not rom_ready
        else "READY_FOR_ROM0_READINESS_REVIEW",
        "blocked_by": blocked_by
        if blocked_by is not None
        else ["exact stock restore evidence is missing"],
        "errors": [],
    }


def operator_payload(*, status: str = "BLOCKED_EVIDENCE") -> dict[str, object]:
    ready = status == "READY_FOR_ROM0_READINESS_REVIEW"
    return {
        "schema_version": "goffy.rom0-operator-checklist.v1",
        "generated_at": "2026-07-22T15:00:01+00:00",
        "ok": ready,
        "status": status,
        "destructive_actions": "withheld",
        "source_refresh_report": ".goffy-validation/rom-0-refresh-report.json",
        "blocked_by": [] if ready else ["exact stock restore evidence is missing"],
        "steps": [],
        "reuse_decision": "Reuse GOFFY typed evidence validators.",
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
    assert result["checkedOperatorChecklist"] is True
    assert result["operatorChecklistStatus"] == "READY_FOR_ROM0_READINESS_REVIEW"
    assert result["blockerCount"] == 0
    assert result["blockers"] == []


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
