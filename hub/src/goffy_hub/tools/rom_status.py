from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic.alias_generators import to_camel

from goffy_hub.registry import ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations

TOOL_NAME = "goffy.rom.status"
TOOL_VERSION = "1.0.0"
CHECKLIST_TOOL_NAME = "goffy.rom.checklist"
CHECKLIST_TOOL_VERSION = "1.0.0"
CHECKLIST_STATUS_VALUES = (
    "BLOCKED_EVIDENCE",
    "READY_FOR_ROM0_READINESS_REVIEW",
    "MISSING",
    "INVALID",
)
CHECKLIST_STEP_STATUS_VALUES = ("DONE", "READY", "BLOCKED")
CHECKLIST_NEXT_STEP_STATUS_VALUES = CHECKLIST_STEP_STATUS_VALUES + ("MISSING", "INVALID")
CHECKLIST_STEP_KIND_VALUES = (
    "LOCAL_READ_ONLY",
    "HUMAN_ONLY",
    "TEMPLATE_ONLY",
    "HUMAN_DECISION",
)
VALIDATION_DIR = Path(".goffy-validation")
REFRESH_REPORT_FILENAME = "rom-0-refresh-report.json"
OPERATOR_CHECKLIST_FILENAME = "rom-0-operator-checklist.json"
LATEST_REFRESH_SCHEMA = "goffy.rom0-refresh-report.v4"
SUPPORTED_REFRESH_SCHEMAS = frozenset(
    (
        "goffy.rom0-refresh-report.v1",
        "goffy.rom0-refresh-report.v2",
        "goffy.rom0-refresh-report.v3",
        LATEST_REFRESH_SCHEMA,
    )
)
SUPPORTED_OPERATOR_SCHEMA = "goffy.rom0-operator-checklist.v1"
READY_FOR_ROM0_REVIEW = "READY_FOR_ROM0_READINESS_REVIEW"
UNLOCK_NOT_ACCEPTED_BLOCKER = (
    "manual OEM or Motorola unlock eligibility evidence is missing or not eligible"
)
MAX_ARTIFACT_BYTES = 64_000
MAX_BLOCKERS = 8
MAX_BLOCKER_LENGTH = 160
MAX_STATUS_LENGTH = 96
MAX_SUMMARY_LENGTH = 192
MAX_NEXT_ACTION_LENGTH = 192
MAX_CHECKLIST_STEPS = 6
MAX_CHECKLIST_STEP_COUNT = 100
MAX_CHECKLIST_STEP_TITLE_LENGTH = 96
MAX_CHECKLIST_STEP_KIND_LENGTH = 48
MAX_CHECKLIST_STEP_SUMMARY_LENGTH = 192
BlockerText = Annotated[str, Field(min_length=1, max_length=MAX_BLOCKER_LENGTH)]
ChecklistStatusText = Literal[
    "BLOCKED_EVIDENCE",
    "READY_FOR_ROM0_READINESS_REVIEW",
    "MISSING",
    "INVALID",
]
ChecklistStepStatusText = Literal["DONE", "READY", "BLOCKED"]
ChecklistNextStepStatusText = Literal["DONE", "READY", "BLOCKED", "MISSING", "INVALID"]
ChecklistStepKindText = Literal[
    "LOCAL_READ_ONLY",
    "HUMAN_ONLY",
    "TEMPLATE_ONLY",
    "HUMAN_DECISION",
]
COMMAND_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:adb|fastboot)\s+"
        r"(?:reboot|shell|sideload|push|install|uninstall|root|remount|"
        r"disable-verity|enable-verity|flash|flashing|oem|erase|wipe|boot|getvar|devices)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:avbctl|magisk)\b", re.IGNORECASE),
    re.compile(r"\b(?:sh|su|pm|cmd|am|rm|dd|mkfs)\s+", re.IGNORECASE),
    re.compile(r"\breboot\s+(?:bootloader|fastboot|recovery)\b", re.IGNORECASE),
    re.compile(r"\bflash\s+(?:boot|system|vendor|vbmeta|image)\b", re.IGNORECASE),
    re.compile(r"\bboot\s+\S+\.img\b", re.IGNORECASE),
    re.compile(r"\bshell\b", re.IGNORECASE),
)
SAFE_SLASH_TOKEN = re.compile(r"\b[A-Z0-9]{2,8}(?:/[A-Z0-9]{2,8})+\b")


class GoffyRomStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GoffyRomChecklistInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GoffyRomChecklistStepOutput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    step_index: int = Field(ge=1, le=MAX_CHECKLIST_STEP_COUNT)
    title: str = Field(min_length=1, max_length=MAX_CHECKLIST_STEP_TITLE_LENGTH)
    kind: ChecklistStepKindText
    status: ChecklistStepStatusText
    summary: str = Field(min_length=1, max_length=MAX_CHECKLIST_STEP_SUMMARY_LENGTH)
    blocked: bool
    blocker_count: int = Field(ge=0, le=MAX_CHECKLIST_STEP_COUNT)

    @field_validator("title", "kind", "status", "summary")
    @classmethod
    def reject_unsafe_step_text(cls, value: str) -> str:
        return _bounded_text(value, maximum=MAX_CHECKLIST_STEP_SUMMARY_LENGTH)


class GoffyRomStatusOutput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    status: Literal["available", "missing", "invalid"]
    milestone: Literal["ROM-0"]
    summary: str = Field(min_length=1, max_length=MAX_SUMMARY_LENGTH)
    generated_at: str = Field(min_length=1, max_length=64)
    refresh_schema_version: str = Field(min_length=1, max_length=64)
    refresh_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    packet_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    bootloader_visibility_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    operator_checklist_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    install_decision: Literal["BLOCKED", "READY_FOR_MANUAL_REVIEW"]
    unlock_gate_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    stock_restore_gate_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    gsi_candidate_gate_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    dsu_preflight_gate_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    fastboot_gate_status: str = Field(min_length=1, max_length=MAX_STATUS_LENGTH)
    destructive_approval_status: Literal["WITHHELD"]
    rom_ready: bool
    destructive_actions: Literal["withheld"]
    blocker_count: int = Field(ge=0, le=10_000)
    blockers: list[BlockerText] = Field(max_length=MAX_BLOCKERS)
    blockers_truncated: bool
    next_action: str = Field(min_length=1, max_length=MAX_NEXT_ACTION_LENGTH)
    stale_report: bool
    checked_refresh_report: bool
    checked_operator_checklist: bool

    @field_validator(
        "summary",
        "generated_at",
        "refresh_schema_version",
        "refresh_status",
        "packet_status",
        "bootloader_visibility_status",
        "operator_checklist_status",
        "unlock_gate_status",
        "stock_restore_gate_status",
        "gsi_candidate_gate_status",
        "dsu_preflight_gate_status",
        "fastboot_gate_status",
        "next_action",
    )
    @classmethod
    def reject_control_text(cls, value: str) -> str:
        return _bounded_text(value, maximum=max(MAX_SUMMARY_LENGTH, MAX_NEXT_ACTION_LENGTH))

    @field_validator("blockers")
    @classmethod
    def reject_unsafe_blockers(cls, value: list[str]) -> list[str]:
        return [_bounded_text(item, maximum=MAX_BLOCKER_LENGTH) for item in value]


class GoffyRomChecklistOutput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    status: Literal["available", "missing", "invalid"]
    milestone: Literal["ROM-0"]
    generated_at: str = Field(min_length=1, max_length=64)
    checklist_status: ChecklistStatusText
    destructive_actions: Literal["withheld"]
    total_step_count: int = Field(ge=0, le=MAX_CHECKLIST_STEP_COUNT)
    done_step_count: int = Field(ge=0, le=MAX_CHECKLIST_STEP_COUNT)
    remaining_step_count: int = Field(ge=0, le=MAX_CHECKLIST_STEP_COUNT)
    next_steps: list[GoffyRomChecklistStepOutput] = Field(max_length=MAX_CHECKLIST_STEPS)
    next_steps_truncated: bool
    blocker_count: int = Field(ge=0, le=10_000)
    blockers: list[BlockerText] = Field(max_length=MAX_BLOCKERS)
    blockers_truncated: bool
    next_step_title: str = Field(min_length=1, max_length=MAX_CHECKLIST_STEP_TITLE_LENGTH)
    next_step_status: ChecklistNextStepStatusText
    next_action: str = Field(min_length=1, max_length=MAX_NEXT_ACTION_LENGTH)
    checked_operator_checklist: bool

    @field_validator(
        "generated_at",
        "checklist_status",
        "next_step_title",
        "next_step_status",
        "next_action",
    )
    @classmethod
    def reject_control_text(cls, value: str) -> str:
        return _bounded_text(value, maximum=MAX_NEXT_ACTION_LENGTH)

    @field_validator("blockers")
    @classmethod
    def reject_unsafe_blockers(cls, value: list[str]) -> list[str]:
        return [_bounded_text(item, maximum=MAX_BLOCKER_LENGTH) for item in value]


async def read_goffy_rom_status(_request: BaseModel, *, root: Path) -> dict[str, Any]:
    return goffy_rom_status_snapshot(root=root)


async def read_goffy_rom_checklist(_request: BaseModel, *, root: Path) -> dict[str, Any]:
    return goffy_rom_checklist_snapshot(root=root)


async def check_goffy_rom_status_health(root: Path) -> bool:
    validation_dir = root / VALIDATION_DIR
    return not validation_dir.is_symlink()


def goffy_rom_status_snapshot(*, root: Path) -> dict[str, Any]:
    repo_root = root.expanduser().resolve(strict=False)
    validation_dir = repo_root / VALIDATION_DIR
    if validation_dir.is_symlink():
        return _invalid_status("ROM-0 validation directory is not a regular local directory")

    refresh_path = validation_dir / REFRESH_REPORT_FILENAME
    operator_path = validation_dir / OPERATOR_CHECKLIST_FILENAME
    if not refresh_path.exists():
        return _missing_status()
    if refresh_path.is_symlink() or not refresh_path.is_file():
        return _invalid_status("ROM-0 refresh report is not a regular local artifact")

    try:
        refresh_report = _read_json_mapping(refresh_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _invalid_status("ROM-0 refresh report is unreadable or malformed")

    try:
        schema_version = _string_value(refresh_report.get("schema_version"), default="unknown")
        if schema_version not in SUPPORTED_REFRESH_SCHEMAS:
            return _invalid_status("ROM-0 refresh report schema is unsupported")
        if refresh_report.get("destructive_actions") != "withheld":
            return _invalid_status("ROM-0 refresh report did not withhold destructive actions")

        operator_status = "MISSING"
        operator_ok = False
        operator_blockers: tuple[str, ...] = ()
        checked_operator = False
        if operator_path.exists():
            if operator_path.is_symlink() or not operator_path.is_file():
                return _invalid_status("ROM-0 operator checklist is not a regular local artifact")
            try:
                operator_report = _read_json_mapping(operator_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                return _invalid_status("ROM-0 operator checklist is unreadable or malformed")
            if operator_report.get("schema_version") != SUPPORTED_OPERATOR_SCHEMA:
                return _invalid_status("ROM-0 operator checklist schema is unsupported")
            if operator_report.get("destructive_actions") != "withheld":
                return _invalid_status(
                    "ROM-0 operator checklist did not withhold destructive actions"
                )
            operator_status = _string_value(operator_report.get("status"), default=operator_status)
            operator_ok = operator_report.get("ok") is True
            operator_blockers = _string_items(operator_report.get("blocked_by"))
            checked_operator = True

        stale_report = schema_version != LATEST_REFRESH_SCHEMA
        refresh_status = _string_value(refresh_report.get("status"), default="UNKNOWN")
        packet_status = _string_value(refresh_report.get("packet_status"), default="UNKNOWN")
        bootloader_status = _string_value(
            refresh_report.get("bootloader_visibility_status"),
            default="MISSING",
        )
        generated_at = _string_value(refresh_report.get("generated_at"), default="unknown")
        raw_blockers = _string_items(refresh_report.get("blocked_by"))
        evidence_statuses = _evidence_statuses(refresh_report)
        unlock_gate_status = _unlock_gate_status(
            evidence_statuses,
            refresh_blockers=raw_blockers,
        )
        stock_restore_gate_status = _gate_status_from_evidence(
            evidence_statuses,
            "stock_restore",
        )
        gsi_candidate_gate_status = _gate_status_from_evidence(
            evidence_statuses,
            "gsi_candidate",
        )
        dsu_preflight_gate_status = _gate_status_from_evidence(
            evidence_statuses,
            "dsu_preflight",
        )
        fastboot_gate_status = _fastboot_gate_status(
            evidence_statuses,
            bootloader_status=bootloader_status,
        )
        blockers = [_bounded_text(item, maximum=MAX_BLOCKER_LENGTH) for item in raw_blockers]
        blockers.extend(
            _bounded_text(item, maximum=MAX_BLOCKER_LENGTH) for item in operator_blockers
        )
        if stale_report:
            blockers.append("ROM-0 refresh report is stale; regenerate the operator packet")
        refresh_claims_ready = refresh_report.get("rom_ready") is True
        if refresh_claims_ready:
            if refresh_report.get("refresh_succeeded") is not True:
                blockers.append("ROM-0 refresh did not complete successfully")
            if refresh_status != READY_FOR_ROM0_REVIEW:
                blockers.append(f"ROM-0 refresh status is {refresh_status}")
            if packet_status != READY_FOR_ROM0_REVIEW:
                blockers.append(f"ROM-0 packet status is {packet_status}")
        if not checked_operator:
            blockers.append("ROM-0 operator checklist evidence is missing")
        elif operator_status != READY_FOR_ROM0_REVIEW:
            blockers.append(f"ROM-0 operator checklist status is {operator_status}")
        elif not operator_ok:
            blockers.append("ROM-0 operator checklist readiness is not verified")
        gate_statuses_ready = (
            unlock_gate_status == "READY"
            and stock_restore_gate_status == "READY"
            and gsi_candidate_gate_status == "READY"
            and dsu_preflight_gate_status == "READY"
            and fastboot_gate_status == "READY"
        )
        if refresh_claims_ready and not gate_statuses_ready:
            blockers.append("ROM-0 install gate statuses are incomplete")
        rom_ready = (
            refresh_claims_ready
            and refresh_report.get("refresh_succeeded") is True
            and gate_statuses_ready
            and not stale_report
            and refresh_status == READY_FOR_ROM0_REVIEW
            and packet_status == READY_FOR_ROM0_REVIEW
            and checked_operator
            and operator_status == READY_FOR_ROM0_REVIEW
            and operator_ok
            and not blockers
        )
        install_decision: Literal["BLOCKED", "READY_FOR_MANUAL_REVIEW"] = (
            "READY_FOR_MANUAL_REVIEW" if rom_ready else "BLOCKED"
        )
        if not rom_ready and not blockers:
            blockers.append("ROM-0 readiness evidence is incomplete")
        unique_blockers = tuple(dict.fromkeys(blockers))
        visible_blockers = unique_blockers[:MAX_BLOCKERS]
        blocker_count = len(unique_blockers)
        next_action = _next_action(visible_blockers, stale_report=stale_report, rom_ready=rom_ready)
        summary = _summary(
            rom_ready=rom_ready,
            stale_report=stale_report,
            blocker_count=blocker_count,
            refresh_status=refresh_status,
        )
    except ValueError:
        return _invalid_status("ROM-0 evidence artifacts contain unsafe display text")
    try:
        return GoffyRomStatusOutput(
            status="available",
            milestone="ROM-0",
            summary=summary,
            generated_at=generated_at,
            refresh_schema_version=schema_version,
            refresh_status=refresh_status,
            packet_status=packet_status,
            bootloader_visibility_status=bootloader_status,
            operator_checklist_status=operator_status,
            install_decision=install_decision,
            unlock_gate_status=unlock_gate_status,
            stock_restore_gate_status=stock_restore_gate_status,
            gsi_candidate_gate_status=gsi_candidate_gate_status,
            dsu_preflight_gate_status=dsu_preflight_gate_status,
            fastboot_gate_status=fastboot_gate_status,
            destructive_approval_status="WITHHELD",
            rom_ready=rom_ready,
            destructive_actions="withheld",
            blocker_count=blocker_count,
            blockers=list(visible_blockers),
            blockers_truncated=blocker_count > len(visible_blockers),
            next_action=next_action,
            stale_report=stale_report,
            checked_refresh_report=True,
            checked_operator_checklist=checked_operator,
        ).model_dump(mode="json", by_alias=True)
    except (ValidationError, ValueError):
        return _invalid_status("ROM-0 evidence artifacts contain invalid status fields")


def goffy_rom_checklist_snapshot(*, root: Path) -> dict[str, Any]:
    repo_root = root.expanduser().resolve(strict=False)
    validation_dir = repo_root / VALIDATION_DIR
    if validation_dir.is_symlink():
        return _invalid_checklist("ROM-0 validation directory is not a regular local directory")

    operator_path = validation_dir / OPERATOR_CHECKLIST_FILENAME
    if not operator_path.exists():
        return _missing_checklist()
    if operator_path.is_symlink() or not operator_path.is_file():
        return _invalid_checklist("ROM-0 operator checklist is not a regular local artifact")

    try:
        operator_report = _read_json_mapping(operator_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return _invalid_checklist("ROM-0 operator checklist is unreadable or malformed")

    try:
        if operator_report.get("schema_version") != SUPPORTED_OPERATOR_SCHEMA:
            return _invalid_checklist("ROM-0 operator checklist schema is unsupported")
        if operator_report.get("destructive_actions") != "withheld":
            return _invalid_checklist(
                "ROM-0 operator checklist did not withhold destructive actions"
            )

        generated_at = _text_value(operator_report.get("generated_at"), "unknown", maximum=64)
        checklist_status = _checklist_status_value(operator_report.get("status"))
        steps = _operator_steps(operator_report)
        if not steps:
            return _invalid_checklist("ROM-0 operator checklist contains no steps")
        blockers = tuple(
            dict.fromkeys(
                _bounded_text(item, maximum=MAX_BLOCKER_LENGTH)
                for item in _string_items(operator_report.get("blocked_by"))
            )
        )
        done_step_count = sum(1 for step in steps if step.status == "DONE")
        remaining_steps = [step for step in steps if step.status != "DONE"]
        visible_steps = remaining_steps[:MAX_CHECKLIST_STEPS]
        next_step = next(
            (step for step in remaining_steps if not step.blocked and step.status != "BLOCKED"),
            remaining_steps[0] if remaining_steps else None,
        )
        if next_step is None:
            next_step_title = "ROM-0 readiness review"
            next_step_status: ChecklistNextStepStatusText = "READY"
            next_action = "Review ROM-0 readiness manually before any destructive decision"
        else:
            next_step_title = next_step.title
            next_step_status = next_step.status
            next_action = _bounded_text(
                f"Complete {next_step.title}",
                maximum=MAX_NEXT_ACTION_LENGTH,
            )

        return GoffyRomChecklistOutput(
            status="available",
            milestone="ROM-0",
            generated_at=generated_at,
            checklist_status=checklist_status,
            destructive_actions="withheld",
            total_step_count=len(steps),
            done_step_count=done_step_count,
            remaining_step_count=len(remaining_steps),
            next_steps=visible_steps,
            next_steps_truncated=len(remaining_steps) > len(visible_steps),
            blocker_count=len(blockers),
            blockers=list(blockers[:MAX_BLOCKERS]),
            blockers_truncated=len(blockers) > MAX_BLOCKERS,
            next_step_title=next_step_title,
            next_step_status=next_step_status,
            next_action=next_action,
            checked_operator_checklist=True,
        ).model_dump(mode="json", by_alias=True)
    except (ValidationError, ValueError):
        return _invalid_checklist("ROM-0 operator checklist contains unsafe display text")


def build_goffy_rom_status_tool(
    root: Path,
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    resolved_root = root.expanduser().resolve(strict=False)

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await read_goffy_rom_status(request, root=resolved_root)

    async def health_probe() -> bool:
        return await check_goffy_rom_status_health(resolved_root)

    return ToolDefinition(
        name=TOOL_NAME,
        title="GOFFY ROM status",
        description=(
            "Read the local GOFFY ROM-0 readiness packet summary without flashing, "
            "unlocking, rebooting, or exposing raw artifact paths."
        ),
        tool_version=TOOL_VERSION,
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=GoffyRomStatusInput,
        output_model=GoffyRomStatusOutput,
        handler=handler,
        health_probe=health_probe,
        health_timeout_seconds=health_timeout_seconds,
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )


def build_goffy_rom_checklist_tool(
    root: Path,
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    resolved_root = root.expanduser().resolve(strict=False)

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await read_goffy_rom_checklist(request, root=resolved_root)

    async def health_probe() -> bool:
        return await check_goffy_rom_status_health(resolved_root)

    return ToolDefinition(
        name=CHECKLIST_TOOL_NAME,
        title="GOFFY ROM operator checklist",
        description=(
            "Read the bounded GOFFY ROM-0 operator checklist without exposing raw "
            "artifact paths or command strings, and without granting unlock, reboot, "
            "flash, erase, wipe, boot, or shell authority."
        ),
        tool_version=CHECKLIST_TOOL_VERSION,
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=GoffyRomChecklistInput,
        output_model=GoffyRomChecklistOutput,
        handler=handler,
        health_probe=health_probe,
        health_timeout_seconds=health_timeout_seconds,
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )


def _missing_status() -> dict[str, Any]:
    blocker = "run the read-only ROM-0 refresh packet before relying on ROM status"
    return GoffyRomStatusOutput(
        status="missing",
        milestone="ROM-0",
        summary="ROM-0 refresh evidence is missing",
        generated_at="unknown",
        refresh_schema_version="missing",
        refresh_status="MISSING",
        packet_status="MISSING",
        bootloader_visibility_status="MISSING",
        operator_checklist_status="MISSING",
        install_decision="BLOCKED",
        unlock_gate_status="MISSING",
        stock_restore_gate_status="MISSING",
        gsi_candidate_gate_status="MISSING",
        dsu_preflight_gate_status="MISSING",
        fastboot_gate_status="MISSING",
        destructive_approval_status="WITHHELD",
        rom_ready=False,
        destructive_actions="withheld",
        blocker_count=1,
        blockers=[blocker],
        blockers_truncated=False,
        next_action="Run the read-only ROM-0 refresh packet on the Mac",
        stale_report=True,
        checked_refresh_report=False,
        checked_operator_checklist=False,
    ).model_dump(mode="json", by_alias=True)


def _invalid_status(summary: str) -> dict[str, Any]:
    blocker = "repair ROM-0 evidence artifacts before any ROM readiness decision"
    return GoffyRomStatusOutput(
        status="invalid",
        milestone="ROM-0",
        summary=summary,
        generated_at="unknown",
        refresh_schema_version="invalid",
        refresh_status="INVALID",
        packet_status="INVALID",
        bootloader_visibility_status="INVALID",
        operator_checklist_status="INVALID",
        install_decision="BLOCKED",
        unlock_gate_status="INVALID",
        stock_restore_gate_status="INVALID",
        gsi_candidate_gate_status="INVALID",
        dsu_preflight_gate_status="INVALID",
        fastboot_gate_status="INVALID",
        destructive_approval_status="WITHHELD",
        rom_ready=False,
        destructive_actions="withheld",
        blocker_count=1,
        blockers=[blocker],
        blockers_truncated=False,
        next_action="Regenerate the ROM-0 packet before continuing",
        stale_report=True,
        checked_refresh_report=False,
        checked_operator_checklist=False,
    ).model_dump(mode="json", by_alias=True)


def _missing_checklist() -> dict[str, Any]:
    blocker = "run the read-only ROM-0 refresh packet before relying on the checklist"
    return GoffyRomChecklistOutput(
        status="missing",
        milestone="ROM-0",
        generated_at="unknown",
        checklist_status="MISSING",
        destructive_actions="withheld",
        total_step_count=0,
        done_step_count=0,
        remaining_step_count=0,
        next_steps=[],
        next_steps_truncated=False,
        blocker_count=1,
        blockers=[blocker],
        blockers_truncated=False,
        next_step_title="Refresh ROM-0 evidence",
        next_step_status="MISSING",
        next_action="Run the read-only ROM-0 refresh packet on the Mac",
        checked_operator_checklist=False,
    ).model_dump(mode="json", by_alias=True)


def _invalid_checklist(summary: str) -> dict[str, Any]:
    blocker = "repair ROM-0 checklist artifacts before any ROM readiness decision"
    return GoffyRomChecklistOutput(
        status="invalid",
        milestone="ROM-0",
        generated_at="unknown",
        checklist_status="INVALID",
        destructive_actions="withheld",
        total_step_count=0,
        done_step_count=0,
        remaining_step_count=0,
        next_steps=[],
        next_steps_truncated=False,
        blocker_count=1,
        blockers=[blocker],
        blockers_truncated=False,
        next_step_title="Repair ROM-0 checklist",
        next_step_status="INVALID",
        next_action="Regenerate the ROM-0 operator checklist before continuing",
        checked_operator_checklist=False,
    ).model_dump(mode="json", by_alias=True)


def _read_json_mapping(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds ROM status size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("artifact root must be an object")
    return cast(dict[str, Any], value)


def _string_value(value: object, *, default: str) -> str:
    return _text_value(value, default, maximum=MAX_STATUS_LENGTH)


def _text_value(value: object, default: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    return _bounded_text(value, maximum=maximum)


def _checklist_status_value(value: object) -> ChecklistStatusText:
    raw_value = _text_value(value, "UNKNOWN", maximum=MAX_STATUS_LENGTH)
    if raw_value not in CHECKLIST_STATUS_VALUES:
        raise ValueError("ROM-0 operator checklist status is unsupported")
    return cast(ChecklistStatusText, raw_value)


def _checklist_step_status_value(value: object) -> ChecklistStepStatusText:
    raw_value = _text_value(value, "UNKNOWN", maximum=MAX_STATUS_LENGTH)
    if raw_value not in CHECKLIST_STEP_STATUS_VALUES:
        raise ValueError("ROM-0 operator checklist step status is unsupported")
    return cast(ChecklistStepStatusText, raw_value)


def _checklist_step_kind_value(value: object) -> ChecklistStepKindText:
    raw_value = _text_value(value, "UNKNOWN", maximum=MAX_CHECKLIST_STEP_KIND_LENGTH)
    if raw_value not in CHECKLIST_STEP_KIND_VALUES:
        raise ValueError("ROM-0 operator checklist step kind is unsupported")
    return cast(ChecklistStepKindText, raw_value)


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _evidence_statuses(refresh_report: Mapping[str, Any]) -> dict[str, str]:
    raw_inputs = refresh_report.get("evidence_inputs")
    if not isinstance(raw_inputs, list):
        return {}
    statuses: dict[str, str] = {}
    for item in raw_inputs:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        status = item.get("status")
        if isinstance(name, str) and name and isinstance(status, str) and status:
            statuses[name] = _bounded_text(status, maximum=MAX_STATUS_LENGTH)
    return statuses


def _operator_steps(operator_report: Mapping[str, Any]) -> list[GoffyRomChecklistStepOutput]:
    raw_steps = operator_report.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("operator checklist steps must be an array")
    if len(raw_steps) > MAX_CHECKLIST_STEP_COUNT:
        raise ValueError("operator checklist contains too many steps")
    steps: list[GoffyRomChecklistStepOutput] = []
    for index, item in enumerate(raw_steps, start=1):
        if not isinstance(item, Mapping):
            raise ValueError("operator checklist step must be an object")
        blockers = tuple(
            _bounded_text(blocker, maximum=MAX_BLOCKER_LENGTH)
            for blocker in _string_items(item.get("blockers"))
        )
        status = _checklist_step_status_value(item.get("status"))
        steps.append(
            GoffyRomChecklistStepOutput(
                step_index=index,
                title=_text_value(
                    item.get("title"),
                    f"ROM-0 checklist step {index}",
                    maximum=MAX_CHECKLIST_STEP_TITLE_LENGTH,
                ),
                kind=_checklist_step_kind_value(item.get("kind")),
                status=status,
                summary=_text_value(
                    item.get("summary"),
                    "No checklist summary available",
                    maximum=MAX_CHECKLIST_STEP_SUMMARY_LENGTH,
                ),
                blocked=status == "BLOCKED" or bool(blockers),
                blocker_count=len(blockers),
            )
        )
    return steps


def _gate_status_from_evidence(evidence_statuses: Mapping[str, str], name: str) -> str:
    match evidence_statuses.get(name):
        case "LOADED":
            return "READY"
        case "MISSING":
            return "MISSING"
        case "INVALID":
            return "INVALID"
        case _:
            return "MISSING"


def _unlock_gate_status(
    evidence_statuses: Mapping[str, str],
    *,
    refresh_blockers: tuple[str, ...],
) -> str:
    status = _gate_status_from_evidence(evidence_statuses, "unlock_eligibility")
    if status == "READY" and UNLOCK_NOT_ACCEPTED_BLOCKER in refresh_blockers:
        return "BLOCKED"
    return status


def _fastboot_gate_status(
    evidence_statuses: Mapping[str, str],
    *,
    bootloader_status: str,
) -> str:
    if bootloader_status == "MANUAL_BOOTLOADER_VISIBLE":
        return "READY"
    status = _gate_status_from_evidence(evidence_statuses, "fastboot_evidence")
    if status == "READY":
        return "HOST_READY_ONLY"
    return status


def _bounded_text(value: str, *, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in normalized):
        raise ValueError("text contains unsupported control characters")
    if _contains_path_like_text(normalized):
        raise ValueError("text contains unsupported path-like content")
    if any(pattern.search(normalized) for pattern in COMMAND_TEXT_PATTERNS):
        raise ValueError("text contains unsupported command-like content")
    if len(normalized) > maximum:
        return normalized[: maximum - 3].rstrip() + "..."
    return normalized or "unknown"


def _contains_path_like_text(value: str) -> bool:
    if "file://" in value.casefold() or "\\" in value:
        return True
    without_safe_acronyms = SAFE_SLASH_TOKEN.sub("", value)
    return "/" in without_safe_acronyms


def _summary(
    *,
    rom_ready: bool,
    stale_report: bool,
    blocker_count: int,
    refresh_status: str,
) -> str:
    if rom_ready:
        return "ROM-0 is ready for a manual readiness review; destructive actions remain withheld"
    if stale_report:
        return "ROM-0 evidence exists but the refresh report is stale"
    return f"ROM-0 is {refresh_status}; {blocker_count} blocker(s) remain"


def _next_action(
    blockers: tuple[str, ...],
    *,
    stale_report: bool,
    rom_ready: bool,
) -> str:
    if rom_ready:
        return "Review ROM-0 readiness manually before any destructive decision"
    if stale_report:
        return "Regenerate the read-only ROM-0 action packet on the Mac"
    if blockers:
        return blockers[0]
    return "Collect the remaining ROM-0 evidence before any unlock, DSU, or flash decision"
