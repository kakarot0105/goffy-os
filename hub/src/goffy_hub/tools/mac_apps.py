from __future__ import annotations

import asyncio
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from goffy_hub.registry import ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations

DEFAULT_MAC_APP_ENTRIES = 10
MAX_APPROVED_MAC_APPS = 25
MAX_APP_DISPLAY_NAME_CHARS = 80
MAX_APP_BUNDLE_ID_CHARS = 160
MAX_APP_STATUS_CHARS = 64
OPEN_EXECUTABLE = "/usr/bin/open"
OSASCRIPT_EXECUTABLE = "/usr/bin/osascript"
APP_OPEN_REGISTRY_TIMEOUT_MARGIN_SECONDS = 0.25
APP_OPEN_MAX_SUBPROCESS_TIMEOUT_SECONDS = 1.0
APP_OPEN_POLL_SECONDS = 0.2
MIN_MAC_APP_OPEN_TIMEOUT_SECONDS = APP_OPEN_REGISTRY_TIMEOUT_MARGIN_SECONDS + 0.1
_BUNDLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,158}[A-Za-z0-9]$")


@dataclass(frozen=True, slots=True)
class ApprovedMacApp:
    index: int
    display_name: str
    bundle_id: str


class MacAppsListInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    max_entries: int = Field(default=DEFAULT_MAC_APP_ENTRIES, ge=1, le=MAX_APPROVED_MAC_APPS)


class MacAppsOpenInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    display_name: str = Field(min_length=1, max_length=MAX_APP_DISPLAY_NAME_CHARS)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        normalized = value.strip()
        _validate_display_name(normalized)
        return normalized


class MacAppCatalogEntryOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    app_index: int = Field(ge=0, lt=MAX_APPROVED_MAC_APPS)
    display_name: str = Field(min_length=1, max_length=MAX_APP_DISPLAY_NAME_CHARS)
    bundle_id: str = Field(min_length=1, max_length=MAX_APP_BUNDLE_ID_CHARS)


class MacAppsListOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    status: str = Field(min_length=1, max_length=MAX_APP_STATUS_CHARS)
    app_count: int = Field(ge=0, le=MAX_APPROVED_MAC_APPS)
    truncated: bool
    entries: list[MacAppCatalogEntryOutput] = Field(max_length=MAX_APPROVED_MAC_APPS)


class MacAppsOpenOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    status: str = Field(min_length=1, max_length=MAX_APP_STATUS_CHARS)
    display_name: str = Field(min_length=1, max_length=MAX_APP_DISPLAY_NAME_CHARS)
    bundle_id: str = Field(min_length=1, max_length=MAX_APP_BUNDLE_ID_CHARS)
    verified: bool


async def list_mac_apps(
    request: BaseModel,
    approved_apps: tuple[ApprovedMacApp, ...],
) -> dict[str, Any]:
    if not is_mac_apps_supported():
        raise ValueError("mac.apps.list requires macOS")
    parsed = cast(MacAppsListInput, request)
    selected = approved_apps[: parsed.max_entries]
    return MacAppsListOutput(
        status="available",
        app_count=len(approved_apps),
        truncated=len(selected) < len(approved_apps),
        entries=[
            MacAppCatalogEntryOutput(
                app_index=app.index,
                display_name=app.display_name,
                bundle_id=app.bundle_id,
            )
            for app in selected
        ],
    ).model_dump(mode="json", by_alias=True)


async def open_mac_app(
    request: BaseModel,
    approved_apps: tuple[ApprovedMacApp, ...],
    operation_timeout_seconds: float,
) -> dict[str, Any]:
    if not is_mac_apps_supported():
        raise ValueError("mac.apps.open requires macOS")
    if not mac_app_open_supported():
        raise ValueError("mac.apps.open requires macOS Launch Services executables")
    if operation_timeout_seconds <= MIN_MAC_APP_OPEN_TIMEOUT_SECONDS:
        raise ValueError("mac.apps.open requires a larger tool timeout")
    parsed = cast(MacAppsOpenInput, request)
    app = _find_approved_app(parsed.display_name, approved_apps)
    if app is None:
        raise ValueError("mac.apps.open requires an approved display name")
    return await asyncio.to_thread(_open_and_verify_app, app, operation_timeout_seconds)


async def check_mac_apps_health(approved_apps: tuple[ApprovedMacApp, ...]) -> bool:
    return is_mac_apps_supported() and bool(approved_apps)


async def check_mac_apps_open_health(approved_apps: tuple[ApprovedMacApp, ...]) -> bool:
    return is_mac_apps_supported() and bool(approved_apps) and mac_app_open_supported()


def build_mac_apps_list_tool(
    allowlist_entries: tuple[str, ...],
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    approved_apps = _approved_apps(allowlist_entries)

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await list_mac_apps(request, approved_apps)

    async def health_probe() -> bool:
        return await check_mac_apps_health(approved_apps)

    return ToolDefinition(
        name="mac.apps.list",
        title="Mac approved app catalog",
        description=(
            "List explicitly approved Mac applications by display name and bundle identifier "
            "without launching apps, reading installed app folders, or exposing file paths."
        ),
        tool_version="1.0.0",
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=MacAppsListInput,
        output_model=MacAppsListOutput,
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


def build_mac_apps_open_tool(
    allowlist_entries: tuple[str, ...],
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    if timeout_seconds <= MIN_MAC_APP_OPEN_TIMEOUT_SECONDS:
        raise ValueError("mac.apps.open requires a larger tool timeout")
    approved_apps = _approved_apps(allowlist_entries)

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await open_mac_app(request, approved_apps, timeout_seconds)

    async def health_probe() -> bool:
        return await check_mac_apps_open_health(approved_apps)

    return ToolDefinition(
        name="mac.apps.open",
        title="Open approved Mac app",
        description=(
            "Open one explicitly approved Mac application by display name using its fixed bundle "
            "identifier. The tool cannot open files, scan installed app folders, or run shell "
            "commands."
        ),
        tool_version="1.0.0",
        permission=PermissionLevel.CONFIRM,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=MacAppsOpenInput,
        output_model=MacAppsOpenOutput,
        handler=handler,
        health_probe=health_probe,
        health_timeout_seconds=health_timeout_seconds,
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )


def is_mac_apps_supported() -> bool:
    return platform.system() == "Darwin"


def mac_app_open_supported() -> bool:
    return Path(OPEN_EXECUTABLE).is_file() and Path(OSASCRIPT_EXECUTABLE).is_file()


def _approved_apps(entries: tuple[str, ...]) -> tuple[ApprovedMacApp, ...]:
    if not 1 <= len(entries) <= MAX_APPROVED_MAC_APPS:
        raise ValueError(f"mac.apps.list requires 1..{MAX_APPROVED_MAC_APPS} approved apps")

    apps: list[ApprovedMacApp] = []
    display_names: set[str] = set()
    bundle_ids: set[str] = set()
    for index, entry in enumerate(entries):
        display_name, separator, bundle_id = entry.partition("=")
        if separator != "=":
            raise ValueError("GOFFY_MAC_APP_ALLOWLIST entries must use Display Name=bundle.id")
        display_name = display_name.strip()
        bundle_id = bundle_id.strip()
        _validate_display_name(display_name)
        _validate_bundle_id(bundle_id)

        display_key = display_name.casefold()
        bundle_key = bundle_id.casefold()
        if display_key in display_names or bundle_key in bundle_ids:
            raise ValueError("GOFFY_MAC_APP_ALLOWLIST entries must be unique")
        display_names.add(display_key)
        bundle_ids.add(bundle_key)
        apps.append(ApprovedMacApp(index=index, display_name=display_name, bundle_id=bundle_id))
    return tuple(apps)


def _find_approved_app(
    display_name: str,
    approved_apps: tuple[ApprovedMacApp, ...],
) -> ApprovedMacApp | None:
    display_key = display_name.casefold()
    return next(
        (app for app in approved_apps if app.display_name.casefold() == display_key),
        None,
    )


def _open_and_verify_app(
    app: ApprovedMacApp,
    operation_timeout_seconds: float,
) -> dict[str, Any]:
    deadline = (
        time.monotonic() + operation_timeout_seconds - APP_OPEN_REGISTRY_TIMEOUT_MARGIN_SECONDS
    )
    try:
        opened = _run_open_request(app, _remaining_timeout_seconds(deadline))
    except subprocess.TimeoutExpired as error:
        raise ValueError(
            "mac.apps.open launch did not finish before the verification deadline"
        ) from error
    if opened.returncode != 0:
        raise ValueError("mac.apps.open was rejected by Launch Services")

    while time.monotonic() <= deadline:
        if _is_app_running(app.bundle_id, _remaining_timeout_seconds(deadline)):
            return MacAppsOpenOutput(
                status="running",
                display_name=app.display_name,
                bundle_id=app.bundle_id,
                verified=True,
            ).model_dump(mode="json", by_alias=True)
        sleep_seconds = min(APP_OPEN_POLL_SECONDS, max(0.0, deadline - time.monotonic()))
        if sleep_seconds <= 0:
            break
        time.sleep(sleep_seconds)
    raise ValueError("mac.apps.open could not verify the app is running")


def _is_app_running(bundle_id: str, timeout_seconds: float) -> bool:
    try:
        completed = _run_running_check(bundle_id, timeout_seconds)
    except subprocess.TimeoutExpired:
        return False
    returncode = int(getattr(completed, "returncode", 1))
    stdout = str(getattr(completed, "stdout", ""))
    return returncode == 0 and stdout.strip().lower() == "true"


def _run_open_request(app: ApprovedMacApp, timeout_seconds: float) -> Any:
    return subprocess.run(  # noqa: S603 - fixed executable and allowlisted bundle id.
        [OPEN_EXECUTABLE, "-b", app.bundle_id],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _run_running_check(bundle_id: str, timeout_seconds: float) -> Any:
    return subprocess.run(  # noqa: S603 - fixed executable and validated bundle id.
        [
            OSASCRIPT_EXECUTABLE,
            "-e",
            f'application id "{bundle_id}" is running',
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _remaining_timeout_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("mac.apps.open could not verify the app is running")
    return min(remaining, APP_OPEN_MAX_SUBPROCESS_TIMEOUT_SECONDS)


def _validate_display_name(value: str) -> None:
    if not value or len(value) > MAX_APP_DISPLAY_NAME_CHARS:
        raise ValueError("GOFFY_MAC_APP_ALLOWLIST display names must be bounded")
    if "/" in value or "\\" in value:
        raise ValueError("GOFFY_MAC_APP_ALLOWLIST display names must not contain paths")
    if any(_is_unsafe_display_character(character) for character in value):
        raise ValueError("GOFFY_MAC_APP_ALLOWLIST display names contain unsupported characters")


def _validate_bundle_id(value: str) -> None:
    if (
        not value
        or len(value) > MAX_APP_BUNDLE_ID_CHARS
        or "." not in value
        or ".." in value
        or not _BUNDLE_ID.fullmatch(value)
    ):
        raise ValueError("GOFFY_MAC_APP_ALLOWLIST bundle identifiers must be reverse-DNS values")


def _is_unsafe_display_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        codepoint < 0x20
        or codepoint == 0x7F
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
    )
