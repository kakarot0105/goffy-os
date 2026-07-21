from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_moto_g_device_smoke import (  # noqa: E402
    CommandRunner,
    DeviceTarget,
    StepStatus,
    adb_command,
    default_command_runner,
    display_adb_command,
    resolve_device_target,
    trusted_adb_path,
)
from scripts.run_moto_g_modeldebug_observation_smoke import (  # noqa: E402
    MODEL_DEBUG_PACKAGE_NAME,
)
from scripts.verify_modeldebug_acceptance import (  # noqa: E402
    DEFAULT_MAX_IDLE_PSS_KB,
    DEFAULT_MAX_OBSERVATION_MILLIS,
    DEFAULT_MAX_RUN_PSS_KB,
    DEFAULT_MIN_IDLE_SECONDS,
    IDLE_EVIDENCE_SCHEMA_VERSION,
    REQUIRED_LOGCAT_MARKERS,
    is_sha256,
    parse_total_pss_kb,
    validate_observation_report,
)

DEFAULT_OUTPUT = ROOT / ".goffy-validation" / "modeldebug-observation-smoke" / "idle-cleanup.json"


@dataclass(frozen=True)
class IdleCleanupStep:
    name: str
    status: StepStatus
    command: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class ModelDebugIdleCleanupEvidence:
    schema_version: str
    ok: bool
    executed: bool
    waited_seconds: int | None
    model_sha256: str | None
    provider_closed_after_idle: bool | None
    process_running_after_idle: bool | None
    total_pss_kb: int | None
    observation_engine_scope_closed: bool | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    steps: tuple[IdleCleanupStep, ...]


def build_evidence(
    *,
    root: Path = ROOT,
    execute: bool = False,
    wait_seconds: int = DEFAULT_MIN_IDLE_SECONDS,
    timeout_seconds: int = 30,
    max_idle_pss_kb: int = DEFAULT_MAX_IDLE_PSS_KB,
    model_sha256: str | None = None,
    observation_report: Path | None = None,
    device_serial: str | None = None,
    runner: CommandRunner = default_command_runner,
    env: Mapping[str, str] | None = None,
    sleep: Callable[[int], None] = time.sleep,
) -> ModelDebugIdleCleanupEvidence:
    resolved_root = root.resolve()
    (
        resolved_model_sha,
        observation_scope_closed,
        observation_blockers,
    ) = resolve_observation_context(
        model_sha256=model_sha256,
        observation_report=observation_report,
        require_report=execute,
    )
    plan_steps = planned_steps(wait_seconds=wait_seconds)
    if not execute:
        return ModelDebugIdleCleanupEvidence(
            schema_version=IDLE_EVIDENCE_SCHEMA_VERSION,
            ok=False,
            executed=False,
            waited_seconds=None,
            model_sha256=resolved_model_sha,
            provider_closed_after_idle=None,
            process_running_after_idle=None,
            total_pss_kb=None,
            observation_engine_scope_closed=observation_scope_closed,
            blockers=(
                "not executed; rerun with --execute to collect evidence",
                *observation_blockers,
            ),
            warnings=(),
            steps=plan_steps,
        )

    blockers = list(observation_blockers)
    if wait_seconds < 0:
        blockers.append("wait_seconds must be non-negative")
    if wait_seconds < DEFAULT_MIN_IDLE_SECONDS:
        blockers.append(f"wait_seconds must be at least {DEFAULT_MIN_IDLE_SECONDS}")
    if timeout_seconds < 10:
        blockers.append("timeout_seconds must be at least 10")
    if max_idle_pss_kb <= 0:
        blockers.append("max_idle_pss_kb must be positive")
    if blockers:
        return failed_evidence(
            executed=False,
            model_sha256=resolved_model_sha,
            blockers=tuple(blockers),
            steps=plan_steps,
        )

    adb = trusted_adb_path(env) if env is not None else trusted_adb_path()
    if adb is None:
        return failed_evidence(
            executed=False,
            model_sha256=resolved_model_sha,
            blockers=("trusted Android SDK adb executable is unavailable",),
            steps=plan_steps,
        )

    target, target_step = resolve_device_target(
        adb=adb,
        root=resolved_root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        requested_serial=device_serial,
    )
    steps: list[IdleCleanupStep] = [
        IdleCleanupStep(
            name=target_step.name,
            status=target_step.status,
            command=target_step.command,
            detail=target_step.detail,
        )
    ]
    if target is None or target_step.status is not StepStatus.OK:
        return failed_evidence(
            executed=False,
            model_sha256=resolved_model_sha,
            blockers=(target_step.detail or "Moto G target unavailable",),
            steps=tuple(steps),
        )

    sleep(wait_seconds)
    steps.append(
        IdleCleanupStep(
            name="Wait for modelDebug idle cleanup",
            status=StepStatus.OK,
            detail=f"waited {wait_seconds} seconds before read-only idle probes",
        )
    )

    pid, pid_step = read_modeldebug_pid(
        root=resolved_root,
        adb=adb,
        target=target,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    steps.append(pid_step)
    if pid_step.status is StepStatus.FAIL:
        return ModelDebugIdleCleanupEvidence(
            schema_version=IDLE_EVIDENCE_SCHEMA_VERSION,
            ok=False,
            executed=True,
            waited_seconds=wait_seconds,
            model_sha256=resolved_model_sha,
            provider_closed_after_idle=False,
            process_running_after_idle=None,
            total_pss_kb=None,
            observation_engine_scope_closed=observation_scope_closed,
            blockers=("modelDebug process status probe failed",),
            warnings=(),
            steps=tuple(steps),
        )
    process_running = pid is not None

    total_pss: int | None = None
    if process_running:
        total_pss, mem_step = read_modeldebug_pss(
            root=resolved_root,
            adb=adb,
            target=target,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        steps.append(mem_step)

    blockers = []
    warnings = []
    if not observation_scope_closed:
        blockers.append("observation report logcat is missing observation_engine_scope_closed")
    if process_running:
        if total_pss is None:
            blockers.append("modelDebug process is running but TOTAL PSS could not be parsed")
        elif total_pss > max_idle_pss_kb:
            blockers.append(f"idle cleanup TOTAL PSS exceeds {max_idle_pss_kb} KB")
        else:
            blockers.append("modelDebug process is still running after idle wait")
            warnings.append("modelDebug process remained below idle PSS budget")

    provider_closed = observation_scope_closed is True and not process_running
    if not provider_closed:
        blockers.append("idle evidence does not satisfy provider_closed_after_idle")

    deduped_blockers = tuple(dict.fromkeys(blockers))
    return ModelDebugIdleCleanupEvidence(
        schema_version=IDLE_EVIDENCE_SCHEMA_VERSION,
        ok=not deduped_blockers,
        executed=True,
        waited_seconds=wait_seconds,
        model_sha256=resolved_model_sha,
        provider_closed_after_idle=provider_closed,
        process_running_after_idle=process_running,
        total_pss_kb=total_pss,
        observation_engine_scope_closed=observation_scope_closed,
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        steps=tuple(steps),
    )


def planned_steps(*, wait_seconds: int) -> tuple[IdleCleanupStep, ...]:
    return (
        IdleCleanupStep(
            name="Verify Moto G target",
            status=StepStatus.PLANNED,
            command=("adb", "devices", "-l"),
            detail="would require exactly one approved Moto G or --device-serial",
        ),
        IdleCleanupStep(
            name="Wait for modelDebug idle cleanup",
            status=StepStatus.PLANNED,
            detail=f"would wait {wait_seconds} seconds before read-only idle probes",
        ),
        IdleCleanupStep(
            name="Read modelDebug process status",
            status=StepStatus.PLANNED,
            command=("adb", "-s", "<device-serial>", "shell", "pidof", MODEL_DEBUG_PACKAGE_NAME),
            detail="would check whether the modelDebug process remains running",
        ),
    )


def failed_evidence(
    *,
    executed: bool,
    model_sha256: str | None,
    blockers: tuple[str, ...],
    steps: tuple[IdleCleanupStep, ...],
) -> ModelDebugIdleCleanupEvidence:
    return ModelDebugIdleCleanupEvidence(
        schema_version=IDLE_EVIDENCE_SCHEMA_VERSION,
        ok=False,
        executed=executed,
        waited_seconds=None,
        model_sha256=model_sha256,
        provider_closed_after_idle=None,
        process_running_after_idle=None,
        total_pss_kb=None,
        observation_engine_scope_closed=None,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=(),
        steps=steps,
    )


def read_modeldebug_pid(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> tuple[str | None, IdleCleanupStep]:
    command = adb_command(adb, target, "shell", "pidof", MODEL_DEBUG_PACKAGE_NAME)
    result = runner(command, root, timeout_seconds)
    pid = result.stdout.strip().split()[0] if result.exit_code == 0 else ""
    if pid.isdigit():
        return (
            pid,
            IdleCleanupStep(
                name="Read modelDebug process status",
                status=StepStatus.OK,
                command=display_adb_command(adb, "shell", "pidof", MODEL_DEBUG_PACKAGE_NAME),
                detail="modelDebug process remains running",
            ),
        )
    if result.timed_out or result.stderr.strip() or result.stdout.strip():
        detail = result.stderr.strip() or result.stdout.strip() or "pidof timed out"
        return (
            None,
            IdleCleanupStep(
                name="Read modelDebug process status",
                status=StepStatus.FAIL,
                command=display_adb_command(adb, "shell", "pidof", MODEL_DEBUG_PACKAGE_NAME),
                detail=detail,
            ),
        )
    return (
        None,
        IdleCleanupStep(
            name="Read modelDebug process status",
            status=StepStatus.OK,
            command=display_adb_command(adb, "shell", "pidof", MODEL_DEBUG_PACKAGE_NAME),
            detail="modelDebug process is not running",
        ),
    )


def read_modeldebug_pss(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> tuple[int | None, IdleCleanupStep]:
    command = adb_command(adb, target, "shell", "dumpsys", "meminfo", MODEL_DEBUG_PACKAGE_NAME)
    result = runner(command, root, timeout_seconds)
    total_pss = parse_total_pss_kb(result.stdout) if result.exit_code == 0 else None
    status = StepStatus.OK if total_pss is not None else StepStatus.FAIL
    detail = f"TOTAL PSS {total_pss} KB" if total_pss is not None else "TOTAL PSS unavailable"
    return (
        total_pss,
        IdleCleanupStep(
            name="Capture modelDebug idle memory snapshot",
            status=status,
            command=display_adb_command(
                adb,
                "shell",
                "dumpsys",
                "meminfo",
                MODEL_DEBUG_PACKAGE_NAME,
            ),
            detail=detail,
        ),
    )


def resolve_observation_context(
    *,
    model_sha256: str | None,
    observation_report: Path | None,
    require_report: bool,
) -> tuple[str | None, bool | None, tuple[str, ...]]:
    if model_sha256 is not None:
        normalized = model_sha256.strip()
        if not is_sha256(normalized):
            return (None, None, ("model_sha256 is invalid",))
    else:
        normalized = None
    if observation_report is None:
        blocker = "provide --observation-report" if require_report else ""
        blockers = (blocker,) if blocker else ()
        return (normalized, None, blockers)
    try:
        accepted = validate_observation_report(
            observation_report,
            max_observation_millis=DEFAULT_MAX_OBSERVATION_MILLIS,
            max_run_pss_kb=DEFAULT_MAX_RUN_PSS_KB,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return (normalized, None, (f"{observation_report}: {exc}",))
    model_hash = accepted.model_sha256
    if normalized is not None and normalized != model_hash:
        return (model_hash, None, ("model_sha256 does not match observation report",))
    output_dir = Path(accepted.output_directory)
    logcat_path = output_dir / "modeldebug-logcat.txt"
    try:
        logcat = logcat_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return (model_hash, None, (f"{logcat_path}: {exc}",))
    marker_seen = all(marker in logcat for marker in REQUIRED_LOGCAT_MARKERS)
    blockers = () if marker_seen else ("observation report logcat is missing teardown marker",)
    return (model_hash, marker_seen, blockers)


def render_json(report: ModelDebugIdleCleanupEvidence) -> str:
    return json.dumps(asdict(report), indent=2)


def write_report(report: ModelDebugIdleCleanupEvidence, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{render_json(report)}\n", encoding="utf-8")
    return output


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect read-only Moto G modelDebug idle-cleanup evidence.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--device-serial")
    parser.add_argument("--observation-report", type=Path)
    parser.add_argument("--model-sha256")
    parser.add_argument("--wait-seconds", type=int, default=DEFAULT_MIN_IDLE_SECONDS)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--max-idle-pss-kb", type=int, default=DEFAULT_MAX_IDLE_PSS_KB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def render_text(report: ModelDebugIdleCleanupEvidence, output: Path) -> str:
    lines = [
        "GOFFY modelDebug idle-cleanup evidence",
        f"executed: {str(report.executed).lower()}",
        f"status: {'OK' if report.ok else 'BLOCKED'}",
        f"output: {output}",
    ]
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_evidence(
        execute=args.execute,
        wait_seconds=args.wait_seconds,
        timeout_seconds=args.timeout_seconds,
        max_idle_pss_kb=args.max_idle_pss_kb,
        model_sha256=args.model_sha256,
        observation_report=args.observation_report,
        device_serial=args.device_serial,
    )
    write_report(report, args.output)
    print(render_json(report) if args.json else render_text(report, args.output))
    if not args.execute:
        return 0
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
