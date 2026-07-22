from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = ROOT / "protocol" / "python"
if __package__ in {None, ""}:
    for import_root in (ROOT, PROTOCOL_ROOT):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

from scripts.android_preflight import default_sdk_roots, first_existing_path  # noqa: E402
from scripts.setup_doctor import DoctorReport, redact_paths, safe_text  # noqa: E402
from scripts.verify_moto_g_readiness import (  # noqa: E402
    DEBUG_APK_RELATIVE_PATH,
    existing_directory,
)

JSON_SCHEMA_VERSION = "goffy.moto-g-device-smoke.v1"
PACKAGE_NAME = "dev.goffy.os"
MAIN_ACTIVITY = f"{PACKAGE_NAME}/.MainActivity"
HUB_REVERSE_ENDPOINT = "tcp:8787"
DEFAULT_PHONE_COMMAND = "check my battery level"
DEFAULT_MAC_COMMAND = "check my Mac status"
DEFAULT_MAC_PROCESS_COMMAND = "What is running on my Mac"
DEFAULT_MAC_ROM_STATUS_COMMAND = "Show GOFFY ROM status"
DEFAULT_MEMORY_LIST_COMMAND = "what do you remember"
DEFAULT_MEMORY_TEXT_PREFIX = "goffy memory smoke"
DEBUG_HUB_ENDPOINT = "ws://127.0.0.1:8787/ws/v1"
REMOTE_UI_XML = "/sdcard/goffy-device-smoke-window.xml"
MAX_INPUT_TEXT_LENGTH = 120
INPUT_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9 .,_:-]{1,120}$")
DEBUG_HUB_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._-]{24,120}$")
BOUNDS_PATTERN = re.compile(r"\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]")
MAX_LOGCAT_LINES = 200
INITIAL_RESULT_SETTLE_POLLS = 3
SEND_BOTTOM_SAFE_MARGIN_PX = 96
MOTO_G_MODEL_PATTERN = re.compile(r"\bmoto\s*g\b|moto_g", re.IGNORECASE)
DEVICE_SERIAL_PLACEHOLDER = "<device-serial>"
DEBUG_HUB_TOKEN_PLACEHOLDER = "REDACTED_DEBUG_HUB_TOKEN"  # noqa: S105
MAC_SMOKE_MARKERS = {
    DEFAULT_MAC_COMMAND.casefold(): (
        "VERIFIED",
        "Darwin",
        "mac.system_info output matched the registered schema.",
    ),
    DEFAULT_MAC_PROCESS_COMMAND.casefold(): (
        "VERIFIED",
        "MAC PROCESSES",
        "mac.processes.list output matched the registered schema.",
    ),
    DEFAULT_MAC_ROM_STATUS_COMMAND.casefold(): (
        "VERIFIED",
        "GOFFY ROM-0",
        "MAC  /  goffy.rom.status  /  SAFE",
        "goffy.rom.status output matched the registered schema.",
    ),
}
TASK_CARD_STATUS_TEXTS = frozenset(
    {
        "AWAITING APPROVAL",
        "ACCEPTED",
        "BLOCKED",
        "CANCELLED",
        "COMPLETED UNVERIFIED",
        "DENIED",
        "FAILED",
        "PENDING",
        "PREPARING",
        "ROUTING",
        "RUNNING",
        "UNVERIFIED",
        "VERIFIED",
        "VERIFYING",
    }
)
MAX_TASK_CARD_WINDOW_NODES = 30
MOTO_G_PORTRAIT_VIEWPORT_BOUNDS = (0, 0, 720, 1604)
COMMAND_INPUT_REVEAL_SWIPES = (
    ("360", "1450", "360", "650", "450"),
    ("360", "1450", "360", "650", "450"),
    ("360", "1450", "360", "650", "450"),
    ("360", "650", "360", "1450", "450"),
    ("360", "650", "360", "1450", "450"),
)
SEND_REVEAL_SWIPES = (
    ("360", "1450", "360", "650", "450"),
    ("360", "650", "360", "1450", "450"),
    ("360", "1450", "360", "650", "450"),
    ("360", "650", "360", "1450", "450"),
)
DEBUG_HUB_SETUP_REVEAL_SWIPES = (
    ("360", "1450", "360", "650", "450"),
    ("360", "1450", "360", "650", "450"),
    ("360", "1450", "360", "650", "450"),
    ("360", "1450", "360", "650", "450"),
)
TIMELINE_REVEAL_SWIPES = (
    ("360", "1450", "360", "650", "450"),
    ("360", "1450", "360", "650", "450"),
    ("360", "1450", "360", "650", "450"),
)
HOME_TOP_RESTORE_SWIPES = (
    ("360", "650", "360", "1450", "450"),
    ("360", "650", "360", "1450", "450"),
    ("360", "650", "360", "1450", "450"),
    ("360", "650", "360", "1450", "450"),
    ("360", "650", "360", "1450", "450"),
    ("360", "650", "360", "1450", "450"),
    ("360", "650", "360", "1450", "450"),
)
DEVICE_MAP_REVEAL_SWIPES = (("360", "1450", "360", "900", "350"),)
KEYEVENT_BY_INPUT_CHAR = {
    **{chr(code): f"KEYCODE_{chr(code).upper()}" for code in range(ord("a"), ord("z") + 1)},
    **{str(digit): f"KEYCODE_{digit}" for digit in range(10)},
    " ": "KEYCODE_SPACE",
}
HOME_SURFACE_MARKERS = (
    "GOFFY title",
    "GOFFY LITE",
    "SETTINGS",
    "GOFFY orb state",
    "LOOP phase",
    "MAC LINK",
    "EXECUTION TARGET",
    "DOCK MODE",
    "HOME SHELL",
    "HOME status",
    "HOME CHECK",
    "DEVICE MAP",
)
DEVICE_MAP_SURFACE_MARKERS = (
    "PHONE ENGINE",
    "MAC HUB",
    "MCP REGISTRY",
    "LOCAL MODEL",
    "CLOUD",
)


class StepStatus(StrEnum):
    PLANNED = "PLANNED"
    OK = "OK"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class DeviceSmokeStep:
    name: str
    status: StepStatus
    command: tuple[str, ...] = ()
    mutates_device: bool = False
    detail: str = ""
    remediation: str = ""
    artifact: str | None = None


@dataclass(frozen=True)
class UiNode:
    text: str
    content_desc: str
    class_name: str
    bounds: tuple[int, int, int, int]
    enabled: bool
    clickable: bool
    password: bool
    focused: bool

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
        return ((left + right) // 2, (top + bottom) // 2)


@dataclass(frozen=True)
class DeviceTarget:
    serial: str
    model: str


@dataclass(frozen=True)
class DeviceSmokeReport:
    executed: bool
    ok: bool
    output_directory: str | None
    phone_command: str
    mac_command: str | None
    steps: tuple[DeviceSmokeStep, ...]
    repo_root: Path = ROOT
    home: Path = Path.home()


CommandRunner = Callable[[Sequence[str], Path, int], CommandResult]


def default_command_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
    try:
        completed = subprocess.run(  # noqa: S603
            list(command),
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(124, stdout, stderr, timed_out=True)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def trusted_adb_path(env: Mapping[str, str] = os.environ) -> Path | None:
    sdk_root = first_existing_path(default_sdk_roots(env))
    if sdk_root is None:
        return None
    adb_name = "adb.exe" if platform.system() == "Windows" else "adb"
    adb = (sdk_root / "platform-tools" / adb_name).expanduser().resolve()
    if not adb.is_file() or not os.access(adb, os.X_OK):
        return None
    return adb


def adb_command(adb: Path, target: DeviceTarget, *args: str) -> tuple[str, ...]:
    return (str(adb), "-s", target.serial, *args)


def display_adb_command(adb: Path, *args: str) -> tuple[str, ...]:
    return (str(adb), "-s", DEVICE_SERIAL_PLACEHOLDER, *args)


def default_memory_smoke_text() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d %H%M%S %f")
    return f"{DEFAULT_MEMORY_TEXT_PREFIX} {timestamp}"


def memory_remember_command(memory_text: str) -> str:
    return f"remember that {memory_text}"


def planned_steps(
    root: Path,
    adb: Path | None,
    *,
    include_mac: bool,
    include_memory: bool,
    phone_command: str,
    mac_command: str,
    memory_text: str,
    memory_remember_command: str,
    debug_hub_token_file: Path | None,
) -> tuple[DeviceSmokeStep, ...]:
    adb_path = adb or Path("<adb>")
    apk = root / DEBUG_APK_RELATIVE_PATH
    steps = [
        DeviceSmokeStep(
            name="Configure Hub USB reverse",
            status=StepStatus.PLANNED,
            command=(
                str(adb_path),
                "-s",
                DEVICE_SERIAL_PLACEHOLDER,
                "reverse",
                HUB_REVERSE_ENDPOINT,
                HUB_REVERSE_ENDPOINT,
            ),
            mutates_device=True,
            detail="would map phone tcp:8787 to local Hub tcp:8787",
        ),
        DeviceSmokeStep(
            name="Install debug APK",
            status=StepStatus.PLANNED,
            command=(str(adb_path), "-s", DEVICE_SERIAL_PLACEHOLDER, "install", "-r", str(apk)),
            mutates_device=True,
            detail="would install or replace the GOFFY debug APK",
        ),
        DeviceSmokeStep(
            name="Launch GOFFY",
            status=StepStatus.PLANNED,
            command=(
                str(adb_path),
                "-s",
                DEVICE_SERIAL_PLACEHOLDER,
                "shell",
                "am",
                "start",
                "-W",
                "-n",
                MAIN_ACTIVITY,
            ),
            mutates_device=True,
            detail="would start the GOFFY launcher activity",
        ),
        DeviceSmokeStep(
            name="Restore HOME top viewport",
            status=StepStatus.PLANNED,
            mutates_device=True,
            detail="would restore the top HOME viewport before launch marker verification",
        ),
        DeviceSmokeStep(
            name="HOME surface smoke",
            status=StepStatus.PLANNED,
            detail=(
                "would verify the idle GOFFY HOME shell, orb, device-map entry, "
                "HOME setup card, Settings escape hatch, and visible "
                "connection/target indicators"
            ),
        ),
        DeviceSmokeStep(
            name="Device map viewport smoke",
            status=StepStatus.PLANNED,
            mutates_device=True,
            detail="would reveal and verify the read-only device-map node labels",
        ),
        DeviceSmokeStep(
            name="PHONE command smoke",
            status=StepStatus.PLANNED,
            mutates_device=True,
            detail=f"would submit `{phone_command}` and verify phone.battery.status",
        ),
    ]
    if include_memory:
        steps.extend(
            [
                DeviceSmokeStep(
                    name="PHONE memory remember smoke",
                    status=StepStatus.PLANNED,
                    mutates_device=True,
                    detail=(
                        f"would submit `{memory_remember_command}`, tap the matching "
                        "approval, and verify phone.memory.remember"
                    ),
                ),
                DeviceSmokeStep(
                    name="Restore HOME top viewport before memory list",
                    status=StepStatus.PLANNED,
                    mutates_device=True,
                    detail="would restore the command surface before listing memories",
                ),
                DeviceSmokeStep(
                    name="PHONE memory list smoke",
                    status=StepStatus.PLANNED,
                    mutates_device=True,
                    detail=(
                        f"would submit `{DEFAULT_MEMORY_LIST_COMMAND}` and verify the "
                        f"newest `{memory_text}` memory is visible without deleting "
                        "existing memories"
                    ),
                ),
            ]
        )
    if include_mac:
        if debug_hub_token_file is not None:
            steps.append(
                DeviceSmokeStep(
                    name="Configure debug Hub link",
                    status=StepStatus.PLANNED,
                    mutates_device=True,
                    detail=(
                        "would type a redacted token from .goffy-validation and tap "
                        "`Debug link` for the fixed localhost Hub endpoint"
                    ),
                )
            )
        steps.append(
            DeviceSmokeStep(
                name="MAC command smoke",
                status=StepStatus.PLANNED,
                mutates_device=True,
                detail=f"would submit `{mac_command}` and verify {mac_tool_for_smoke(mac_command)}",
            )
        )
    steps.extend(
        [
            DeviceSmokeStep(
                name="Capture screenshot",
                status=StepStatus.PLANNED,
                command=display_adb_command(adb_path, "exec-out", "screencap", "-p"),
                detail="would save final phone screenshot under .goffy-validation",
            ),
            DeviceSmokeStep(
                name="Capture bounded app logcat",
                status=StepStatus.PLANNED,
                command=display_adb_command(
                    adb_path,
                    "logcat",
                    "-d",
                    "--pid",
                    "<goffy-pid>",
                    "-t",
                    "200",
                ),
                detail="would save only bounded GOFFY process logs when pid is available",
            ),
        ]
    )
    return tuple(steps)


def build_report(
    *,
    root: Path = ROOT,
    execute: bool = False,
    confirm_device_mutation: bool = False,
    include_mac: bool = False,
    include_memory: bool = False,
    phone_command: str = DEFAULT_PHONE_COMMAND,
    mac_command: str = DEFAULT_MAC_COMMAND,
    runner: CommandRunner = default_command_runner,
    timeout_seconds: int = 30,
    wait_timeout_seconds: int = 20,
    output_directory: Path | None = None,
    trusted_root: Path = ROOT,
    device_serial: str | None = None,
    debug_hub_token_file: Path | None = None,
    memory_text: str | None = None,
) -> DeviceSmokeReport:
    resolved_root = root.resolve()
    adb = trusted_adb_path()
    resolved_memory_text = memory_text or default_memory_smoke_text()
    remember_command = memory_remember_command(resolved_memory_text)
    if not execute:
        return DeviceSmokeReport(
            executed=False,
            ok=True,
            output_directory=None,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=planned_steps(
                resolved_root,
                adb,
                include_mac=include_mac,
                include_memory=include_memory,
                phone_command=phone_command,
                mac_command=mac_command,
                memory_text=resolved_memory_text,
                memory_remember_command=remember_command,
                debug_hub_token_file=debug_hub_token_file,
            ),
            repo_root=resolved_root,
        )

    blockers = execution_blockers(
        root=resolved_root,
        adb=adb,
        confirm_device_mutation=confirm_device_mutation,
        include_mac=include_mac,
        include_memory=include_memory,
        phone_command=phone_command,
        mac_command=mac_command,
        memory_text=resolved_memory_text,
        memory_remember_command=remember_command,
        trusted_root=trusted_root,
        debug_hub_token_file=debug_hub_token_file,
    )
    if blockers:
        return DeviceSmokeReport(
            executed=False,
            ok=False,
            output_directory=None,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=tuple(
                DeviceSmokeStep(
                    name="Execution gate",
                    status=StepStatus.FAIL,
                    detail=blocker,
                    remediation="Resolve the gate before mutating the connected phone.",
                )
                for blocker in blockers
            ),
            repo_root=resolved_root,
        )

    if adb is None:
        return DeviceSmokeReport(
            executed=False,
            ok=False,
            output_directory=None,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=(
                DeviceSmokeStep(
                    name="Execution gate",
                    status=StepStatus.FAIL,
                    detail="trusted SDK adb executable disappeared after gate check",
                    remediation="Rerun Android setup diagnostics and retry.",
                ),
            ),
            repo_root=resolved_root,
        )

    target, target_step = resolve_device_target(
        adb=adb,
        root=resolved_root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        requested_serial=device_serial,
    )
    if target is None:
        return DeviceSmokeReport(
            executed=False,
            ok=False,
            output_directory=None,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=(target_step,),
            repo_root=resolved_root,
        )

    artifacts = output_directory or default_output_directory(resolved_root)
    artifacts.mkdir(parents=True, exist_ok=True)
    steps: list[DeviceSmokeStep] = [target_step]
    steps.extend(run_setup_steps(resolved_root, adb, target, runner, timeout_seconds))
    if not all(step.status is StepStatus.OK for step in steps):
        return executed_report(
            root=resolved_root,
            output_directory=artifacts,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=steps,
        )

    steps.extend(run_launch_steps(resolved_root, adb, target, runner, timeout_seconds))
    if include_mac and debug_hub_token_file is not None:
        configure_debug_hub = configure_debug_hub_link(
            adb=adb,
            target=target,
            root=resolved_root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            token_file=debug_hub_token_file,
            output_directory=artifacts,
        )
        steps.append(configure_debug_hub)
        if configure_debug_hub.status is StepStatus.FAIL:
            return executed_report(
                root=resolved_root,
                output_directory=artifacts,
                phone_command=phone_command,
                mac_command=mac_command if include_mac else None,
                steps=steps,
            )
    collapse_setup = collapse_setup_card_if_expanded(
        adb=adb,
        target=target,
        root=resolved_root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    steps.append(collapse_setup)
    if collapse_setup.status is StepStatus.FAIL:
        return executed_report(
            root=resolved_root,
            output_directory=artifacts,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=steps,
        )

    restore_home = restore_home_top_viewport(
        adb=adb,
        target=target,
        root=resolved_root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        output_directory=artifacts,
    )
    steps.append(restore_home)
    if restore_home.status is StepStatus.FAIL:
        return executed_report(
            root=resolved_root,
            output_directory=artifacts,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=steps,
        )

    ui_after_launch = dump_ui(
        adb=adb,
        target=target,
        root=resolved_root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        artifact_path=artifacts / "after-launch.xml",
    )
    steps.append(ui_after_launch)
    if ui_after_launch.status is not StepStatus.OK:
        return executed_report(
            root=resolved_root,
            output_directory=artifacts,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=steps,
        )

    home_surface = verify_home_surface(
        ui_xml=(artifacts / "after-launch.xml").read_text(encoding="utf-8"),
        output_directory=artifacts,
    )
    steps.append(home_surface)
    if home_surface.status is not StepStatus.OK:
        return executed_report(
            root=resolved_root,
            output_directory=artifacts,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=steps,
        )

    device_map_steps = reveal_and_verify_device_map_surface(
        adb=adb,
        target=target,
        root=resolved_root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        output_directory=artifacts,
    )
    steps.extend(device_map_steps)
    if not device_map_steps or device_map_steps[-1].status is not StepStatus.OK:
        return executed_report(
            root=resolved_root,
            output_directory=artifacts,
            phone_command=phone_command,
            mac_command=mac_command if include_mac else None,
            steps=steps,
        )

    steps.append(
        submit_and_verify_command(
            adb=adb,
            target=target,
            root=resolved_root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            command=phone_command,
            expected_markers=("VERIFIED", "%"),
            step_name="PHONE command smoke",
            artifact_prefix="phone-command",
            output_directory=artifacts,
        )
    )
    if include_memory and steps[-1].status is StepStatus.OK:
        steps.append(
            submit_and_verify_command(
                adb=adb,
                target=target,
                root=resolved_root,
                runner=runner,
                timeout_seconds=timeout_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                command=remember_command,
                expected_markers=(
                    "VERIFIED",
                    "MEMORY SAVED",
                    "phone.memory.remember",
                    resolved_memory_text,
                ),
                approval_markers=("APPROVAL REQUIRED", "Approve remembering this locally"),
                approval_button_text="Approve once",
                step_name="PHONE memory remember smoke",
                artifact_prefix="phone-memory-remember",
                output_directory=artifacts,
            )
        )
        if steps[-1].status is StepStatus.OK:
            restore_for_memory_list = restore_home_top_viewport(
                adb=adb,
                target=target,
                root=resolved_root,
                runner=runner,
                timeout_seconds=timeout_seconds,
                output_directory=artifacts,
                step_name="Restore HOME top viewport before memory list",
                success_detail="restored command surface before memory list smoke",
            )
            steps.append(restore_for_memory_list)
        if steps[-1].status is StepStatus.OK:
            steps.append(
                submit_and_verify_command(
                    adb=adb,
                    target=target,
                    root=resolved_root,
                    runner=runner,
                    timeout_seconds=timeout_seconds,
                    wait_timeout_seconds=wait_timeout_seconds,
                    command=DEFAULT_MEMORY_LIST_COMMAND,
                    expected_markers=(
                        "VERIFIED",
                        "MEMORIES",
                        "phone.memory.list",
                        resolved_memory_text,
                    ),
                    step_name="PHONE memory list smoke",
                    artifact_prefix="phone-memory-list",
                    output_directory=artifacts,
                )
            )
        elif steps[-1].name == "Restore HOME top viewport before memory list":
            steps.append(
                DeviceSmokeStep(
                    name="PHONE memory list smoke",
                    status=StepStatus.SKIP,
                    detail="skipped because command surface restore failed",
                )
            )
    elif include_memory:
        steps.extend(
            [
                DeviceSmokeStep(
                    name="PHONE memory remember smoke",
                    status=StepStatus.SKIP,
                    detail="skipped because PHONE command smoke failed",
                ),
                DeviceSmokeStep(
                    name="Restore HOME top viewport before memory list",
                    status=StepStatus.SKIP,
                    detail="skipped because PHONE command smoke failed",
                ),
                DeviceSmokeStep(
                    name="PHONE memory list smoke",
                    status=StepStatus.SKIP,
                    detail="skipped because PHONE command smoke failed",
                ),
            ]
        )
    if include_mac and steps[-1].status is StepStatus.OK:
        steps.append(
            submit_and_verify_command(
                adb=adb,
                target=target,
                root=resolved_root,
                runner=runner,
                timeout_seconds=timeout_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                command=mac_command,
                expected_markers=mac_smoke_markers(mac_command),
                step_name="MAC command smoke",
                artifact_prefix="mac-command",
                output_directory=artifacts,
            )
        )
    elif include_mac:
        steps.append(
            DeviceSmokeStep(
                name="MAC command smoke",
                status=StepStatus.SKIP,
                detail="skipped because PHONE command smoke failed",
            )
        )

    steps.append(
        capture_screenshot(
            adb=adb,
            target=target,
            root=resolved_root,
            timeout_seconds=timeout_seconds,
            output_path=artifacts / "final.png",
        )
    )
    steps.append(
        capture_app_logcat(
            adb=adb,
            target=target,
            root=resolved_root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            output_path=artifacts / "goffy-logcat.txt",
        )
    )
    return executed_report(
        root=resolved_root,
        output_directory=artifacts,
        phone_command=phone_command,
        mac_command=mac_command if include_mac else None,
        steps=steps,
    )


def execution_blockers(
    *,
    root: Path,
    adb: Path | None,
    confirm_device_mutation: bool,
    include_mac: bool,
    include_memory: bool,
    phone_command: str,
    mac_command: str,
    memory_text: str,
    memory_remember_command: str,
    trusted_root: Path,
    debug_hub_token_file: Path | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not confirm_device_mutation:
        blockers.append("missing explicit --confirm-device-mutation")
    if phone_command != DEFAULT_PHONE_COMMAND:
        blockers.append("execute mode only supports the fixed PHONE smoke command")
    if include_memory:
        if not INPUT_TEXT_PATTERN.fullmatch(memory_text):
            blockers.append("generated memory smoke text contains unsupported characters")
        if not INPUT_TEXT_PATTERN.fullmatch(memory_remember_command):
            blockers.append("generated memory smoke command contains unsupported characters")
        if memory_remember_command == DEFAULT_MEMORY_LIST_COMMAND:
            blockers.append("memory smoke commands must stay distinct")
    if include_mac and mac_command.casefold() not in MAC_SMOKE_MARKERS:
        blockers.append("execute mode only supports the fixed MAC smoke commands")
    if root.resolve() != trusted_root.resolve():
        blockers.append(
            "repo-root/mutating mode only supports the checked-out GOFFY repository root"
        )
    if debug_hub_token_file is not None:
        if not include_mac:
            blockers.append("debug Hub token file is only supported with --include-mac")
        token_file = resolve_debug_hub_token_file(root, debug_hub_token_file)
        validation_root = (root / ".goffy-validation").resolve()
        if not token_file.is_relative_to(validation_root):
            blockers.append("debug Hub token file must live under .goffy-validation")
        elif not token_file.is_file():
            blockers.append("debug Hub token file missing")
        elif token_file.stat().st_size > 256:
            blockers.append("debug Hub token file is too large for bounded ADB entry")
    if adb is None:
        blockers.append("device/trusted SDK adb executable")
    apk = root / DEBUG_APK_RELATIVE_PATH
    if not apk.is_file():
        blockers.append("android/debug APK missing")
    return tuple(blockers)


def mac_smoke_markers(command: str) -> tuple[str, ...]:
    return MAC_SMOKE_MARKERS.get(
        command.casefold(), MAC_SMOKE_MARKERS[DEFAULT_MAC_COMMAND.casefold()]
    )


def mac_tool_for_smoke(command: str) -> str:
    normalized = command.casefold()
    if normalized == DEFAULT_MAC_PROCESS_COMMAND.casefold():
        return "mac.processes.list"
    if normalized == DEFAULT_MAC_ROM_STATUS_COMMAND.casefold():
        return "goffy.rom.status"
    return "mac.system_info"


def resolve_debug_hub_token_file(root: Path, token_file: Path) -> Path:
    candidate = token_file if token_file.is_absolute() else root / token_file
    return candidate.expanduser().resolve()


def resolve_device_target(
    *,
    adb: Path,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    requested_serial: str | None,
) -> tuple[DeviceTarget | None, DeviceSmokeStep]:
    devices = runner((str(adb), "devices", "-l"), root, timeout_seconds)
    display = (str(adb), "devices", "-l")
    if devices.exit_code != 0:
        return None, DeviceSmokeStep(
            name="Verify Moto G target",
            status=StepStatus.FAIL,
            command=display,
            detail="adb devices failed",
            remediation="Reconnect the Moto G and approve USB debugging.",
        )

    authorized = parse_authorized_devices(devices.stdout)
    if requested_serial is not None:
        selected = next(
            (device for device in authorized if device["serial"] == requested_serial), None
        )
        if selected is None:
            return None, DeviceSmokeStep(
                name="Verify Moto G target",
                status=StepStatus.FAIL,
                command=display,
                detail="requested device serial is not connected and authorized",
                remediation=(
                    "Reconnect the requested Moto G or omit --device-serial with one device."
                ),
            )
    elif len(authorized) != 1:
        detail = "no authorized Android device" if not authorized else "multiple authorized devices"
        return None, DeviceSmokeStep(
            name="Verify Moto G target",
            status=StepStatus.FAIL,
            command=display,
            detail=detail,
            remediation="Connect exactly one Moto G or pass --device-serial.",
        )
    else:
        selected = authorized[0]

    serial = selected["serial"]
    listed_model = selected.get("model", "")
    model_command = adb_command(
        adb, DeviceTarget(serial=serial, model=listed_model), "shell", "getprop", "ro.product.model"
    )
    model_result = runner(model_command, root, timeout_seconds)
    prop_model = model_result.stdout.strip() if model_result.exit_code == 0 else ""
    model = prop_model or listed_model
    if not is_moto_g_model(model) and not is_moto_g_model(listed_model):
        return None, DeviceSmokeStep(
            name="Verify Moto G target",
            status=StepStatus.FAIL,
            command=display_adb_command(adb, "shell", "getprop", "ro.product.model"),
            detail="connected device is not the approved Moto G target",
            remediation="Use the dedicated Moto G or pass the correct --device-serial.",
        )

    return DeviceTarget(serial=serial, model=model), DeviceSmokeStep(
        name="Verify Moto G target",
        status=StepStatus.OK,
        command=display_adb_command(adb, "shell", "getprop", "ro.product.model"),
        detail=f"verified Moto G target model: {model or listed_model}",
    )


def parse_authorized_devices(stdout: str) -> tuple[dict[str, str], ...]:
    devices: list[dict[str, str]] = []
    for line in stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        attrs: dict[str, str] = {"serial": parts[0]}
        for part in parts[2:]:
            key, separator, value = part.partition(":")
            if separator:
                attrs[key] = value
        devices.append(attrs)
    return tuple(devices)


def is_moto_g_model(model: str) -> bool:
    return MOTO_G_MODEL_PATTERN.search(model.replace("_", " ")) is not None


def run_setup_steps(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> list[DeviceSmokeStep]:
    apk = root / DEBUG_APK_RELATIVE_PATH
    return [
        execute_step(
            name="Configure Hub USB reverse",
            command=adb_command(adb, target, "reverse", HUB_REVERSE_ENDPOINT, HUB_REVERSE_ENDPOINT),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "reverse",
                HUB_REVERSE_ENDPOINT,
                HUB_REVERSE_ENDPOINT,
            ),
        ),
        execute_step(
            name="Install debug APK",
            command=adb_command(adb, target, "install", "-r", str(apk)),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(adb, "install", "-r", str(apk)),
        ),
    ]


def run_launch_steps(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> list[DeviceSmokeStep]:
    return [
        execute_step(
            name="Stop GOFFY",
            command=adb_command(adb, target, "shell", "am", "force-stop", PACKAGE_NAME),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(adb, "shell", "am", "force-stop", PACKAGE_NAME),
        ),
        execute_step(
            name="Launch GOFFY",
            command=adb_command(adb, target, "shell", "am", "start", "-W", "-n", MAIN_ACTIVITY),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "am",
                "start",
                "-W",
                "-n",
                MAIN_ACTIVITY,
            ),
        ),
    ]


def collapse_setup_card_if_expanded(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    ui_text = latest_ui_text(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    if find_command_field(ui_text) is not None and not setup_card_expanded(ui_text):
        return DeviceSmokeStep(
            name="Collapse Hub setup card",
            status=StepStatus.SKIP,
            detail="Hub setup card was already collapsed",
        )
    for attempt in range(4):
        hide = find_node(ui_text, text="Hide")
        if hide is not None:
            step = tap_center(
                adb,
                target,
                root,
                runner,
                timeout_seconds,
                hide,
                step_name="Collapse Hub setup card",
            )
            if step.status is StepStatus.OK:
                time.sleep(1)
                after_tap = latest_ui_text(
                    adb=adb,
                    target=target,
                    root=root,
                    runner=runner,
                    timeout_seconds=timeout_seconds,
                )
                if find_node(after_tap, text="Hide") is None:
                    return step
                return DeviceSmokeStep(
                    name="Collapse Hub setup card",
                    status=StepStatus.FAIL,
                    mutates_device=True,
                    detail="Hub setup card still exposed `Hide` after tapping it",
                    remediation="Inspect the UI XML and confirm the Hub setup toggle collapsed.",
                )
            return step
        if attempt == 3:
            break
        reveal = execute_step(
            name="Collapse Hub setup card: Reveal setup toggle",
            command=adb_command(
                adb,
                target,
                "shell",
                "input",
                "swipe",
                "360",
                "1450",
                "360",
                "650",
                "450",
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                "360",
                "1450",
                "360",
                "650",
                "450",
            ),
        )
        if reveal.status is not StepStatus.OK:
            return reveal
        time.sleep(1)
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
    if setup_card_expanded(ui_text):
        return DeviceSmokeStep(
            name="Collapse Hub setup card",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="Hub setup card remained expanded but `Hide` was not tappable",
            remediation="Inspect the UI XML and adjust bounded setup-card collapse logic.",
        )
    return DeviceSmokeStep(
        name="Collapse Hub setup card",
        status=StepStatus.SKIP,
        mutates_device=True,
        detail="Hub setup card was already collapsed or not found after bounded scan",
    )


def setup_card_expanded(xml_text: str) -> bool:
    nodes = nodes_from_xml(xml_text)
    has_endpoint = any(node.text == DEBUG_HUB_ENDPOINT for node in nodes)
    has_secret_field = any(node.password for node in nodes)
    has_pairing_label = any(
        node.text in {"Pairing bundle JSON", "Development bearer token"} for node in nodes
    )
    return has_endpoint or has_secret_field or has_pairing_label


def restore_home_top_viewport(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    output_directory: Path,
    step_name: str = "Restore HOME top viewport",
    success_detail: str = "restored launch viewport before HOME smoke",
) -> DeviceSmokeStep:
    for start_x, start_y, end_x, end_y, duration_ms in HOME_TOP_RESTORE_SWIPES:
        step = execute_step(
            name=step_name,
            command=adb_command(
                adb,
                target,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
        )
        if step.status is not StepStatus.OK:
            return step
        time.sleep(0.4)
    ui_text = latest_ui_text(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    visible_nodes = visible_nodes_from_xml(
        ui_text,
        viewport_bounds=MOTO_G_PORTRAIT_VIEWPORT_BOUNDS,
    )
    if has_exact_text(visible_nodes, "GOFFY"):
        return DeviceSmokeStep(
            name=step_name,
            status=StepStatus.OK,
            mutates_device=True,
            detail=success_detail,
        )
    artifact = "restore-home-top.xml"
    if ui_text.strip():
        (output_directory / artifact).write_text(ui_text, encoding="utf-8")
    return DeviceSmokeStep(
        name=step_name,
        status=StepStatus.FAIL,
        mutates_device=True,
        detail="GOFFY title was not visible after bounded top-restore swipes",
        remediation="Inspect restore-home-top.xml and adjust bounded viewport restore logic.",
        artifact=artifact,
    )


def configure_debug_hub_link(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    token_file: Path,
    output_directory: Path,
) -> DeviceSmokeStep:
    token, token_error = read_debug_hub_token(root, token_file)
    if token_error is not None:
        return token_error

    ui_text = latest_ui_text(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    for attempt in range(len(DEBUG_HUB_SETUP_REVEAL_SWIPES) + 1):
        if DEBUG_HUB_ENDPOINT in ui_text and "Development bearer token" in ui_text:
            break
        edit = find_node(ui_text, text="Edit")
        if edit is not None:
            tap_edit = tap_center(
                adb,
                target,
                root,
                runner,
                timeout_seconds,
                edit,
                step_name="Configure debug Hub link: Open setup",
            )
            if tap_edit.status is not StepStatus.OK:
                return tap_edit
            time.sleep(1)
            ui_text = latest_ui_text(
                adb=adb,
                target=target,
                root=root,
                runner=runner,
                timeout_seconds=timeout_seconds,
            )
            continue
        if attempt == len(DEBUG_HUB_SETUP_REVEAL_SWIPES):
            break
        start_x, start_y, end_x, end_y, duration_ms = DEBUG_HUB_SETUP_REVEAL_SWIPES[attempt]
        reveal = execute_step(
            name="Configure debug Hub link: Reveal setup card",
            command=adb_command(
                adb,
                target,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
        )
        if reveal.status is not StepStatus.OK:
            return reveal
        time.sleep(1)
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )

    if DEBUG_HUB_ENDPOINT not in ui_text or "Development bearer token" not in ui_text:
        write_debug_hub_link_artifact(output_directory, ui_text, token)
        return DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="debug Hub setup fields were not visible",
            remediation="Launch GOFFY debug APK and confirm the Hub setup card is available.",
            artifact="debug-hub-link.xml",
        )

    token_field = find_debug_token_field(ui_text)
    if token_field is None:
        write_debug_hub_link_artifact(output_directory, ui_text, token)
        return DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="development bearer token input field not found",
            remediation="Check the saved UI XML for Compose hierarchy changes.",
            artifact="debug-hub-link.xml",
        )

    focused_token_field = None
    focus_ui_text = ui_text
    for attempt in range(3):
        if attempt == 2:
            tap_token = tap_center(
                adb,
                target,
                root,
                runner,
                timeout_seconds,
                token_field,
                step_name="Configure debug Hub link: Focus token input",
            )
        else:
            tap_token = tap_text_field_entry_area(
                adb,
                target,
                root,
                runner,
                timeout_seconds,
                token_field,
                step_name="Configure debug Hub link: Focus token input",
            )
        if tap_token.status is not StepStatus.OK:
            return tap_token
        time.sleep(1)
        focus_ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        focused_token_field = find_focused_debug_token_field(focus_ui_text)
        if focused_token_field is not None:
            break
    if focused_token_field is None:
        write_debug_hub_link_artifact(output_directory, focus_ui_text, token)
        return DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="development bearer token input did not receive focus",
            remediation="Inspect debug-hub-link.xml and adjust the bounded token-field tap target.",
            artifact="debug-hub-link.xml",
        )

    typed = execute_step(
        name="Configure debug Hub link: Type token",
        command=adb_command(adb, target, "shell", "input", "text", token),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(
            adb,
            "shell",
            "input",
            "text",
            DEBUG_HUB_TOKEN_PLACEHOLDER,
        ),
    )
    if typed.status is not StepStatus.OK:
        return typed

    hidden_keyboard = execute_step(
        name="Configure debug Hub link: Hide keyboard",
        command=adb_command(adb, target, "shell", "input", "keyevent", "BACK"),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(adb, "shell", "input", "keyevent", "BACK"),
    )
    if hidden_keyboard.status is not StepStatus.OK:
        return hidden_keyboard
    time.sleep(1)

    debug_link = None
    debug_link_label_seen = False
    for attempt in range(3):
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        debug_link_label_seen = (
            debug_link_label_seen
            or find_node(
                ui_text,
                text="Debug link",
            )
            is not None
        )
        debug_link = find_enabled_action_for_text(ui_text, text="Debug link")
        if debug_link is not None:
            break
        if attempt == 2:
            break
        scroll = execute_step(
            name="Configure debug Hub link: Reveal Debug link",
            command=adb_command(
                adb, target, "shell", "input", "swipe", "360", "1500", "360", "900", "500"
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                "360",
                "1500",
                "360",
                "900",
                "500",
            ),
        )
        if scroll.status is not StepStatus.OK:
            return scroll
        time.sleep(1)

    if debug_link is None:
        write_debug_hub_link_artifact(output_directory, ui_text, token)
        if token_in_unmasked_edit_text(ui_text, token):
            detail = "development token was entered into a non-password field"
            remediation = (
                "Inspect debug-hub-link.xml; token focus was not on the development bearer field."
            )
        elif debug_link_label_seen:
            detail = "Debug link button stayed disabled after token entry"
            remediation = (
                "Verify the development bearer token field accepted input and matches the Hub."
            )
        else:
            detail = "Debug link button was not visible after bounded scroll"
            remediation = "Check the saved UI XML for setup-card layout changes."
        return DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail=detail,
            remediation=remediation,
            artifact="debug-hub-link.xml",
        )

    tapped_debug = tap_center(
        adb,
        target,
        root,
        runner,
        timeout_seconds,
        debug_link,
        step_name="Configure debug Hub link: Tap Debug link",
    )
    if tapped_debug.status is not StepStatus.OK:
        return tapped_debug
    time.sleep(1)

    ui_text = latest_ui_text(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    write_debug_hub_link_artifact(output_directory, ui_text, token)
    if DEBUG_HUB_ENDPOINT in ui_text and "NOT CONFIGURED" not in ui_text:
        return DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.OK,
            mutates_device=True,
            detail="configured fixed localhost debug Hub link with a redacted token",
            artifact="debug-hub-link.xml",
        )

    return DeviceSmokeStep(
        name="Configure debug Hub link",
        status=StepStatus.FAIL,
        mutates_device=True,
        detail="debug Hub link did not become configured after tapping Debug link",
        remediation="Verify the token matches the running Hub and inspect the saved UI XML.",
        artifact="debug-hub-link.xml",
    )


def write_debug_hub_link_artifact(output_directory: Path, ui_text: str, token: str) -> None:
    safe_ui_text = ui_text.replace(token, DEBUG_HUB_TOKEN_PLACEHOLDER)
    (output_directory / "debug-hub-link.xml").write_text(safe_ui_text, encoding="utf-8")


def read_debug_hub_token(root: Path, token_file: Path) -> tuple[str, DeviceSmokeStep | None]:
    resolved = resolve_debug_hub_token_file(root, token_file)
    try:
        token = resolved.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "", DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="debug Hub token file could not be read",
            remediation="Create the token file under .goffy-validation and retry.",
        )
    if DEBUG_HUB_TOKEN_PATTERN.fullmatch(token) is None:
        return "", DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail=(
                "debug Hub token must be 24..120 chars using only A-Z, a-z, 0-9, "
                "dot, underscore, or dash"
            ),
            remediation=(
                "Use a short-lived ADB-safe development token; do not use a production secret."
            ),
        )
    return token, None


def submit_and_verify_command(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    wait_timeout_seconds: int,
    command: str,
    expected_markers: tuple[str, ...],
    step_name: str,
    artifact_prefix: str,
    output_directory: Path,
    approval_markers: tuple[str, ...] = (),
    approval_button_text: str | None = None,
) -> DeviceSmokeStep:
    if not INPUT_TEXT_PATTERN.fullmatch(command):
        return DeviceSmokeStep(
            name=step_name,
            status=StepStatus.FAIL,
            detail="command contains unsupported characters for bounded adb input",
        )

    ui_text = latest_ui_text(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    baseline_command_count = timeline_command_occurrences(ui_text, command)
    command_field = find_command_field(ui_text)
    for attempt in range(len(COMMAND_INPUT_REVEAL_SWIPES) + 1):
        if command_field is not None:
            break
        if attempt == len(COMMAND_INPUT_REVEAL_SWIPES):
            break
        start_x, start_y, end_x, end_y, duration_ms = COMMAND_INPUT_REVEAL_SWIPES[attempt]
        reveal = execute_step(
            name=f"{step_name}: Reveal command input",
            command=adb_command(
                adb,
                target,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
        )
        if reveal.status is not StepStatus.OK:
            return reveal
        time.sleep(1)
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        baseline_command_count = max(
            baseline_command_count, timeline_command_occurrences(ui_text, command)
        )
        command_field = find_command_field(ui_text)
    if command_field is None:
        return DeviceSmokeStep(
            name=step_name,
            status=StepStatus.FAIL,
            detail="command input field not found",
            remediation="Confirm GOFFY is visible and not blocked by a permission dialog.",
        )
    tap = tap_center(
        adb,
        target,
        root,
        runner,
        timeout_seconds,
        command_field,
        step_name=f"{step_name}: Focus command input",
    )
    if tap.status is not StepStatus.OK:
        return tap
    time.sleep(2.5)
    if command_field.text.strip() and not command_field_matches(command_field, command):
        cleared = clear_focused_text_field(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            step_name=f"{step_name}: Clear stale command input",
        )
        if cleared.status is not StepStatus.OK:
            return cleared
        time.sleep(0.5)
    typed = execute_step(
        name=f"{step_name}: Type command",
        command=adb_command(adb, target, "shell", "input", "text", adb_input_text(command)),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(adb, "shell", "input", "text", "<bounded-command>"),
    )
    if typed.status is not StepStatus.OK:
        return typed
    time.sleep(1)

    hidden_keyboard = execute_step(
        name=f"{step_name}: Hide keyboard",
        command=adb_command(adb, target, "shell", "input", "keyevent", "BACK"),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(adb, "shell", "input", "keyevent", "BACK"),
    )
    if hidden_keyboard.status is not StepStatus.OK:
        return hidden_keyboard
    time.sleep(1)

    ui_text = latest_ui_text(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    baseline_command_count = max(
        baseline_command_count, timeline_command_occurrences(ui_text, command)
    )
    current_command_field = find_command_field(ui_text) or command_field
    send = find_send_control(ui_text, command_field=current_command_field)
    if not command_field_matches(current_command_field, command):
        before_fallback_artifact = f"{artifact_prefix}-before-fallback.xml"
        if ui_text.strip():
            (output_directory / before_fallback_artifact).write_text(
                ui_text,
                encoding="utf-8",
            )
        fallback = type_command_with_keyevents(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            command=command,
            command_field=current_command_field,
            step_name=step_name,
        )
        if fallback.status is not StepStatus.OK:
            return fallback
        hidden_keyboard = execute_step(
            name=f"{step_name}: Hide keyboard after fallback",
            command=adb_command(adb, target, "shell", "input", "keyevent", "BACK"),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(adb, "shell", "input", "keyevent", "BACK"),
        )
        if hidden_keyboard.status is not StepStatus.OK:
            return hidden_keyboard
        time.sleep(1)
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        after_fallback_artifact = f"{artifact_prefix}-after-fallback.xml"
        if ui_text.strip():
            (output_directory / after_fallback_artifact).write_text(
                ui_text,
                encoding="utf-8",
            )
        baseline_command_count = max(
            baseline_command_count, timeline_command_occurrences(ui_text, command)
        )
        current_command_field = find_command_field(ui_text) or current_command_field
        send = find_send_control(ui_text, command_field=current_command_field)
        if not command_field_matches(current_command_field, command):
            return DeviceSmokeStep(
                name=step_name,
                status=StepStatus.FAIL,
                mutates_device=True,
                detail="command text was not entered after adb text and keyevent fallback",
                remediation=(
                    "Inspect the fallback UI XML artifacts and confirm the command input "
                    "retained focus on the Moto G."
                ),
                artifact=after_fallback_artifact,
            )
    for attempt in range(len(SEND_REVEAL_SWIPES) + 1):
        if send is not None and send_control_is_safely_visible(send):
            break
        if attempt == len(SEND_REVEAL_SWIPES):
            break
        start_x, start_y, end_x, end_y, duration_ms = SEND_REVEAL_SWIPES[attempt]
        reveal = execute_step(
            name=f"{step_name}: Reveal Send button",
            command=adb_command(
                adb,
                target,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
        )
        if reveal.status is not StepStatus.OK:
            return reveal
        time.sleep(1)
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        baseline_command_count = max(
            baseline_command_count, timeline_command_occurrences(ui_text, command)
        )
        current_command_field = find_command_field(ui_text) or current_command_field
        send = find_send_control(ui_text, command_field=current_command_field)
    if not command_field_matches(current_command_field, command):
        artifact = f"{artifact_prefix}-command-mismatch.xml"
        if ui_text.strip():
            (output_directory / artifact).write_text(ui_text, encoding="utf-8")
        return DeviceSmokeStep(
            name=step_name,
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="command text was not visible before tapping Send",
            remediation="Inspect the saved UI XML and confirm the command field retained input.",
            artifact=artifact,
        )
    if send is None or not send_control_is_safely_visible(send):
        artifact = f"{artifact_prefix}-send-missing.xml"
        if ui_text.strip():
            (output_directory / artifact).write_text(ui_text, encoding="utf-8")
        return DeviceSmokeStep(
            name=step_name,
            status=StepStatus.FAIL,
            detail="Send button not safely visible after typing command",
            remediation="Inspect the saved UI XML and adjust bounded viewport reveal logic.",
            artifact=artifact,
        )
    ready_artifact = f"{artifact_prefix}-ready-to-send.xml"
    if ui_text.strip():
        (output_directory / ready_artifact).write_text(ui_text, encoding="utf-8")
    tapped_send = tap_send_control(
        adb,
        target,
        root,
        runner,
        timeout_seconds,
        send,
        step_name=f"{step_name}: Tap Send",
    )
    if tapped_send.status is not StepStatus.OK:
        return tapped_send
    time.sleep(1)
    after_send_artifact = f"{artifact_prefix}-after-send.xml"
    after_send = dump_ui(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        artifact_path=output_directory / after_send_artifact,
    )
    if after_send.status is StepStatus.OK and approval_button_text is None:
        after_send_text = (output_directory / after_send_artifact).read_text(encoding="utf-8")
        current_command_count = timeline_command_occurrences(after_send_text, command)
        fresh_count = current_command_count - baseline_command_count
        if fresh_count > 0 and command_window_contains(
            after_send_text,
            command,
            expected_markers,
            fresh_count=fresh_count,
        ):
            (output_directory / f"{artifact_prefix}.xml").write_text(
                after_send_text,
                encoding="utf-8",
            )
            return DeviceSmokeStep(
                name=step_name,
                status=StepStatus.OK,
                mutates_device=True,
                detail=f"verified visible markers for `{command}`",
                artifact=f"{artifact_prefix}.xml",
            )

    deadline = time.monotonic() + wait_timeout_seconds
    last_text = ""
    timeline_reveal_count = 0
    settle_poll_count = 0
    approval_tapped = False
    while time.monotonic() <= deadline:
        dump_step = dump_ui(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            artifact_path=output_directory / f"{artifact_prefix}.xml",
        )
        if dump_step.status is StepStatus.OK:
            last_text = (output_directory / f"{artifact_prefix}.xml").read_text(encoding="utf-8")
            current_command_count = timeline_command_occurrences(last_text, command)
            fresh_count = current_command_count - baseline_command_count
            if (
                approval_button_text is not None
                and approval_markers
                and not approval_tapped
                and fresh_count > 0
                and command_window_contains(
                    last_text,
                    command,
                    approval_markers,
                    fresh_count=fresh_count,
                )
            ):
                approve, approval_error = find_command_window_node(
                    last_text,
                    command,
                    text=approval_button_text,
                    required_markers=approval_markers,
                    fresh_count=fresh_count,
                )
                if approval_error is not None:
                    return DeviceSmokeStep(
                        name=step_name,
                        status=StepStatus.FAIL,
                        mutates_device=True,
                        detail=approval_error,
                        remediation=(
                            "Only one matching approval control may be visible in the "
                            "fresh smoke command card."
                        ),
                        artifact=f"{artifact_prefix}.xml",
                    )
                if approve is not None:
                    approval = tap_center(
                        adb,
                        target,
                        root,
                        runner,
                        timeout_seconds,
                        approve,
                        step_name=f"{step_name}: Tap approval",
                    )
                    if approval.status is not StepStatus.OK:
                        return approval
                    approval_tapped = True
                    time.sleep(1)
                    continue
            if fresh_count > 0 and command_window_contains(
                last_text, command, expected_markers, fresh_count=fresh_count
            ):
                return DeviceSmokeStep(
                    name=step_name,
                    status=StepStatus.OK,
                    mutates_device=True,
                    detail=f"verified visible markers for `{command}`",
                    artifact=f"{artifact_prefix}.xml",
                )
            if settle_poll_count < INITIAL_RESULT_SETTLE_POLLS:
                settle_poll_count += 1
                time.sleep(1)
                continue
            if timeline_reveal_count < len(TIMELINE_REVEAL_SWIPES):
                start_x, start_y, end_x, end_y, duration_ms = TIMELINE_REVEAL_SWIPES[
                    timeline_reveal_count
                ]
                timeline_reveal_count += 1
                reveal = execute_step(
                    name=f"{step_name}: Reveal task timeline",
                    command=adb_command(
                        adb,
                        target,
                        "shell",
                        "input",
                        "swipe",
                        start_x,
                        start_y,
                        end_x,
                        end_y,
                        duration_ms,
                    ),
                    root=root,
                    runner=runner,
                    timeout_seconds=timeout_seconds,
                    mutates_device=True,
                    display_command=display_adb_command(
                        adb,
                        "shell",
                        "input",
                        "swipe",
                        start_x,
                        start_y,
                        end_x,
                        end_y,
                        duration_ms,
                    ),
                )
                if reveal.status is not StepStatus.OK:
                    return reveal
        time.sleep(1)

    missing_markers = [marker for marker in expected_markers if marker not in last_text]
    if approval_button_text is not None and not approval_tapped:
        missing_markers.append("approved memory action")
    current_command_count = timeline_command_occurrences(last_text, command)
    if current_command_count <= baseline_command_count:
        missing_markers.append("fresh command card")
    elif not command_window_contains(
        last_text,
        command,
        expected_markers,
        fresh_count=current_command_count - baseline_command_count,
    ):
        missing_markers.append("fresh verified command card")
    missing = ", ".join(missing_markers)
    return DeviceSmokeStep(
        name=step_name,
        status=StepStatus.FAIL,
        mutates_device=True,
        detail=f"timed out waiting for visible markers; missing: {missing or 'command window'}",
        remediation="Check the saved UI XML, screenshot, and bounded GOFFY logcat artifact.",
        artifact=f"{artifact_prefix}.xml",
    )


def command_field_matches(command_field: UiNode, command: str) -> bool:
    return command_field.text.strip().casefold() == command.strip().casefold()


def type_command_with_keyevents(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    command: str,
    command_field: UiNode,
    step_name: str,
) -> DeviceSmokeStep:
    keyevents = keyevents_for_input_text(command)
    if keyevents is None:
        return DeviceSmokeStep(
            name=f"{step_name}: Type command fallback",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="command cannot be typed with bounded keyevent fallback",
            remediation="Use a smoke command containing only ASCII letters, digits, and spaces.",
        )
    focused = tap_center(
        adb,
        target,
        root,
        runner,
        timeout_seconds,
        command_field,
        step_name=f"{step_name}: Refocus command input for fallback",
    )
    if focused.status is not StepStatus.OK:
        return focused
    time.sleep(2.5)
    for keyevent in keyevents:
        typed = execute_step(
            name=f"{step_name}: Type command fallback",
            command=adb_command(adb, target, "shell", "input", "keyevent", keyevent),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "keyevent",
                keyevent,
            ),
        )
        if typed.status is not StepStatus.OK:
            return typed
        time.sleep(0.04)
    return DeviceSmokeStep(
        name=f"{step_name}: Type command fallback",
        status=StepStatus.OK,
        mutates_device=True,
        detail="typed command with bounded keyevent fallback",
    )


def keyevents_for_input_text(text: str) -> tuple[str, ...] | None:
    keyevents: list[str] = []
    for character in text.casefold():
        keyevent = KEYEVENT_BY_INPUT_CHAR.get(character)
        if keyevent is None:
            return None
        keyevents.append(keyevent)
    return tuple(keyevents)


def latest_ui_text(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> str:
    dump = runner(
        adb_command(adb, target, "shell", "uiautomator", "dump", REMOTE_UI_XML),
        root,
        timeout_seconds,
    )
    if dump.exit_code != 0:
        return ""
    xml = runner(adb_command(adb, target, "exec-out", "cat", REMOTE_UI_XML), root, timeout_seconds)
    return xml.stdout if xml.exit_code == 0 else ""


def dump_ui(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    artifact_path: Path,
) -> DeviceSmokeStep:
    text = latest_ui_text(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    if not text.strip():
        return DeviceSmokeStep(
            name="Dump UI",
            status=StepStatus.FAIL,
            detail="uiautomator dump returned no XML",
        )
    artifact_path.write_text(text, encoding="utf-8")
    return DeviceSmokeStep(
        name="Dump UI",
        status=StepStatus.OK,
        detail="captured UIAutomator XML",
        artifact=artifact_path.name,
    )


def nodes_from_xml(xml_text: str) -> tuple[UiNode, ...]:
    try:
        # UI XML comes from local `adb shell uiautomator dump`; this runner stays
        # stdlib-only and bounds the command surface instead of adding a parser dependency.
        root = ET.fromstring(xml_text)  # noqa: S314
    except ET.ParseError:
        return ()
    nodes: list[UiNode] = []
    for element in root.iter("node"):
        bounds = parse_bounds(element.attrib.get("bounds", ""))
        if bounds is None:
            continue
        nodes.append(
            UiNode(
                text=element.attrib.get("text", ""),
                content_desc=element.attrib.get("content-desc", ""),
                class_name=element.attrib.get("class", ""),
                bounds=bounds,
                enabled=element.attrib.get("enabled") == "true",
                clickable=element.attrib.get("clickable") == "true",
                password=element.attrib.get("password") == "true",
                focused=element.attrib.get("focused") == "true",
            )
        )
    return tuple(nodes)


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = BOUNDS_PATTERN.fullmatch(value)
    if match is None:
        return None
    left, top, right, bottom = (int(part) for part in match.groups())
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def find_command_field(xml_text: str) -> UiNode | None:
    nodes = nodes_from_xml(xml_text)
    for node in nodes:
        if (
            node.class_name == "android.widget.EditText"
            and node.enabled
            and not node.password
            and node.text != DEBUG_HUB_ENDPOINT
        ):
            return node
    return None


def find_debug_token_field(xml_text: str) -> UiNode | None:
    if "Development bearer token" not in xml_text:
        return None
    nodes = nodes_from_xml(xml_text)
    labels = [node for node in nodes if node.text == "Development bearer token"]
    fields = [
        node for node in nodes if node.class_name == "android.widget.EditText" and node.enabled
    ]
    if not labels or not fields:
        return None
    label = labels[-1]
    labelled_fields = [field for field in fields if field_is_near_label(field, label)]
    if not labelled_fields:
        return None
    return min(labelled_fields, key=lambda field: field_label_distance(field, label))


def find_focused_debug_token_field(xml_text: str) -> UiNode | None:
    token_field = find_debug_token_field(xml_text)
    if token_field is None or not token_field.focused:
        return None
    return token_field


def field_is_near_label(field: UiNode, label: UiNode) -> bool:
    field_left, field_top, field_right, field_bottom = field.bounds
    label_left, label_top, label_right, label_bottom = label.bounds
    horizontally_overlaps = field_left <= label_right and field_right >= label_left
    vertically_contains_or_follows = (
        field_top <= label_bottom + 80 and field_bottom >= label_top - 8
    )
    return horizontally_overlaps and vertically_contains_or_follows


def field_label_distance(field: UiNode, label: UiNode) -> int:
    _, field_top, _, field_bottom = field.bounds
    _, label_top, _, label_bottom = label.bounds
    if field_top <= label_top and field_bottom >= label_bottom:
        return 0
    return min(abs(field_top - label_bottom), abs(field_bottom - label_top))


def token_in_unmasked_edit_text(xml_text: str, token: str) -> bool:
    return any(
        node.text == token and node.class_name == "android.widget.EditText" and not node.password
        for node in nodes_from_xml(xml_text)
    )


def find_node(xml_text: str, *, text: str) -> UiNode | None:
    for node in nodes_from_xml(xml_text):
        if node.text == text and node.enabled:
            return node
    return None


def find_enabled_action_for_text(xml_text: str, *, text: str) -> UiNode | None:
    nodes = nodes_from_xml(xml_text)
    labels = [node for node in nodes if node.text == text and node.enabled]
    for label in labels:
        label_x, label_y = label.center
        containing_actions = [
            node
            for node in nodes
            if node.clickable
            and node.bounds[0] <= label_x <= node.bounds[2]
            and node.bounds[1] <= label_y <= node.bounds[3]
        ]
        if containing_actions:
            enabled_actions = [node for node in containing_actions if node.enabled]
            if enabled_actions:
                return min(enabled_actions, key=node_area)
            continue
        return label
    return None


def node_area(node: UiNode) -> int:
    left, top, right, bottom = node.bounds
    return (right - left) * (bottom - top)


def find_send_control(xml_text: str, *, command_field: UiNode) -> UiNode | None:
    nodes = nodes_from_xml(xml_text)
    labelled_send_nodes = [node for node in nodes if node.text == "Send"]
    if labelled_send_nodes:
        return next((node for node in labelled_send_nodes if node.enabled), None)

    send_descriptions = {"send", "submit goffy command"}
    content_desc_send_nodes = [
        node for node in nodes if node.content_desc.strip().casefold() in send_descriptions
    ]
    if content_desc_send_nodes:
        return next((node for node in content_desc_send_nodes if node.enabled), None)

    _, field_top, field_right, field_bottom = command_field.bounds
    candidates: list[UiNode] = []
    for node in nodes:
        left, top, right, bottom = node.bounds
        if not node.enabled or not node.clickable:
            continue
        if right < field_right - 20 or left < field_right - 120:
            continue
        if top < field_top - 20 or bottom > field_bottom + 260:
            continue
        width = right - left
        height = bottom - top
        if width > 180 or height > 240:
            continue
        candidates.append(node)

    if not candidates:
        return None
    return max(candidates, key=lambda node: (node.bounds[2], node.bounds[0]))


def send_control_is_safely_visible(node: UiNode) -> bool:
    _, _, _, viewport_bottom = MOTO_G_PORTRAIT_VIEWPORT_BOUNDS
    return node.bounds[3] <= viewport_bottom - SEND_BOTTOM_SAFE_MARGIN_PX


def timeline_nodes(xml_text: str) -> tuple[UiNode, ...]:
    nodes = nodes_from_xml(xml_text)
    timeline_nodes = tuple(
        node for node in nodes if node.text and node.class_name != "android.widget.EditText"
    )
    try:
        timeline_index = next(
            index for index, node in enumerate(timeline_nodes) if node.text == "TASK TIMELINE"
        )
    except ValueError:
        return ()
    except StopIteration:
        return ()
    return timeline_nodes[timeline_index + 1 :]


def timeline_texts(xml_text: str) -> tuple[str, ...]:
    return tuple(node.text for node in timeline_nodes(xml_text))


def timeline_command_occurrences(xml_text: str, command: str) -> int:
    normalized = command.casefold()
    return sum(1 for text in timeline_texts(xml_text) if text.casefold() == normalized)


def command_window_contains(
    xml_text: str,
    command: str,
    markers: tuple[str, ...],
    *,
    fresh_count: int | None = None,
) -> bool:
    nodes = command_window_nodes(
        xml_text,
        command,
        fresh_count=fresh_count,
    )
    if not nodes:
        return False
    segment = " ".join(node.text for node in nodes)
    return all(marker in segment for marker in markers)


def command_window_nodes(
    xml_text: str,
    command: str,
    *,
    fresh_count: int | None = None,
) -> tuple[UiNode, ...]:
    nodes = timeline_nodes(xml_text)
    normalized = command.casefold()
    command_indexes = [
        index
        for index, node in enumerate(nodes)
        if node.text.casefold() == normalized and is_task_card_header(nodes, index)
    ]
    if not command_indexes:
        return ()
    if fresh_count is not None and fresh_count <= 0:
        return ()

    # GOFFY renders the newest task cards first; the fresh command is therefore
    # the first matching command window after the current command count increases.
    index = command_indexes[0]
    next_index = next_task_card_header_index(nodes, after=index)
    if next_index is None:
        next_index = min(len(nodes), index + MAX_TASK_CARD_WINDOW_NODES)
    return nodes[index:next_index]


def is_task_card_header(nodes: Sequence[UiNode], index: int) -> bool:
    if index + 1 >= len(nodes):
        return False
    return nodes[index + 1].text.strip().upper() in TASK_CARD_STATUS_TEXTS


def next_task_card_header_index(nodes: Sequence[UiNode], *, after: int) -> int | None:
    for index in range(after + 1, len(nodes)):
        if is_task_card_header(nodes, index):
            return index
    return None


def find_command_window_node(
    xml_text: str,
    command: str,
    *,
    text: str,
    required_markers: tuple[str, ...],
    fresh_count: int,
) -> tuple[UiNode | None, str | None]:
    nodes = command_window_nodes(xml_text, command, fresh_count=fresh_count)
    if not nodes:
        return None, None

    segment = " ".join(node.text for node in nodes)
    if not all(marker in segment for marker in required_markers):
        return None, None

    candidates = [node for node in nodes if node.text == text and node.enabled]
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, None
    return None, f"ambiguous approval control `{text}` in fresh command window"


def verify_home_surface(*, ui_xml: str, output_directory: Path) -> DeviceSmokeStep:
    visible_nodes = visible_nodes_from_xml(
        ui_xml,
        viewport_bounds=MOTO_G_PORTRAIT_VIEWPORT_BOUNDS,
    )
    missing = missing_home_surface_markers(visible_nodes)
    artifact = "home-surface.xml"
    (output_directory / artifact).write_text(ui_xml, encoding="utf-8")
    if missing:
        return DeviceSmokeStep(
            name="HOME surface smoke",
            status=StepStatus.FAIL,
            detail="missing HOME viewport markers: " + ", ".join(missing[:6]),
            remediation=(
                "Inspect home-surface.xml and confirm the GOFFY HOME shell, orb, "
                "HOME setup card, device map, Settings escape hatch, and "
                "connection/target indicators intersect the Moto G portrait viewport."
            ),
            artifact=artifact,
        )
    return DeviceSmokeStep(
        name="HOME surface smoke",
        status=StepStatus.OK,
        detail="verified idle GOFFY HOME and setup-card viewport markers",
        artifact=artifact,
    )


def reveal_and_verify_device_map_surface(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    output_directory: Path,
) -> tuple[DeviceSmokeStep, ...]:
    steps: list[DeviceSmokeStep] = []
    for start_x, start_y, end_x, end_y, duration_ms in DEVICE_MAP_REVEAL_SWIPES:
        step = execute_step(
            name="Reveal device map viewport",
            command=adb_command(
                adb,
                target,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                start_x,
                start_y,
                end_x,
                end_y,
                duration_ms,
            ),
        )
        steps.append(step)
        if step.status is not StepStatus.OK:
            return tuple(steps)
        time.sleep(0.4)

    dump = dump_ui(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        artifact_path=output_directory / "device-map.xml",
    )
    steps.append(dump)
    if dump.status is not StepStatus.OK:
        return tuple(steps)

    steps.append(
        verify_device_map_surface(
            ui_xml=(output_directory / "device-map.xml").read_text(encoding="utf-8"),
            output_directory=output_directory,
        )
    )
    return tuple(steps)


def verify_device_map_surface(*, ui_xml: str, output_directory: Path) -> DeviceSmokeStep:
    visible_nodes = visible_nodes_from_xml(
        ui_xml,
        viewport_bounds=MOTO_G_PORTRAIT_VIEWPORT_BOUNDS,
    )
    missing = missing_device_map_surface_markers(visible_nodes)
    artifact = "device-map.xml"
    (output_directory / artifact).write_text(ui_xml, encoding="utf-8")
    if missing:
        return DeviceSmokeStep(
            name="Device map viewport smoke",
            status=StepStatus.FAIL,
            detail="missing device-map viewport markers: " + ", ".join(missing[:6]),
            remediation=(
                "Inspect device-map.xml and confirm the read-only device map node "
                "labels are reachable after the bounded HOME viewport reveal."
            ),
            artifact=artifact,
        )
    return DeviceSmokeStep(
        name="Device map viewport smoke",
        status=StepStatus.OK,
        detail="verified read-only device-map node labels",
        artifact=artifact,
    )


def missing_home_surface_markers(nodes: tuple[UiNode, ...]) -> list[str]:
    checks: dict[str, bool] = {
        "GOFFY title": has_exact_text(nodes, "GOFFY"),
        "GOFFY LITE": has_exact_text(nodes, "GOFFY LITE"),
        "SETTINGS": has_exact_text(nodes, "SETTINGS"),
        "GOFFY orb state": has_content_desc_prefix(nodes, "GOFFY orb state:"),
        "LOOP phase": has_text_prefix(nodes, "LOOP /"),
        "MAC LINK": has_exact_text(nodes, "MAC LINK"),
        "EXECUTION TARGET": has_exact_text(nodes, "EXECUTION TARGET"),
        "DOCK MODE": has_exact_text(nodes, "DOCK MODE"),
        "HOME SHELL": has_exact_text(nodes, "HOME SHELL"),
        "HOME status": has_home_setup_status(nodes),
        "HOME CHECK": has_exact_text(nodes, "CHECK"),
        "DEVICE MAP": has_exact_text(nodes, "DEVICE MAP"),
    }
    return [label for label in HOME_SURFACE_MARKERS if not checks[label]]


def missing_device_map_surface_markers(nodes: tuple[UiNode, ...]) -> list[str]:
    checks: dict[str, bool] = {
        "PHONE ENGINE": has_exact_text(nodes, "PHONE ENGINE"),
        "MAC HUB": has_exact_text(nodes, "MAC HUB"),
        "MCP REGISTRY": has_exact_text(nodes, "MCP REGISTRY"),
        "LOCAL MODEL": has_exact_text(nodes, "LOCAL MODEL"),
        "CLOUD": has_exact_text(nodes, "CLOUD"),
    }
    return [label for label in DEVICE_MAP_SURFACE_MARKERS if not checks[label]]


def has_exact_text(nodes: tuple[UiNode, ...], text: str) -> bool:
    return any(node.text == text for node in nodes)


def has_text_prefix(nodes: tuple[UiNode, ...], prefix: str) -> bool:
    return any(node.text.startswith(prefix) for node in nodes)


def has_home_setup_status(nodes: tuple[UiNode, ...]) -> bool:
    return any(
        node.text.startswith(
            (
                "STATUS UNKNOWN",
                "DEFAULT HOME",
                "AVAILABLE",
                "NOT AVAILABLE",
            )
        )
        for node in nodes
    )


def has_content_desc_prefix(nodes: tuple[UiNode, ...], prefix: str) -> bool:
    return any(node.content_desc.startswith(prefix) for node in nodes)


def visible_nodes_from_xml(
    xml_text: str,
    *,
    viewport_bounds: tuple[int, int, int, int] | None = None,
) -> tuple[UiNode, ...]:
    nodes = nodes_from_xml(xml_text)
    if viewport_bounds is None:
        return nodes
    return tuple(node for node in nodes if node_intersects_bounds(node, viewport_bounds))


def visible_ui_text(
    xml_text: str,
    *,
    viewport_bounds: tuple[int, int, int, int] | None = None,
) -> str:
    parts: list[str] = []
    for node in visible_nodes_from_xml(xml_text, viewport_bounds=viewport_bounds):
        if node.text:
            parts.append(node.text)
        if node.content_desc:
            parts.append(node.content_desc)
    return " ".join(parts)


def node_intersects_bounds(node: UiNode, bounds: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = node.bounds
    viewport_left, viewport_top, viewport_right, viewport_bottom = bounds
    return (
        right > viewport_left
        and left < viewport_right
        and bottom > viewport_top
        and top < viewport_bottom
    )


def tap_center(
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    node: UiNode,
    *,
    step_name: str = "Tap UI element",
) -> DeviceSmokeStep:
    x, y = node.center
    return execute_step(
        name=step_name,
        command=adb_command(adb, target, "shell", "input", "tap", str(x), str(y)),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(adb, "shell", "input", "tap", str(x), str(y)),
    )


def tap_text_field_entry_area(
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    node: UiNode,
    *,
    step_name: str = "Tap text field",
) -> DeviceSmokeStep:
    left, top, right, bottom = node.bounds
    x = max(left + 24, right - 48)
    y = min(bottom - 8, max(top + 8, bottom - 20))
    return execute_step(
        name=step_name,
        command=adb_command(adb, target, "shell", "input", "tap", str(x), str(y)),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(adb, "shell", "input", "tap", str(x), str(y)),
    )


def clear_focused_text_field(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    step_name: str,
) -> DeviceSmokeStep:
    delete_keyevents = ("KEYCODE_MOVE_END",) + ("KEYCODE_DEL",) * MAX_INPUT_TEXT_LENGTH
    return execute_step(
        name=step_name,
        command=adb_command(adb, target, "shell", "input", "keyevent", *delete_keyevents),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(
            adb,
            "shell",
            "input",
            "keyevent",
            "KEYCODE_MOVE_END",
            f"KEYCODE_DELx{MAX_INPUT_TEXT_LENGTH}",
        ),
    )


def tap_send_control(
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    node: UiNode,
    *,
    step_name: str = "Tap Send",
) -> DeviceSmokeStep:
    left, top, right, bottom = node.bounds
    x = (left + right) // 2
    height = max(1, bottom - top)
    # The Moto G command surface can clip the send button against the bottom
    # gesture area; tapping near the top of the control avoids the gesture strip.
    y = top + max(1, min(max(height // 6, 12), 32))
    return execute_step(
        name=step_name,
        command=adb_command(adb, target, "shell", "input", "tap", str(x), str(y)),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(adb, "shell", "input", "tap", str(x), str(y)),
    )


def adb_input_text(value: str) -> str:
    if len(value) > MAX_INPUT_TEXT_LENGTH or INPUT_TEXT_PATTERN.fullmatch(value) is None:
        raise ValueError("command text is not safe for adb input")
    return value.replace(" ", "%s")


def capture_screenshot(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    timeout_seconds: int,
    output_path: Path,
) -> DeviceSmokeStep:
    try:
        completed = subprocess.run(  # noqa: S603
            list(adb_command(adb, target, "exec-out", "screencap", "-p")),
            cwd=root,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.FAIL,
            command=display_adb_command(adb, "exec-out", "screencap", "-p"),
            detail="screenshot command timed out",
        )
    if completed.returncode != 0 or not completed.stdout:
        return DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.FAIL,
            command=display_adb_command(adb, "exec-out", "screencap", "-p"),
            detail="screenshot command failed",
        )
    output_path.write_bytes(completed.stdout)
    return DeviceSmokeStep(
        name="Capture screenshot",
        status=StepStatus.OK,
        command=display_adb_command(adb, "exec-out", "screencap", "-p"),
        detail="captured final screenshot",
        artifact=output_path.name,
    )


def capture_app_logcat(
    *,
    adb: Path,
    target: DeviceTarget,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    output_path: Path,
) -> DeviceSmokeStep:
    pid_result = runner(
        adb_command(adb, target, "shell", "pidof", PACKAGE_NAME), root, timeout_seconds
    )
    pid = pid_result.stdout.strip().split()[0] if pid_result.exit_code == 0 else ""
    if not pid.isdigit():
        return DeviceSmokeStep(
            name="Capture bounded app logcat",
            status=StepStatus.SKIP,
            detail="GOFFY process pid unavailable",
        )
    logcat = runner(
        adb_command(adb, target, "logcat", "-d", "--pid", pid, "-t", str(MAX_LOGCAT_LINES)),
        root,
        timeout_seconds,
    )
    if logcat.exit_code != 0:
        return DeviceSmokeStep(
            name="Capture bounded app logcat",
            status=StepStatus.FAIL,
            command=display_adb_command(adb, "logcat", "-d", "--pid", "<goffy-pid>", "-t", "200"),
            detail="bounded app logcat command failed",
        )
    output_path.write_text(logcat.stdout[-16_384:], encoding="utf-8")
    return DeviceSmokeStep(
        name="Capture bounded app logcat",
        status=StepStatus.OK,
        command=display_adb_command(adb, "logcat", "-d", "--pid", "<goffy-pid>", "-t", "200"),
        detail="captured bounded GOFFY process logcat",
        artifact=output_path.name,
    )


def execute_step(
    *,
    name: str,
    command: Sequence[str],
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    mutates_device: bool = False,
    display_command: Sequence[str] | None = None,
) -> DeviceSmokeStep:
    result = runner(command, root, timeout_seconds)
    if result.timed_out:
        return DeviceSmokeStep(
            name=name,
            status=StepStatus.FAIL,
            command=tuple(display_command or command),
            mutates_device=mutates_device,
            detail="command timed out",
            remediation="Reconnect the phone and retry after confirming USB debugging.",
        )
    return DeviceSmokeStep(
        name=name,
        status=StepStatus.OK if result.exit_code == 0 else StepStatus.FAIL,
        command=tuple(display_command or command),
        mutates_device=mutates_device,
        detail="exit:0" if result.exit_code == 0 else "adb command failed",
        remediation="" if result.exit_code == 0 else "Fix the reported adb failure and rerun.",
    )


def default_output_directory(root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / ".goffy-validation" / "device-smoke" / timestamp


def executed_report(
    *,
    root: Path,
    output_directory: Path,
    phone_command: str,
    mac_command: str | None,
    steps: Sequence[DeviceSmokeStep],
) -> DeviceSmokeReport:
    ok = all(step.status in {StepStatus.OK, StepStatus.SKIP} for step in steps)
    if mac_command is not None:
        ok = ok and any(
            step.name == "MAC command smoke" and step.status is StepStatus.OK for step in steps
        )
    return DeviceSmokeReport(
        executed=True,
        ok=ok,
        output_directory=str(output_directory),
        phone_command=phone_command,
        mac_command=mac_command,
        steps=tuple(steps),
        repo_root=root,
    )


def redaction_report(report: DeviceSmokeReport) -> DoctorReport:
    return DoctorReport(checks=(), repo_root=report.repo_root, home=report.home)


def format_command(command: Sequence[str], *, report: DeviceSmokeReport) -> str:
    redactor = redaction_report(report)
    return " ".join(safe_text(part, report=redactor) for part in command)


def render_text(report: DeviceSmokeReport) -> str:
    redactor = redaction_report(report)
    lines = ["GOFFY Moto G device smoke"]
    lines.append(f"mode: {'execute' if report.executed else 'plan'}")
    lines.append(f"overall: {'passed' if report.ok else 'not-passed'}")
    if report.output_directory:
        lines.append(f"artifacts: {safe_text(report.output_directory, report=redactor)}")
    lines.append("")
    lines.append("steps:")
    for step in report.steps:
        lines.append(f"[{step.status}] {step.name}")
        if step.command:
            lines.append(f"       command: {format_command(step.command, report=report)}")
        if step.mutates_device:
            lines.append("       mutates-device: true")
        if step.detail:
            lines.append(f"       detail: {safe_text(step.detail, report=redactor)}")
        if step.artifact:
            lines.append(f"       artifact: {step.artifact}")
        if step.remediation:
            lines.append(f"       fix: {safe_text(step.remediation, report=redactor)}")
    return "\n".join(lines)


def render_json(report: DeviceSmokeReport) -> str:
    redactor = redaction_report(report)
    payload: dict[str, object] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": report.ok,
        "executed": report.executed,
        "outputDirectory": (
            redact_paths(report.output_directory, report=redactor)
            if report.output_directory is not None
            else None
        ),
        "phoneCommand": redact_paths(report.phone_command, report=redactor),
        "macCommand": (
            redact_paths(report.mac_command, report=redactor)
            if report.mac_command is not None
            else None
        ),
        "steps": [
            {
                **asdict(step),
                "status": step.status.value,
                "command": [redact_paths(part, report=redactor) for part in step.command],
                "detail": redact_paths(step.detail, report=redactor),
                "remediation": redact_paths(step.remediation, report=redactor),
            }
            for step in report.steps
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def bounded_timeout(value: str) -> int:
    try:
        timeout = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be an integer") from exc
    if timeout <= 0 or timeout > 300:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 300 seconds")
    return timeout


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=existing_directory, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--execute", action="store_true", help="Run the fixed device smoke flow.")
    parser.add_argument(
        "--confirm-device-mutation",
        action="store_true",
        help="Required with --execute because the flow mutates connected phone state.",
    )
    parser.add_argument("--include-mac", action="store_true", help="Also submit the MAC command.")
    parser.add_argument(
        "--include-memory",
        action="store_true",
        help=(
            "Also submit a fixed approved local-memory write and bounded memory list. "
            "This never runs forget-all."
        ),
    )
    parser.add_argument(
        "--debug-hub-token-file",
        type=Path,
        help=(
            "Optional short-lived token file under .goffy-validation used to configure "
            "the fixed localhost debug Hub link before --include-mac."
        ),
    )
    parser.add_argument("--phone-command", default=DEFAULT_PHONE_COMMAND)
    parser.add_argument("--mac-command", default=DEFAULT_MAC_COMMAND)
    parser.add_argument(
        "--device-serial",
        help=(
            "Optional ADB serial for the Moto G target; required when multiple devices "
            "are connected."
        ),
    )
    parser.add_argument("--timeout-seconds", type=bounded_timeout, default=30)
    parser.add_argument("--wait-timeout-seconds", type=bounded_timeout, default=20)
    args = parser.parse_args(argv)

    report = build_report(
        root=args.repo_root,
        execute=args.execute,
        confirm_device_mutation=args.confirm_device_mutation,
        include_mac=args.include_mac,
        include_memory=args.include_memory,
        phone_command=args.phone_command,
        mac_command=args.mac_command,
        timeout_seconds=args.timeout_seconds,
        wait_timeout_seconds=args.wait_timeout_seconds,
        device_serial=args.device_serial,
        debug_hub_token_file=args.debug_hub_token_file,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
