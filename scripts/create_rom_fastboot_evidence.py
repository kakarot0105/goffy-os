from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.android_preflight import default_sdk_roots, first_existing_path  # noqa: E402
from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.rom-fastboot-evidence.v1"
DEFAULT_OUTPUT = Path(".goffy-validation/rom-fastboot-evidence.json")
SERIAL_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{4,128}$")
FASTBOOT_DEVICE_LINE_PATTERN = re.compile(r"^(?P<serial>\S+)\s+fastboot(?:\s|$)")
ABSOLUTE_POSIX_PATH = re.compile(r"(?<![>\w])/(?!\s)(?:[^;\n\r,)]+)")
ABSOLUTE_WINDOWS_PATH = re.compile(
    r"(?i)(?:\b[A-Z]:\\[^\s;\n\r,)]+|\\\\[A-Za-z0-9._$-]+\\[^\s;\n\r,)]+)"
)
DESTRUCTIVE_FASTBOOT_SUBCOMMANDS = frozenset({"flash", "erase", "wipe", "boot", "reboot"})
READ_ONLY_FASTBOOT_LABELS = frozenset({"fastboot --version", "fastboot devices"})


class FastbootStatus(StrEnum):
    HOST_READY = "HOST_READY"
    MANUAL_BOOTLOADER_VISIBLE = "MANUAL_BOOTLOADER_VISIBLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class FastbootEvidence:
    schema_version: str
    generated_at: str
    ok: bool
    status: FastbootStatus
    destructive_actions: str
    host: dict[str, str]
    manual_bootloader_check: dict[str, object]
    commands: tuple[dict[str, object], ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


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


def create_fastboot_evidence(
    *,
    root: Path = ROOT,
    env: Mapping[str, str] = os.environ,
    runner: CommandRunner = default_command_runner,
    manual_bootloader_check: bool = False,
    timeout_seconds: int = 10,
) -> FastbootEvidence:
    blockers: list[str] = []
    warnings: list[str] = []
    commands: list[dict[str, object]] = []
    fastboot = trusted_fastboot_path(env)
    if fastboot is None:
        blockers.append("trusted Android SDK fastboot executable is unavailable")
        return build_evidence(
            ok=False,
            status=FastbootStatus.BLOCKED,
            fastboot_path="",
            version="",
            manual_bootloader_check=manual_bootloader_check,
            bootloader_device_visible=False,
            bootloader_device_count=0,
            commands=tuple(commands),
            blockers=tuple(blockers),
            warnings=tuple(warnings),
        )

    version_result = runner((str(fastboot), "--version"), root, timeout_seconds)
    commands.append(command_evidence("fastboot --version", version_result))
    version = parse_fastboot_version(version_result.stdout or version_result.stderr)
    if version_result.exit_code != 0:
        blockers.append("fastboot --version failed")
    if not version:
        blockers.append("fastboot version could not be parsed")

    bootloader_device_count = 0
    if manual_bootloader_check:
        devices_result = runner((str(fastboot), "devices"), root, timeout_seconds)
        commands.append(command_evidence("fastboot devices", devices_result))
        devices = parse_fastboot_devices(devices_result.stdout)
        bootloader_device_count = len(devices)
        if devices_result.exit_code != 0:
            blockers.append("fastboot devices failed")
        elif not devices:
            blockers.append("no manually booted fastboot device is visible")
    else:
        warnings.append("manual bootloader visibility was not checked; do not reboot automatically")

    status = fastboot_status(
        blockers=blockers,
        manual_bootloader_check=manual_bootloader_check,
        bootloader_device_count=bootloader_device_count,
    )
    return build_evidence(
        ok=not blockers,
        status=status,
        fastboot_path=str(fastboot),
        version=version,
        manual_bootloader_check=manual_bootloader_check,
        bootloader_device_visible=bootloader_device_count > 0,
        bootloader_device_count=bootloader_device_count,
        commands=tuple(commands),
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def trusted_fastboot_path(env: Mapping[str, str]) -> Path | None:
    sdk_root = first_existing_path(default_sdk_roots(env))
    if sdk_root is None:
        return None
    fastboot_name = "fastboot.exe" if platform.system() == "Windows" else "fastboot"
    sdk = sdk_root.expanduser()
    platform_tools = sdk / "platform-tools"
    fastboot = platform_tools / fastboot_name
    if sdk.is_symlink() or platform_tools.is_symlink() or fastboot.is_symlink():
        return None
    resolved = fastboot.resolve()
    try:
        resolved.relative_to(platform_tools.resolve())
    except ValueError:
        return None
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return None
    return resolved


def parse_fastboot_version(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.lower().startswith("fastboot version"):
            return line.removeprefix("fastboot version").strip()[:80]
    return ""


def parse_fastboot_devices(text: str) -> tuple[str, ...]:
    devices: list[str] = []
    for raw_line in text.splitlines():
        match = FASTBOOT_DEVICE_LINE_PATTERN.match(raw_line.strip())
        if match is None:
            continue
        serial = match.group("serial")
        if SERIAL_PATTERN.fullmatch(serial):
            devices.append(serial)
    return tuple(devices)


def fastboot_status(
    *,
    blockers: Sequence[str],
    manual_bootloader_check: bool,
    bootloader_device_count: int,
) -> FastbootStatus:
    if blockers:
        return FastbootStatus.BLOCKED
    if manual_bootloader_check and bootloader_device_count > 0:
        return FastbootStatus.MANUAL_BOOTLOADER_VISIBLE
    return FastbootStatus.HOST_READY


def build_evidence(
    *,
    ok: bool,
    status: FastbootStatus,
    fastboot_path: str,
    version: str,
    manual_bootloader_check: bool,
    bootloader_device_visible: bool,
    bootloader_device_count: int,
    commands: tuple[dict[str, object], ...],
    blockers: tuple[str, ...],
    warnings: tuple[str, ...],
) -> FastbootEvidence:
    return FastbootEvidence(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=ok,
        status=status,
        destructive_actions="withheld",
        host={
            "fastboot": "available" if fastboot_path else "missing",
            "fastboot_path": redact_path(fastboot_path),
            "fastboot_version": version,
        },
        manual_bootloader_check={
            "requested": manual_bootloader_check,
            "bootloader_device_visible": bootloader_device_visible,
            "bootloader_device_count": bootloader_device_count,
            "serials_redacted": True,
        },
        commands=commands,
        blockers=blockers,
        warnings=warnings,
    )


def command_evidence(label: str, result: CommandResult) -> dict[str, object]:
    if not command_label_allowed(label):
        raise ValueError("fastboot evidence command must be read-only")
    return {
        "label": label,
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "stdout": redact_fastboot_output(result.stdout),
        "stderr": redact_fastboot_output(result.stderr),
    }


def command_label_allowed(label: str) -> bool:
    normalized = " ".join(label.lower().split())
    return normalized in READ_ONLY_FASTBOOT_LABELS and not command_has_destructive_term(normalized)


def command_has_destructive_term(label: str) -> bool:
    tokens = label.lower().split()
    if len(tokens) < 2 or tokens[0] != "fastboot":
        return True
    subcommand = tokens[1]
    return subcommand in DESTRUCTIVE_FASTBOOT_SUBCOMMANDS or tokens[1:3] in (
        ["flashing", "unlock"],
        ["oem", "unlock"],
    )


def redact_fastboot_output(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = FASTBOOT_DEVICE_LINE_PATTERN.match(line)
        if match:
            lines.append(line.replace(match.group("serial"), "<device-serial>", 1))
        else:
            lines.append(redact_paths(line[:240]))
    return "\n".join(lines)


def redact_paths(text: str) -> str:
    return ABSOLUTE_POSIX_PATH.sub("<path>", ABSOLUTE_WINDOWS_PATH.sub("<path>", text))


def redact_path(path: str) -> str:
    if not path:
        return ""
    return "<android-sdk>/platform-tools/fastboot"


def render_json(evidence: FastbootEvidence) -> str:
    return json.dumps(asdict(evidence), indent=2) + "\n"


def render_text(evidence: FastbootEvidence) -> str:
    lines = [
        "GOFFY ROM fastboot evidence",
        f"schema: {evidence.schema_version}",
        f"overall: {'PASS' if evidence.ok else 'BLOCKED'}",
        f"status: {evidence.status}",
        f"destructive actions: {evidence.destructive_actions}",
        f"fastboot: {evidence.host['fastboot']}",
        f"version: {evidence.host['fastboot_version'] or 'missing'}",
    ]
    if evidence.manual_bootloader_check["requested"]:
        lines.append(
            "manual bootloader visible: "
            f"{str(evidence.manual_bootloader_check['bootloader_device_visible']).lower()}"
        )
    if evidence.blockers:
        lines.append("blockers:")
        lines.extend(f"- {item}" for item in evidence.blockers)
    if evidence.warnings:
        lines.append("warnings:")
        lines.extend(f"- {item}" for item in evidence.warnings)
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create read-only GOFFY ROM-0 fastboot host/manual-mode evidence without "
            "rebooting, unlocking, flashing, or erasing the phone."
        ),
    )
    parser.add_argument(
        "--manual-bootloader-check",
        action="store_true",
        help=(
            "Run only fastboot devices after the human manually enters bootloader mode. "
            "This script never reboots the phone."
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path under .goffy-validation.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = ROOT
    try:
        evidence = create_fastboot_evidence(
            root=root,
            manual_bootloader_check=args.manual_bootloader_check,
            timeout_seconds=args.timeout_seconds,
            runner=default_command_runner,
        )
        text = render_json(evidence)
        write_output(args.output, text, root=root)
        if args.json:
            print(text, end="")
        else:
            print(render_text(evidence))
            print(f"wrote ROM fastboot evidence to {args.output}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0 if evidence.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
