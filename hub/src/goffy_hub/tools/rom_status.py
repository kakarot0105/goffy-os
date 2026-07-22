from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic.alias_generators import to_camel

from goffy_hub.registry import ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations

TOOL_NAME = "goffy.rom.status"
TOOL_VERSION = "1.0.0"
VALIDATION_DIR = Path(".goffy-validation")
REFRESH_REPORT_FILENAME = "rom-0-refresh-report.json"
OPERATOR_CHECKLIST_FILENAME = "rom-0-operator-checklist.json"
LATEST_REFRESH_SCHEMA = "goffy.rom0-refresh-report.v3"
SUPPORTED_REFRESH_SCHEMAS = frozenset(
    (
        "goffy.rom0-refresh-report.v1",
        "goffy.rom0-refresh-report.v2",
        LATEST_REFRESH_SCHEMA,
    )
)
SUPPORTED_OPERATOR_SCHEMA = "goffy.rom0-operator-checklist.v1"
READY_FOR_ROM0_REVIEW = "READY_FOR_ROM0_READINESS_REVIEW"
MAX_ARTIFACT_BYTES = 64_000
MAX_BLOCKERS = 8
MAX_BLOCKER_LENGTH = 160
MAX_STATUS_LENGTH = 96
MAX_SUMMARY_LENGTH = 192
MAX_NEXT_ACTION_LENGTH = 192
BlockerText = Annotated[str, Field(min_length=1, max_length=MAX_BLOCKER_LENGTH)]


class GoffyRomStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


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
        "next_action",
    )
    @classmethod
    def reject_control_text(cls, value: str) -> str:
        return _bounded_text(value, maximum=max(MAX_SUMMARY_LENGTH, MAX_NEXT_ACTION_LENGTH))

    @field_validator("blockers")
    @classmethod
    def reject_unsafe_blockers(cls, value: list[str]) -> list[str]:
        return [_bounded_text(item, maximum=MAX_BLOCKER_LENGTH) for item in value]


async def read_goffy_rom_status(_request: BaseModel, *, root: Path) -> dict[str, Any]:
    return goffy_rom_status_snapshot(root=root)


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
        rom_ready = (
            refresh_claims_ready
            and refresh_report.get("refresh_succeeded") is True
            and not stale_report
            and refresh_status == READY_FOR_ROM0_REVIEW
            and packet_status == READY_FOR_ROM0_REVIEW
            and checked_operator
            and operator_status == READY_FOR_ROM0_REVIEW
            and operator_ok
            and not blockers
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


def _read_json_mapping(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds ROM status size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("artifact root must be an object")
    return cast(dict[str, Any], value)


def _string_value(value: object, *, default: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    return _bounded_text(value, maximum=MAX_STATUS_LENGTH)


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _bounded_text(value: str, *, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in normalized):
        raise ValueError("text contains unsupported control characters")
    if "file://" in normalized.casefold() or "/" in normalized or "\\" in normalized:
        raise ValueError("text contains unsupported path-like content")
    if len(normalized) > maximum:
        return normalized[: maximum - 3].rstrip() + "..."
    return normalized or "unknown"


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
