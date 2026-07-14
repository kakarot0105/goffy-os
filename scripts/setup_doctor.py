from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.android_preflight import Check as AndroidCheck  # noqa: E402
from scripts.android_preflight import collect_checks as collect_android_checks  # noqa: E402
from scripts.android_preflight import (  # noqa: E402
    default_sdk_roots,
    first_existing_path,
    resolve_adb,
)

MIN_PYTHON = (3, 12)
HUB_REVERSE_ENDPOINT = "tcp:8787"
DEV_MODULES = {
    "build": "build",
    "fastapi": "fastapi",
    "httpx2": "httpx",
    "jsonschema": "jsonschema",
    "mcp": "mcp",
    "mypy": "mypy",
    "pydantic": "pydantic",
    "pytest": "pytest",
    "pytest-asyncio": "pytest_asyncio",
    "pyyaml": "yaml",
    "ruff": "ruff",
    "segno": "segno",
    "uvicorn": "uvicorn",
    "websockets": "websockets",
}
JSON_SCHEMA_VERSION = "goffy.setup-doctor.v1"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
ABSOLUTE_POSIX_PATH = re.compile(r"(?<![>\w])/(?!\s)(?:[^;\n\r,)]+)")
OTHER_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class DoctorCheck:
    category: str
    name: str
    ok: bool
    detail: str
    remediation: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]
    repo_root: Path = ROOT
    home: Path = Path.home()

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


ModuleFinder = Callable[[str], bool]
AndroidCollector = Callable[[Path], Sequence[AndroidCheck]]
DeviceCommandRunner = Callable[[Sequence[str], Path, int], "DeviceCommandResult"]


@dataclass(frozen=True)
class DeviceCommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class AdbDeviceSummary:
    serial: str
    status: str


@dataclass(frozen=True)
class AdbReverseSummary:
    serial: str
    local: str
    remote: str


def default_module_finder(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def default_device_command_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> DeviceCommandResult:
    try:
        completed = subprocess.run(  # noqa: S603,S607
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
        return DeviceCommandResult(124, stdout, stderr, timed_out=True)
    return DeviceCommandResult(completed.returncode, completed.stdout, completed.stderr)


def collect_python_checks(
    *,
    version_info: tuple[int, int, int] | None = None,
    executable: str = sys.executable,
    module_finder: ModuleFinder = default_module_finder,
) -> list[DoctorCheck]:
    version = version_info if version_info is not None else sys.version_info[:3]
    version_label = ".".join(str(part) for part in version)
    python_ok = version[:2] >= MIN_PYTHON
    checks = [
        DoctorCheck(
            category="python",
            name="Python runtime",
            ok=python_ok,
            detail=f"Python {version_label} at {executable}",
            remediation=(
                "" if python_ok else "Install Python 3.12+ and recreate the GOFFY virtualenv."
            ),
        )
    ]

    missing: list[str] = []
    for package, module in DEV_MODULES.items():
        if not module_finder(module):
            missing.append(package)

    checks.append(
        DoctorCheck(
            category="python",
            name="Python dev dependencies",
            ok=not missing,
            detail=(
                "all required dev modules importable"
                if not missing
                else f"missing modules for packages: {', '.join(sorted(missing))}"
            ),
            remediation=(
                ""
                if not missing
                else "Run `.venv/bin/python -m pip install -e '.[dev]'` from the repo root."
            ),
        )
    )
    return checks


def collect_doctor_report(
    *,
    root: Path = ROOT,
    module_finder: ModuleFinder = default_module_finder,
    android_collector: AndroidCollector = lambda root: collect_android_checks(root=root),
    include_python: bool = True,
    include_device: bool = False,
    device_runner: DeviceCommandRunner = default_device_command_runner,
) -> DoctorReport:
    checks = collect_python_checks(module_finder=module_finder) if include_python else []
    android_checks = tuple(android_collector(root))
    checks.extend(
        DoctorCheck(
            category="android",
            name=check.name,
            ok=check.ok,
            detail=check.detail,
            remediation="" if check.ok else check.remediation,
        )
        for check in android_checks
    )
    if include_device:
        adb_check = next((check for check in android_checks if check.name == "adb"), None)
        if adb_check is not None and not adb_check.ok:
            checks.append(
                DoctorCheck(
                    category="device",
                    name="Device diagnostics",
                    ok=False,
                    detail="skipped because Android adb preflight failed",
                    remediation=(
                        "Fix the Android adb preflight first, then rerun with --include-device."
                    ),
                )
            )
        else:
            checks.extend(collect_device_checks(root=root, runner=device_runner))
    return DoctorReport(tuple(checks), repo_root=root.resolve())


def discover_adb_path() -> Path | None:
    sdk_root = first_existing_path(default_sdk_roots(os.environ))
    adb = resolve_adb(sdk_root, shutil.which("adb"))
    if adb is None:
        return None
    return adb if os.access(adb, os.X_OK) else None


def parse_adb_devices(output: str) -> list[AdbDeviceSummary]:
    devices: list[AdbDeviceSummary] = []
    allowed_statuses = {
        "authorizing",
        "bootloader",
        "detached",
        "device",
        "host",
        "no permissions",
        "nopermission",
        "offline",
        "recovery",
        "rescue",
        "sideload",
        "unauthorized",
    }
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*") or stripped == "List of devices attached":
            continue
        parts = stripped.split()
        if len(parts) >= 3 and parts[1] == "no" and parts[2] == "permissions":
            devices.append(AdbDeviceSummary(serial=parts[0], status="no permissions"))
        elif len(parts) >= 2 and parts[1] in allowed_statuses:
            devices.append(AdbDeviceSummary(serial=parts[0], status=parts[1]))
    return devices


def parse_adb_reverse_list(output: str) -> list[AdbReverseSummary]:
    reverse_entries: list[AdbReverseSummary] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        parts = stripped.split()
        if len(parts) >= 3 and parts[1].startswith("tcp:") and parts[2].startswith("tcp:"):
            reverse_entries.append(
                AdbReverseSummary(serial=parts[0], local=parts[1], remote=parts[2])
            )
    return reverse_entries


def count_statuses(devices: Sequence[AdbDeviceSummary]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for device in devices:
        counts[device.status] = counts.get(device.status, 0) + 1
    return counts


def render_status_counts(counts: Mapping[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{status}:{count}" for status, count in sorted(counts.items()))


def collect_device_checks(
    *,
    root: Path = ROOT,
    runner: DeviceCommandRunner = default_device_command_runner,
    timeout_seconds: int = 5,
    adb: Path | None = None,
) -> list[DoctorCheck]:
    resolved_adb = adb if adb is not None else discover_adb_path()
    if resolved_adb is None:
        return [
            DoctorCheck(
                category="device",
                name="adb executable",
                ok=False,
                detail="adb unavailable",
                remediation="Install Android SDK Platform Tools and ensure adb is on PATH.",
            )
        ]

    device_result = runner((str(resolved_adb), "devices", "-l"), root, timeout_seconds)
    if device_result.timed_out:
        return [
            DoctorCheck(
                category="device",
                name="adb devices",
                ok=False,
                detail="adb devices timed out",
                remediation="Reconnect the phone and retry after approving USB debugging.",
            )
        ]
    if device_result.exit_code != 0:
        return [
            DoctorCheck(
                category="device",
                name="adb devices",
                ok=False,
                detail="adb devices failed",
                remediation="Restart adb or reconnect the phone, then rerun setup doctor.",
            )
        ]

    devices = parse_adb_devices(device_result.stdout)
    status_counts = count_statuses(devices)
    authorized_count = status_counts.get("device", 0)
    authorized_serials = {device.serial for device in devices if device.status == "device"}
    checks = [
        DoctorCheck(
            category="device",
            name="Authorized Android device",
            ok=authorized_count > 0,
            detail=(
                f"authorized:{authorized_count}; statuses: {render_status_counts(status_counts)}"
            ),
            remediation=(
                ""
                if authorized_count > 0
                else "Connect the Moto G over USB and approve this Mac for USB debugging."
            ),
        )
    ]
    if authorized_count == 0:
        return checks

    reverse_result = runner((str(resolved_adb), "reverse", "--list"), root, timeout_seconds)
    if reverse_result.timed_out:
        checks.append(
            DoctorCheck(
                category="device",
                name="Hub USB reverse",
                ok=False,
                detail="adb reverse --list timed out",
                remediation="Retry `adb reverse tcp:8787 tcp:8787` after reconnecting the phone.",
            )
        )
        return checks
    if reverse_result.exit_code != 0:
        checks.append(
            DoctorCheck(
                category="device",
                name="Hub USB reverse",
                ok=False,
                detail="adb reverse --list failed",
                remediation="Run `adb reverse tcp:8787 tcp:8787` after the phone is authorized.",
            )
        )
        return checks

    reverse_entries = parse_adb_reverse_list(reverse_result.stdout)
    reverse_ready = any(
        (entry.serial == "host" or entry.serial in authorized_serials)
        and entry.local == HUB_REVERSE_ENDPOINT
        and entry.remote == HUB_REVERSE_ENDPOINT
        for entry in reverse_entries
    )
    checks.append(
        DoctorCheck(
            category="device",
            name="Hub USB reverse",
            ok=reverse_ready,
            detail=(
                "tcp:8787 reverse is active"
                if reverse_ready
                else f"tcp:8787 reverse missing; reverse entries:{len(reverse_entries)}"
            ),
            remediation="" if reverse_ready else "Run `adb reverse tcp:8787 tcp:8787`.",
        )
    )
    return checks


def redact_paths(value: str, *, report: DoctorReport) -> str:
    redacted = value
    replacements = [
        (str(report.repo_root), "<repo>"),
        (str(report.home), "<home>"),
    ]
    for source, replacement in replacements:
        if source:
            redacted = redacted.replace(source, replacement)
    return ABSOLUTE_POSIX_PATH.sub("<path>", redacted)


def safe_text(value: str, *, report: DoctorReport) -> str:
    sanitized = redact_paths(value, report=report)
    sanitized = ANSI_ESCAPE.sub("", sanitized)
    sanitized = sanitized.replace("\\", "\\\\")
    sanitized = sanitized.replace("\r", "\\r").replace("\n", "\\n")
    return OTHER_CONTROL.sub(lambda match: f"\\x{ord(match.group(0)):02x}", sanitized)


def render_text(report: DoctorReport) -> str:
    lines = ["GOFFY setup doctor"]
    current_category = ""
    for check in report.checks:
        if check.category != current_category:
            current_category = check.category
            lines.append("")
            lines.append(f"{current_category.upper()}")
        status = "OK" if check.ok else "FAIL"
        lines.append(f"[{status}] {check.name}: {safe_text(check.detail, report=report)}")
        if not check.ok:
            lines.append(f"       fix: {safe_text(check.remediation, report=report)}")
    lines.append("")
    if report.ok:
        lines.append(
            "Ready for full local verification with `.venv/bin/python scripts/verify_all.py`."
        )
    else:
        lines.append(
            "Resolve failed checks before expecting full Android verification or "
            "physical-device tests."
        )
    return "\n".join(lines)


def render_json(report: DoctorReport) -> str:
    payload: Mapping[str, object] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": report.ok,
        "checks": [
            asdict(
                DoctorCheck(
                    category=check.category,
                    name=check.name,
                    ok=check.ok,
                    detail=redact_paths(check.detail, report=report),
                    remediation=redact_paths(check.remediation, report=report),
                )
            )
            for check in report.checks
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--android-only",
        action="store_true",
        help="Skip Python dev dependency checks and report only Android/device readiness.",
    )
    parser.add_argument(
        "--include-device",
        action="store_true",
        help="Also run read-only adb device and USB reverse diagnostics.",
    )
    args = parser.parse_args(argv)

    report = collect_doctor_report(
        root=Path(args.repo_root).resolve(),
        include_python=not args.android_only,
        include_device=args.include_device,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
