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
DEBUG_HUB_ENDPOINT = "ws://127.0.0.1:8787/ws/v1"
REMOTE_UI_XML = "/sdcard/goffy-device-smoke-window.xml"
MAX_INPUT_TEXT_LENGTH = 120
INPUT_TEXT_PATTERN = re.compile(r"^[A-Za-z0-9 .,_:-]{1,120}$")
DEBUG_HUB_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._-]{24,120}$")
BOUNDS_PATTERN = re.compile(r"\[([0-9]+),([0-9]+)\]\[([0-9]+),([0-9]+)\]")
MAX_LOGCAT_LINES = 200
MOTO_G_MODEL_PATTERN = re.compile(r"\bmoto\s*g\b|moto_g", re.IGNORECASE)
DEVICE_SERIAL_PLACEHOLDER = "<device-serial>"
DEBUG_HUB_TOKEN_PLACEHOLDER = "<redacted-debug-hub-token>"  # noqa: S105


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


def planned_steps(
    root: Path,
    adb: Path | None,
    *,
    include_mac: bool,
    phone_command: str,
    mac_command: str,
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
            name="PHONE command smoke",
            status=StepStatus.PLANNED,
            mutates_device=True,
            detail=f"would submit `{phone_command}` and verify phone.battery.status",
        ),
    ]
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
                detail=f"would submit `{mac_command}` and verify mac.system_info",
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
    phone_command: str = DEFAULT_PHONE_COMMAND,
    mac_command: str = DEFAULT_MAC_COMMAND,
    runner: CommandRunner = default_command_runner,
    timeout_seconds: int = 30,
    wait_timeout_seconds: int = 20,
    output_directory: Path | None = None,
    trusted_root: Path = ROOT,
    device_serial: str | None = None,
    debug_hub_token_file: Path | None = None,
) -> DeviceSmokeReport:
    resolved_root = root.resolve()
    adb = trusted_adb_path()
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
                phone_command=phone_command,
                mac_command=mac_command,
                debug_hub_token_file=debug_hub_token_file,
            ),
            repo_root=resolved_root,
        )

    blockers = execution_blockers(
        root=resolved_root,
        adb=adb,
        confirm_device_mutation=confirm_device_mutation,
        include_mac=include_mac,
        phone_command=phone_command,
        mac_command=mac_command,
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

    steps.append(
        submit_and_verify_command(
            adb=adb,
            target=target,
            root=resolved_root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            command=phone_command,
            expected_markers=("VERIFIED", "PHONE", "phone.battery.status", "%"),
            step_name="PHONE command smoke",
            artifact_prefix="phone-command",
            output_directory=artifacts,
        )
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
                expected_markers=("VERIFIED", "MAC", "mac.system_info", "Darwin"),
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
    phone_command: str,
    mac_command: str,
    trusted_root: Path,
    debug_hub_token_file: Path | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not confirm_device_mutation:
        blockers.append("missing explicit --confirm-device-mutation")
    if phone_command != DEFAULT_PHONE_COMMAND:
        blockers.append("execute mode only supports the fixed PHONE smoke command")
    if include_mac and mac_command != DEFAULT_MAC_COMMAND:
        blockers.append("execute mode only supports the fixed MAC smoke command")
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
    hide = find_node(ui_text, text="Hide")
    if hide is None:
        return DeviceSmokeStep(
            name="Collapse Hub setup card",
            status=StepStatus.SKIP,
            detail="Hub setup card was already collapsed",
        )
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
    return step


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
    if DEBUG_HUB_ENDPOINT in ui_text and "NOT CONFIGURED" not in ui_text:
        write_debug_hub_link_artifact(output_directory, ui_text, token)
        return DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.OK,
            mutates_device=True,
            detail="fixed localhost debug Hub link was already configured",
            artifact="debug-hub-link.xml",
        )

    if "Development bearer token" not in ui_text:
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

    tap_token = tap_center(
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
    for attempt in range(3):
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        debug_link = find_node(ui_text, text="Debug link")
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
        return DeviceSmokeStep(
            name="Configure debug Hub link",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="Debug link button was not visible after bounded scroll",
            remediation="Check the saved UI XML for setup-card layout changes.",
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
    send = find_node(ui_text, text="Send")
    for attempt in range(4):
        if send is not None:
            break
        if attempt == 3:
            break
        reveal = execute_step(
            name=f"{step_name}: Reveal Send button",
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
        send = find_node(ui_text, text="Send")
    if send is None:
        artifact = f"{artifact_prefix}-send-missing.xml"
        if ui_text.strip():
            (output_directory / artifact).write_text(ui_text, encoding="utf-8")
        return DeviceSmokeStep(
            name=step_name,
            status=StepStatus.FAIL,
            detail="Send button not found after typing command",
            remediation="Inspect the saved UI XML and adjust bounded viewport reveal logic.",
            artifact=artifact,
        )
    tapped_send = tap_center(
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

    deadline = time.monotonic() + wait_timeout_seconds
    last_text = ""
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
            if timeline_command_occurrences(
                last_text, command
            ) > baseline_command_count and command_window_contains(
                last_text, command, expected_markers
            ):
                return DeviceSmokeStep(
                    name=step_name,
                    status=StepStatus.OK,
                    mutates_device=True,
                    detail=f"verified visible markers for `{command}`",
                    artifact=f"{artifact_prefix}.xml",
                )
        time.sleep(1)

    missing_markers = [marker for marker in expected_markers if marker not in last_text]
    if timeline_command_occurrences(last_text, command) <= baseline_command_count:
        missing_markers.append("fresh command card")
    missing = ", ".join(missing_markers)
    return DeviceSmokeStep(
        name=step_name,
        status=StepStatus.FAIL,
        mutates_device=True,
        detail=f"timed out waiting for visible markers; missing: {missing or 'command window'}",
        remediation="Check the saved UI XML, screenshot, and bounded GOFFY logcat artifact.",
        artifact=f"{artifact_prefix}.xml",
    )


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
        if node.class_name == "android.widget.EditText" and node.enabled:
            return node
    return None


def find_debug_token_field(xml_text: str) -> UiNode | None:
    if "Development bearer token" not in xml_text:
        return None
    fields = [
        node
        for node in nodes_from_xml(xml_text)
        if node.class_name == "android.widget.EditText" and node.enabled
    ]
    if len(fields) < 2:
        return None
    return max(fields, key=lambda node: node.bounds[1])


def find_node(xml_text: str, *, text: str) -> UiNode | None:
    for node in nodes_from_xml(xml_text):
        if node.text == text and node.enabled:
            return node
    return None


def timeline_texts(xml_text: str) -> tuple[str, ...]:
    texts = tuple(node.text for node in nodes_from_xml(xml_text) if node.text)
    try:
        timeline_index = texts.index("TASK TIMELINE")
    except ValueError:
        return texts
    return texts[timeline_index + 1 :]


def timeline_command_occurrences(xml_text: str, command: str) -> int:
    return sum(1 for text in timeline_texts(xml_text) if text == command)


def command_window_contains(xml_text: str, command: str, markers: tuple[str, ...]) -> bool:
    texts = timeline_texts(xml_text)
    try:
        index = texts.index(command)
    except ValueError:
        return False
    window = " ".join(texts[index : index + 30])
    return all(marker in window for marker in markers)


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
