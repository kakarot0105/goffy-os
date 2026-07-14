from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = ROOT / "protocol" / "python"
if __package__ in {None, ""}:
    for import_root in (ROOT, PROTOCOL_ROOT):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

from scripts.android_preflight import default_sdk_roots, first_existing_path  # noqa: E402
from scripts.setup_doctor import (  # noqa: E402
    DeviceCommandResult,
    DoctorCheck,
    DoctorReport,
    collect_device_checks,
    collect_doctor_report,
    discover_adb_path,
    redact_paths,
    safe_text,
)
from scripts.verify_moto_g_readiness import (  # noqa: E402
    DEBUG_APK_RELATIVE_PATH,
    ReadinessReport,
    collect_readiness_report,
    existing_directory,
)
from scripts.verify_moto_g_readiness import (  # noqa: E402
    render_json as render_readiness_json,
)

JSON_SCHEMA_VERSION = "goffy.moto-g-usb-setup.v1"
HUB_REVERSE_ENDPOINT = "tcp:8787"
IGNORABLE_EXECUTION_BLOCKERS = frozenset({("device", "Hub USB reverse")})


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
class UsbSetupStep:
    name: str
    status: StepStatus
    command: tuple[str, ...] = ()
    mutates_device: bool = False
    detail: str = ""
    remediation: str = ""


@dataclass(frozen=True)
class UsbSetupReport:
    executed: bool
    readiness_ok: bool
    readiness_blockers: tuple[str, ...]
    steps: tuple[UsbSetupStep, ...]
    repo_root: Path = ROOT
    home: Path = Path.home()

    @property
    def ok(self) -> bool:
        if self.readiness_blockers:
            return False
        return all(step.status in {StepStatus.PLANNED, StepStatus.OK} for step in self.steps)

    @property
    def setup_complete(self) -> bool:
        return self.executed and all(step.status is StepStatus.OK for step in self.steps)


CommandRunner = Callable[[Sequence[str], Path, int], CommandResult]


def default_command_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
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
        return CommandResult(124, stdout, stderr, timed_out=True)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def readiness_blockers_for_execution(report: ReadinessReport) -> tuple[str, ...]:
    blockers: list[str] = []
    for check in report.checks:
        if check.ok or (check.category, check.name) in IGNORABLE_EXECUTION_BLOCKERS:
            continue
        blockers.append(f"{check.category}/{check.name}")
    return tuple(blockers)


def setup_commands(root: Path, adb: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    apk = root / DEBUG_APK_RELATIVE_PATH
    return (
        (str(adb), "reverse", HUB_REVERSE_ENDPOINT, HUB_REVERSE_ENDPOINT),
        (str(adb), "install", "-r", str(apk)),
    )


def trusted_adb_path(env: Mapping[str, str] = os.environ) -> Path | None:
    sdk_root = first_existing_path(default_sdk_roots(env))
    if sdk_root is None:
        return None
    adb_name = "adb.exe" if platform.system() == "Windows" else "adb"
    adb = (sdk_root / "platform-tools" / adb_name).expanduser().resolve()
    if not adb.is_file() or not os.access(adb, os.X_OK):
        return None
    return adb


def collect_trusted_device_checks(
    *,
    root: Path,
    adb: Path | None,
    runner: CommandRunner = default_command_runner,
    timeout_seconds: int = 5,
) -> list[DoctorCheck]:
    if adb is None:
        return [
            DoctorCheck(
                category="device",
                name="trusted SDK adb executable",
                ok=False,
                detail="trusted SDK platform-tools adb unavailable",
                remediation="Install Android SDK Platform Tools and set ANDROID_HOME.",
            )
        ]

    def device_runner(command: Sequence[str], cwd: Path, timeout: int) -> DeviceCommandResult:
        result = runner(command, cwd, timeout)
        return DeviceCommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
        )

    return collect_device_checks(
        root=root,
        runner=device_runner,
        timeout_seconds=timeout_seconds,
        adb=adb,
    )


def collect_setup_readiness(
    *,
    root: Path,
    adb: Path | None,
    runner: CommandRunner = default_command_runner,
    timeout_seconds: int = 5,
) -> ReadinessReport:
    def doctor_collector(doctor_root: Path) -> DoctorReport:
        base_report = collect_doctor_report(
            root=doctor_root,
            include_python=False,
            include_device=False,
        )
        device_checks = collect_trusted_device_checks(
            root=doctor_root,
            adb=adb,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        return DoctorReport(
            checks=(*base_report.checks, *device_checks),
            repo_root=base_report.repo_root,
            home=base_report.home,
        )

    return collect_readiness_report(root=root, doctor_collector=doctor_collector)


def mutating_root_blocker(root: Path, trusted_root: Path = ROOT) -> str | None:
    if root.resolve() != trusted_root.resolve():
        return "repo-root/mutating mode only supports the checked-out GOFFY repository root"
    return None


def planned_steps(root: Path, adb: Path | None = None) -> tuple[UsbSetupStep, ...]:
    adb_path = adb or Path("<adb>")
    reverse, install = setup_commands(root, adb_path)
    return (
        UsbSetupStep(
            name="Configure Hub USB reverse",
            status=StepStatus.PLANNED,
            command=reverse,
            mutates_device=True,
            detail="would map phone tcp:8787 to local Hub tcp:8787",
        ),
        UsbSetupStep(
            name="Install debug APK",
            status=StepStatus.PLANNED,
            command=install,
            mutates_device=True,
            detail="would install or replace the GOFFY debug APK",
        ),
    )


def execute_step(
    *,
    name: str,
    command: Sequence[str],
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> UsbSetupStep:
    result = runner(command, root, timeout_seconds)
    if result.timed_out:
        return UsbSetupStep(
            name=name,
            status=StepStatus.FAIL,
            command=tuple(command),
            mutates_device=True,
            detail="command timed out",
            remediation="Reconnect the phone and retry after confirming USB debugging.",
        )
    output = safe_output(result)
    return UsbSetupStep(
        name=name,
        status=StepStatus.OK if result.exit_code == 0 else StepStatus.FAIL,
        command=tuple(command),
        mutates_device=True,
        detail=output if output else f"exit:{result.exit_code}",
        remediation="" if result.exit_code == 0 else "Fix the reported adb failure and rerun.",
    )


def safe_output(result: CommandResult) -> str:
    text = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.exit_code == 0:
        return "exit:0"
    return "adb command failed" if text else f"exit:{result.exit_code}"


def verify_reverse_step(
    root: Path,
    *,
    adb: Path,
    runner: CommandRunner = default_command_runner,
    timeout_seconds: int = 30,
) -> UsbSetupStep:
    checks = collect_trusted_device_checks(
        root=root,
        adb=adb,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    reverse_check = next((check for check in checks if check.name == "Hub USB reverse"), None)
    if reverse_check is None:
        failed_check = next((check for check in checks if not check.ok), None)
        if failed_check is not None:
            return UsbSetupStep(
                name="Verify Hub USB reverse",
                status=StepStatus.FAIL,
                detail=f"{failed_check.name}: {failed_check.detail}",
                remediation=failed_check.remediation,
            )
        return UsbSetupStep(
            name="Verify Hub USB reverse",
            status=StepStatus.FAIL,
            detail="Hub USB reverse check unavailable",
            remediation="Run `.venv/bin/python scripts/setup_doctor.py --include-device`.",
        )
    return UsbSetupStep(
        name="Verify Hub USB reverse",
        status=StepStatus.OK if reverse_check.ok else StepStatus.FAIL,
        detail=reverse_check.detail,
        remediation=reverse_check.remediation,
    )


def build_report(
    *,
    root: Path = ROOT,
    execute: bool = False,
    confirm_device_mutation: bool = False,
    runner: CommandRunner = default_command_runner,
    timeout_seconds: int = 30,
    trusted_root: Path = ROOT,
) -> UsbSetupReport:
    plan_adb = discover_adb_path()

    if not execute:
        readiness = collect_setup_readiness(
            root=root,
            adb=trusted_adb_path(),
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        blockers = readiness_blockers_for_execution(readiness)
        return UsbSetupReport(
            executed=False,
            readiness_ok=readiness.ok,
            readiness_blockers=blockers,
            steps=planned_steps(root, plan_adb),
            repo_root=root.resolve(),
        )

    if not confirm_device_mutation:
        return UsbSetupReport(
            executed=False,
            readiness_ok=False,
            readiness_blockers=("missing explicit --confirm-device-mutation",),
            steps=planned_steps(root, plan_adb),
            repo_root=root.resolve(),
        )

    root_blocker = mutating_root_blocker(root, trusted_root)
    if root_blocker is not None:
        return UsbSetupReport(
            executed=False,
            readiness_ok=False,
            readiness_blockers=(root_blocker,),
            steps=planned_steps(root, plan_adb),
            repo_root=root.resolve(),
        )

    adb = trusted_adb_path()
    if adb is None:
        return UsbSetupReport(
            executed=False,
            readiness_ok=False,
            readiness_blockers=("device/trusted SDK adb executable",),
            steps=planned_steps(root, plan_adb),
            repo_root=root.resolve(),
        )

    readiness = collect_setup_readiness(
        root=root,
        adb=adb,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    blockers = readiness_blockers_for_execution(readiness)
    if blockers:
        return UsbSetupReport(
            executed=False,
            readiness_ok=readiness.ok,
            readiness_blockers=blockers,
            steps=planned_steps(root, plan_adb),
            repo_root=root.resolve(),
        )

    reverse, install = setup_commands(root, adb)
    steps = [
        execute_step(
            name="Configure Hub USB reverse",
            command=reverse,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
    ]
    if steps[-1].status is StepStatus.OK:
        steps.append(
            verify_reverse_step(
                root,
                adb=adb,
                runner=runner,
                timeout_seconds=timeout_seconds,
            )
        )
    else:
        steps.append(
            UsbSetupStep(
                name="Verify Hub USB reverse",
                status=StepStatus.SKIP,
                detail="skipped because reverse setup failed",
            )
        )
    if all(step.status is StepStatus.OK for step in steps):
        steps.append(
            execute_step(
                name="Install debug APK",
                command=install,
                root=root,
                runner=runner,
                timeout_seconds=timeout_seconds,
            )
        )
    else:
        steps.append(
            UsbSetupStep(
                name="Install debug APK",
                status=StepStatus.SKIP,
                command=install,
                mutates_device=True,
                detail="skipped because USB reverse verification failed",
            )
        )
    setup_complete = all(step.status is StepStatus.OK for step in steps)
    return UsbSetupReport(
        executed=True,
        readiness_ok=readiness.ok or setup_complete,
        readiness_blockers=(),
        steps=tuple(steps),
        repo_root=root.resolve(),
    )


def redaction_report(report: UsbSetupReport) -> DoctorReport:
    return DoctorReport(checks=(), repo_root=report.repo_root, home=report.home)


def format_command(command: Sequence[str], *, report: UsbSetupReport) -> str:
    redactor = redaction_report(report)
    return " ".join(safe_text(part, report=redactor) for part in command)


def render_text(report: UsbSetupReport) -> str:
    redactor = redaction_report(report)
    lines = ["GOFFY Moto G USB setup"]
    lines.append(f"mode: {'execute' if report.executed else 'plan'}")
    lines.append(f"readiness: {'ready' if report.readiness_ok else 'not-ready'}")
    if report.readiness_blockers:
        lines.append("blockers:")
        for blocker in report.readiness_blockers:
            lines.append(f"- {safe_text(blocker, report=redactor)}")
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
        if step.remediation:
            lines.append(f"       fix: {safe_text(step.remediation, report=redactor)}")
    lines.append("")
    if report.setup_complete:
        lines.append("USB setup is ready for the manual `Show my Mac status` phone smoke test.")
    elif report.ok:
        lines.append("USB setup plan is ready; no phone state was changed.")
    else:
        lines.append("Resolve blockers before treating Moto G USB setup as complete.")
    return "\n".join(lines)


def render_json(report: UsbSetupReport) -> str:
    redactor = redaction_report(report)
    payload: dict[str, object] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": report.ok,
        "setupComplete": report.setup_complete,
        "executed": report.executed,
        "readinessOk": report.readiness_ok,
        "readinessBlockers": [
            redact_paths(blocker, report=redactor) for blocker in report.readiness_blockers
        ],
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=existing_directory, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run fixed adb reverse and install commands after readiness gates pass.",
    )
    parser.add_argument(
        "--confirm-device-mutation",
        action="store_true",
        help="Required with --execute because the command mutates connected phone state.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="Timeout per adb command in seconds.",
    )
    parser.add_argument(
        "--readiness-json",
        action="store_true",
        help="Print the underlying readiness report JSON instead of setup steps.",
    )
    args = parser.parse_args(argv)

    if args.timeout_seconds <= 0 or args.timeout_seconds > 300:
        parser.error("timeout must be greater than 0 and at most 300 seconds")

    if args.readiness_json:
        readiness = collect_readiness_report(root=args.repo_root)
        print(render_readiness_json(readiness))
        return 0 if readiness.ok else 1

    report = build_report(
        root=args.repo_root,
        execute=args.execute,
        confirm_device_mutation=args.confirm_device_mutation,
        timeout_seconds=args.timeout_seconds,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
