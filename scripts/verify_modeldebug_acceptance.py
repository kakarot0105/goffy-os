from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_moto_g_modeldebug_observation_smoke import (  # noqa: E402
    DEFAULT_COMMAND,
)
from scripts.run_moto_g_modeldebug_observation_smoke import (  # noqa: E402
    JSON_SCHEMA_VERSION as OBSERVATION_SCHEMA_VERSION,
)

JSON_SCHEMA_VERSION = "goffy.modeldebug-production-acceptance.v1"
IDLE_EVIDENCE_SCHEMA_VERSION = "goffy.modeldebug-idle-cleanup-evidence.v1"
DEFAULT_MIN_RUNS = 3
DEFAULT_MAX_OBSERVATION_MILLIS = 15_000
DEFAULT_MAX_RUN_PSS_KB = 256_000
DEFAULT_MAX_IDLE_PSS_KB = 64_000
DEFAULT_MIN_IDLE_SECONDS = 60
REQUIRED_STEP_NAMES = (
    "Verify Moto G target",
    "Unsupported command observation smoke",
    "Dump UI",
    "Capture battery snapshot",
    "Capture memory snapshot",
    "Capture bounded modelDebug logcat",
)
REQUIRED_ARTIFACTS = (
    "final-ui.xml",
    "battery-after.txt",
    "meminfo-after.txt",
    "modeldebug-logcat.txt",
)
REQUIRED_UI_MARKERS = (
    "FAILED",
    "No safe deterministic route is available",
)
LOGCAT_FAILURE_MARKERS = (
    "FATAL EXCEPTION",
    "OutOfMemoryError",
    "ApplicationNotResponding",
    "ANR in dev.goffy.os.model",
)
REQUIRED_LOGCAT_MARKERS = ("observation_engine_scope_closed",)
TOTAL_PSS = re.compile(r"TOTAL\s+PSS:\s*(\d+)", re.IGNORECASE)
BATTERY_LEVEL = re.compile(r"\blevel:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class AcceptedObservationRun:
    report: str
    output_directory: str
    model_sha256: str
    elapsed_millis: int
    total_pss_kb: int | None
    battery_level: int | None


@dataclass(frozen=True)
class IdleCleanupEvidence:
    supplied: bool
    waited_seconds: int | None = None
    provider_closed_after_idle: bool | None = None
    process_running_after_idle: bool | None = None
    total_pss_kb: int | None = None


@dataclass(frozen=True)
class ModelDebugAcceptanceReport:
    schema_version: str
    ok: bool
    status: str
    min_runs: int
    max_observation_millis: int
    max_run_pss_kb: int
    max_idle_pss_kb: int
    accepted_runs: tuple[AcceptedObservationRun, ...]
    idle_cleanup: IdleCleanupEvidence
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def build_acceptance_report(
    *,
    reports: Sequence[Path],
    idle_evidence_json: Path | None,
    min_runs: int = DEFAULT_MIN_RUNS,
    max_observation_millis: int = DEFAULT_MAX_OBSERVATION_MILLIS,
    max_run_pss_kb: int = DEFAULT_MAX_RUN_PSS_KB,
    max_idle_pss_kb: int = DEFAULT_MAX_IDLE_PSS_KB,
    min_idle_seconds: int = DEFAULT_MIN_IDLE_SECONDS,
) -> ModelDebugAcceptanceReport:
    blockers: list[str] = []
    warnings: list[str] = []
    accepted_runs: list[AcceptedObservationRun] = []
    model_hashes: set[str] = set()

    if len(reports) < min_runs:
        blockers.append(f"at least {min_runs} executed modelDebug observation reports are required")

    for report_path in reports:
        try:
            accepted = validate_observation_report(
                report_path,
                max_observation_millis=max_observation_millis,
                max_run_pss_kb=max_run_pss_kb,
            )
        except ValueError as exc:
            blockers.append(f"{report_path}: {exc}")
            continue
        accepted_runs.append(accepted)
        model_hashes.add(accepted.model_sha256)
        if accepted.battery_level is not None and accepted.battery_level < 50:
            warnings.append(f"{report_path}: battery level was below 50 percent")

    if len(model_hashes) > 1:
        blockers.append("modelDebug acceptance reports must use one model SHA-256")

    expected_model_sha = next(iter(model_hashes), None)
    idle_cleanup, idle_blockers, idle_warnings = validate_idle_evidence(
        idle_evidence_json,
        expected_model_sha=expected_model_sha,
        min_idle_seconds=min_idle_seconds,
        max_idle_pss_kb=max_idle_pss_kb,
    )
    blockers.extend(idle_blockers)
    warnings.extend(idle_warnings)

    deduped_blockers = tuple(dict.fromkeys(blockers))
    return ModelDebugAcceptanceReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=not deduped_blockers,
        status="ACCEPTED" if not deduped_blockers else "BLOCKED",
        min_runs=min_runs,
        max_observation_millis=max_observation_millis,
        max_run_pss_kb=max_run_pss_kb,
        max_idle_pss_kb=max_idle_pss_kb,
        accepted_runs=tuple(accepted_runs),
        idle_cleanup=idle_cleanup,
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def validate_observation_report(
    report_path: Path,
    *,
    max_observation_millis: int,
    max_run_pss_kb: int,
) -> AcceptedObservationRun:
    payload = load_json_object(report_path)
    if payload.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("schema_version mismatch")
    if payload.get("executed") is not True:
        raise ValueError("report was not executed")
    if payload.get("ok") is not True:
        raise ValueError("report is not OK")
    if payload.get("command") != DEFAULT_COMMAND:
        raise ValueError(f"report command must be `{DEFAULT_COMMAND}`")
    elapsed = int_value(payload.get("observation_elapsed_millis"))
    if elapsed is None or elapsed <= 0:
        raise ValueError("observation_elapsed_millis is missing")
    if elapsed > max_observation_millis:
        raise ValueError(f"observation took {elapsed} ms; limit is {max_observation_millis} ms")
    model_sha = str(payload.get("model_sha256", ""))
    if not is_sha256(model_sha):
        raise ValueError("model_sha256 is missing or invalid")
    output_dir_value = str(payload.get("output_directory", ""))
    output_dir = Path(output_dir_value)
    if not output_dir.is_dir():
        raise ValueError("output_directory is missing or unavailable")

    steps = tuple(mapping_items(payload.get("steps")))
    statuses = {str(step.get("name", "")): str(step.get("status", "")) for step in steps}
    for step_name in REQUIRED_STEP_NAMES:
        if statuses.get(step_name) != "OK":
            raise ValueError(f"required step `{step_name}` was not OK")
    for artifact in REQUIRED_ARTIFACTS:
        if not (output_dir / artifact).is_file():
            raise ValueError(f"required artifact `{artifact}` is missing")

    ui_text = (output_dir / "final-ui.xml").read_text(encoding="utf-8", errors="replace")
    if not all(marker in ui_text for marker in REQUIRED_UI_MARKERS):
        raise ValueError("final-ui.xml does not prove non-executable FAILED timeline state")

    logcat = (output_dir / "modeldebug-logcat.txt").read_text(
        encoding="utf-8",
        errors="replace",
    )
    for marker in LOGCAT_FAILURE_MARKERS:
        if marker in logcat:
            raise ValueError(f"modeldebug-logcat.txt contains `{marker}`")
    for marker in REQUIRED_LOGCAT_MARKERS:
        if marker not in logcat:
            raise ValueError(f"modeldebug-logcat.txt is missing `{marker}`")

    meminfo = (output_dir / "meminfo-after.txt").read_text(
        encoding="utf-8",
        errors="replace",
    )
    total_pss = parse_total_pss_kb(meminfo)
    if total_pss is None:
        raise ValueError("meminfo-after.txt is missing TOTAL PSS")
    if total_pss > max_run_pss_kb:
        raise ValueError(f"run TOTAL PSS {total_pss} KB exceeds {max_run_pss_kb} KB")

    battery = (output_dir / "battery-after.txt").read_text(
        encoding="utf-8",
        errors="replace",
    )
    return AcceptedObservationRun(
        report=str(report_path),
        output_directory=str(output_dir),
        model_sha256=model_sha,
        elapsed_millis=elapsed,
        total_pss_kb=total_pss,
        battery_level=parse_battery_level(battery),
    )


def validate_idle_evidence(
    path: Path | None,
    *,
    expected_model_sha: str | None,
    min_idle_seconds: int,
    max_idle_pss_kb: int,
) -> tuple[IdleCleanupEvidence, tuple[str, ...], tuple[str, ...]]:
    if path is None:
        return (
            IdleCleanupEvidence(supplied=False),
            ("idle cleanup evidence JSON was not supplied",),
            (),
        )
    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return (IdleCleanupEvidence(supplied=True), (str(exc),), ())

    blockers: list[str] = []
    warnings = string_items(payload.get("warnings"))
    if payload.get("schema_version") != IDLE_EVIDENCE_SCHEMA_VERSION:
        blockers.append("idle cleanup evidence schema_version mismatch")
    if payload.get("ok") is not True:
        blockers.extend(
            string_items(payload.get("blockers")) or ["idle cleanup evidence is not OK"]
        )
    waited_seconds = int_value(payload.get("waited_seconds"))
    if waited_seconds is None or waited_seconds < min_idle_seconds:
        blockers.append(f"idle cleanup evidence must wait at least {min_idle_seconds} seconds")
    model_sha = str(payload.get("model_sha256", ""))
    if expected_model_sha is not None and model_sha != expected_model_sha:
        blockers.append("idle cleanup evidence model_sha256 does not match observation reports")
    provider_closed = payload.get("provider_closed_after_idle")
    if provider_closed is not True:
        blockers.append("idle cleanup evidence must prove provider_closed_after_idle")
    process_running = payload.get("process_running_after_idle")
    total_pss = int_value(payload.get("total_pss_kb"))
    if process_running not in {True, False}:
        blockers.append("idle cleanup evidence must record process_running_after_idle")
    elif process_running and (total_pss is None or total_pss > max_idle_pss_kb):
        blockers.append(
            f"idle cleanup TOTAL PSS must be at most {max_idle_pss_kb} KB when process remains"
        )
    return (
        IdleCleanupEvidence(
            supplied=True,
            waited_seconds=waited_seconds,
            provider_closed_after_idle=provider_closed
            if isinstance(provider_closed, bool)
            else None,
            process_running_after_idle=process_running
            if isinstance(process_running, bool)
            else None,
            total_pss_kb=total_pss,
        ),
        tuple(dict.fromkeys(blockers)),
        warnings,
    )


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def mapping_items(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def parse_total_pss_kb(text: str) -> int | None:
    match = TOTAL_PSS.search(text)
    return int(match.group(1)) if match else None


def parse_battery_level(text: str) -> int | None:
    match = BATTERY_LEVEL.search(text)
    return int(match.group(1)) if match else None


def render_json(report: ModelDebugAcceptanceReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_text(report: ModelDebugAcceptanceReport) -> str:
    lines = [
        "GOFFY modelDebug production acceptance",
        f"status: {report.status}",
        f"ok: {str(report.ok).lower()}",
        f"accepted runs: {len(report.accepted_runs)} / {report.min_runs}",
    ]
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    for run in report.accepted_runs:
        lines.append(f"- {run.report}: elapsed={run.elapsed_millis}ms pss={run.total_pss_kb}KB")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify Moto G modelDebug repeated-run and idle-cleanup acceptance evidence.",
    )
    parser.add_argument("reports", nargs="*", type=Path)
    parser.add_argument("--idle-evidence-json", type=Path)
    parser.add_argument("--min-runs", type=int, default=DEFAULT_MIN_RUNS)
    parser.add_argument(
        "--max-observation-millis",
        type=int,
        default=DEFAULT_MAX_OBSERVATION_MILLIS,
    )
    parser.add_argument("--max-run-pss-kb", type=int, default=DEFAULT_MAX_RUN_PSS_KB)
    parser.add_argument("--max-idle-pss-kb", type=int, default=DEFAULT_MAX_IDLE_PSS_KB)
    parser.add_argument("--min-idle-seconds", type=int, default=DEFAULT_MIN_IDLE_SECONDS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_acceptance_report(
        reports=args.reports,
        idle_evidence_json=args.idle_evidence_json,
        min_runs=args.min_runs,
        max_observation_millis=args.max_observation_millis,
        max_run_pss_kb=args.max_run_pss_kb,
        max_idle_pss_kb=args.max_idle_pss_kb,
        min_idle_seconds=args.min_idle_seconds,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
