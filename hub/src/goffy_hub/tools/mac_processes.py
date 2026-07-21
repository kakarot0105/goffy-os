from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, cast

import psutil
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from goffy_hub.registry import ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations

DEFAULT_PROCESS_ENTRIES = 10
MAX_PROCESS_ENTRIES = 25
MAX_PROCESS_COUNT = 100_000
MAX_PROCESS_NAME_CHARS = 96
MAX_PROCESS_STATUS_CHARS = 32
MAX_PROCESS_PID = 2_147_483_647
MAX_PROCESS_RSS_BYTES = 9_223_372_036_854_775_807


class MacProcessesListInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    max_entries: int = Field(
        default=DEFAULT_PROCESS_ENTRIES,
        ge=1,
        le=MAX_PROCESS_ENTRIES,
    )


class MacProcessEntryOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    pid: int = Field(ge=0, le=MAX_PROCESS_PID)
    name: str = Field(min_length=1, max_length=MAX_PROCESS_NAME_CHARS)
    status: str = Field(min_length=1, max_length=MAX_PROCESS_STATUS_CHARS)
    rss_bytes: int = Field(ge=0, le=MAX_PROCESS_RSS_BYTES)
    create_time_epoch_seconds: int | None = Field(default=None, ge=0)


class MacProcessesListOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    status: str = Field(min_length=1, max_length=64)
    process_count: int = Field(ge=0, le=MAX_PROCESS_COUNT)
    skipped_count: int = Field(ge=0, le=MAX_PROCESS_COUNT)
    truncated: bool
    entries: list[MacProcessEntryOutput] = Field(max_length=MAX_PROCESS_ENTRIES)


@dataclass(frozen=True, slots=True)
class _ProcessSnapshot:
    process_count: int
    skipped_count: int
    truncated: bool
    entries: list[MacProcessEntryOutput]


async def list_mac_processes(request: BaseModel) -> dict[str, Any]:
    if not is_mac_processes_supported():
        raise ValueError("mac.processes.list requires macOS")
    parsed = cast(MacProcessesListInput, request)
    snapshot = await asyncio.to_thread(_process_snapshot, parsed.max_entries)
    return MacProcessesListOutput(
        status="available",
        process_count=snapshot.process_count,
        skipped_count=snapshot.skipped_count,
        truncated=snapshot.truncated,
        entries=snapshot.entries,
    ).model_dump(mode="json", by_alias=True)


async def check_mac_processes_health() -> bool:
    if not is_mac_processes_supported():
        return False
    try:
        return await asyncio.to_thread(lambda: psutil.boot_time() > 0)
    except (OSError, RuntimeError, ValueError):
        return False


def build_mac_processes_list_tool(
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    return ToolDefinition(
        name="mac.processes.list",
        title="Mac running process summary",
        description=(
            "List bounded read-only metadata for running Mac processes without exposing "
            "command lines, executable paths, environment variables, open files, or network data."
        ),
        tool_version="1.0.0",
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=MacProcessesListInput,
        output_model=MacProcessesListOutput,
        handler=list_mac_processes,
        health_probe=check_mac_processes_health,
        health_timeout_seconds=health_timeout_seconds,
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )


def is_mac_processes_supported() -> bool:
    return platform.system() == "Darwin"


def _process_snapshot(max_entries: int) -> _ProcessSnapshot:
    candidates: list[MacProcessEntryOutput] = []
    process_count = 0
    skipped_count = 0
    scan_truncated = False
    errors = (
        psutil.AccessDenied,
        psutil.NoSuchProcess,
        psutil.ZombieProcess,
        OSError,
        RuntimeError,
        ValueError,
    )

    for process in psutil.process_iter(["pid", "name", "status", "memory_info", "create_time"]):
        if process_count >= MAX_PROCESS_COUNT:
            scan_truncated = True
            break
        process_count += 1
        try:
            info = process.info
            candidates.append(_process_entry(info))
        except errors:
            skipped_count += 1

    candidates.sort(key=lambda entry: (-entry.rss_bytes, entry.name.casefold(), entry.pid))
    selected = candidates[:max_entries]
    return _ProcessSnapshot(
        process_count=process_count,
        skipped_count=skipped_count,
        truncated=scan_truncated or len(candidates) > len(selected),
        entries=selected,
    )


def _process_entry(info: dict[str, Any]) -> MacProcessEntryOutput:
    pid = _bounded_int(info.get("pid"), maximum=MAX_PROCESS_PID)
    raw_name = str(info.get("name") or "unknown")
    raw_status = str(info.get("status") or "unknown")
    create_time = info.get("create_time")
    return MacProcessEntryOutput(
        pid=pid,
        name=_bounded_process_name(raw_name),
        status=_bounded_text(raw_status, MAX_PROCESS_STATUS_CHARS),
        rss_bytes=_bounded_int(
            getattr(info.get("memory_info"), "rss", 0),
            maximum=MAX_PROCESS_RSS_BYTES,
        ),
        create_time_epoch_seconds=(
            None
            if create_time is None
            else _bounded_int(create_time, maximum=MAX_PROCESS_RSS_BYTES)
        ),
    )


def _bounded_int(value: object, *, maximum: int) -> int:
    if not isinstance(value, int | float):
        return 0
    if value < 0:
        return 0
    return min(int(value), maximum)


def _bounded_process_name(value: str) -> str:
    # psutil names should be basenames, but strip separators defensively to avoid path leaks.
    if "/" in value or "\\" in value:
        value = PurePath(value.replace("\\", "/")).name
    return _bounded_text(value, MAX_PROCESS_NAME_CHARS)


def _bounded_text(value: str, limit: int) -> str:
    sanitized = "".join(
        " "
        if ord(character) < 0x20
        or ord(character) == 0x7F
        or character
        in {
            "\u202a",
            "\u202b",
            "\u202c",
            "\u202d",
            "\u202e",
            "\u2066",
            "\u2067",
            "\u2068",
            "\u2069",
        }
        else character
        for character in value
    ).strip()
    return sanitized[:limit] or "unknown"
