from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_bootloader_visibility_guide import redact_message  # noqa: E402
from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.rom0-operator-checklist.v1"
SUPPORTED_REFRESH_SCHEMAS = frozenset(
    (
        "goffy.rom0-refresh-report.v2",
        "goffy.rom0-refresh-report.v3",
        "goffy.rom0-refresh-report.v4",
    )
)
VALIDATION_DIR = Path(".goffy-validation")
DEFAULT_REFRESH_REPORT = VALIDATION_DIR / "rom-0-refresh-report.json"
DEFAULT_JSON_OUTPUT = VALIDATION_DIR / "rom-0-operator-checklist.json"
DEFAULT_MARKDOWN_OUTPUT = VALIDATION_DIR / "rom-0-operator-checklist.md"
UNLOCK_NOT_ACCEPTED_BLOCKER = (
    "manual OEM or Motorola unlock eligibility evidence is missing or not eligible"
)

FORBIDDEN_COMMAND_TERMS = (
    "fastboot flashing unlock",
    "fastboot oem unlock",
    "fastboot flash",
    "fastboot erase",
    "fastboot wipe",
    "fastboot reboot",
    "fastboot boot",
    "adb reboot bootloader",
    "adb reboot fastboot",
)


class ChecklistStatus(StrEnum):
    BLOCKED_EVIDENCE = "BLOCKED_EVIDENCE"
    READY_FOR_ROM0_READINESS_REVIEW = "READY_FOR_ROM0_READINESS_REVIEW"


class StepStatus(StrEnum):
    DONE = "DONE"
    READY = "READY"
    BLOCKED = "BLOCKED"


class StepKind(StrEnum):
    LOCAL_READ_ONLY = "LOCAL_READ_ONLY"
    HUMAN_ONLY = "HUMAN_ONLY"
    TEMPLATE_ONLY = "TEMPLATE_ONLY"
    HUMAN_DECISION = "HUMAN_DECISION"


@dataclass(frozen=True)
class OperatorStep:
    step_id: str
    title: str
    kind: StepKind
    status: StepStatus
    summary: str
    must_follow_after: tuple[str, ...] = ()
    safe_commands: tuple[str, ...] = ()
    evidence_paths: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rom0OperatorChecklist:
    schema_version: str
    generated_at: str
    ok: bool
    status: ChecklistStatus
    destructive_actions: str
    source_refresh_report: str
    blocked_by: tuple[str, ...]
    steps: tuple[OperatorStep, ...]
    reuse_decision: str


def build_operator_checklist(
    refresh_report: Mapping[str, Any],
    *,
    source_refresh_report: Path = DEFAULT_REFRESH_REPORT,
) -> Rom0OperatorChecklist:
    validate_refresh_report(refresh_report)
    evidence = evidence_inputs(refresh_report)
    refresh_succeeded = refresh_report.get("refresh_succeeded") is True
    rom_ready = refresh_succeeded and refresh_report.get("rom_ready") is True
    stock_ready = evidence_loaded(evidence, "stock_restore")
    unlock_ready = evidence_loaded(evidence, "unlock_eligibility") and unlock_semantically_ready(
        refresh_report
    )
    gsi_ready = evidence_loaded(evidence, "gsi_candidate")
    dsu_preflight_ready = evidence_loaded(evidence, "dsu_preflight")
    fastboot_ready = evidence_loaded(evidence, "fastboot_evidence")
    bootloader_status = string_value(refresh_report.get("bootloader_visibility_status"))
    manual_bootloader_visible = bootloader_status == "MANUAL_BOOTLOADER_VISIBLE"

    blocked_by = checklist_blockers(
        refresh_report=refresh_report,
        evidence=evidence,
        stock_ready=stock_ready,
        unlock_ready=unlock_ready,
        gsi_ready=gsi_ready,
        dsu_preflight_ready=dsu_preflight_ready,
        fastboot_ready=fastboot_ready,
        manual_bootloader_visible=manual_bootloader_visible,
    )
    status = (
        ChecklistStatus.READY_FOR_ROM0_READINESS_REVIEW
        if rom_ready and not blocked_by
        else ChecklistStatus.BLOCKED_EVIDENCE
    )
    checklist = Rom0OperatorChecklist(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=status is ChecklistStatus.READY_FOR_ROM0_READINESS_REVIEW,
        status=status,
        destructive_actions="withheld",
        source_refresh_report=display_path(source_refresh_report),
        blocked_by=blocked_by,
        steps=(
            refresh_step(refresh_succeeded=refresh_succeeded),
            stock_restore_step(refresh_succeeded=refresh_succeeded, stock_ready=stock_ready),
            unlock_eligibility_step(
                refresh_succeeded=refresh_succeeded,
                stock_ready=stock_ready,
                unlock_ready=unlock_ready,
            ),
            gsi_candidate_step(
                refresh_succeeded=refresh_succeeded,
                stock_ready=stock_ready,
                gsi_ready=gsi_ready,
            ),
            dsu_preflight_step(
                refresh_succeeded=refresh_succeeded,
                stock_ready=stock_ready,
                gsi_ready=gsi_ready,
                dsu_preflight_ready=dsu_preflight_ready,
            ),
            host_fastboot_step(
                refresh_succeeded=refresh_succeeded,
                fastboot_ready=fastboot_ready,
            ),
            manual_bootloader_visibility_step(
                bootloader_status=bootloader_status,
                fastboot_ready=fastboot_ready,
            ),
            manual_gates_step(stock_ready=stock_ready, unlock_ready=unlock_ready),
            readiness_review_step(rom_ready=rom_ready),
            destructive_decision_step(rom_ready=rom_ready),
        ),
        reuse_decision=(
            "Reuse official Android DSU semantics and GOFFY typed evidence validators; "
            "do not import DSU installer apps, generic flashing scripts, or bootloader "
            "automation into ROM-0."
        ),
    )
    assert_no_destructive_authority(checklist)
    return checklist


def validate_refresh_report(refresh_report: Mapping[str, Any]) -> None:
    schema = refresh_report.get("schema_version")
    if schema not in SUPPORTED_REFRESH_SCHEMAS:
        raise ValueError(
            f"unsupported ROM-0 refresh schema {schema!r}; expected one of "
            f"{sorted(SUPPORTED_REFRESH_SCHEMAS)!r}"
        )
    if refresh_report.get("destructive_actions") != "withheld":
        raise ValueError("ROM-0 refresh report must withhold destructive actions")


def checklist_blockers(
    *,
    refresh_report: Mapping[str, Any],
    evidence: Mapping[str, Mapping[str, str]],
    stock_ready: bool,
    unlock_ready: bool,
    gsi_ready: bool,
    dsu_preflight_ready: bool,
    fastboot_ready: bool,
    manual_bootloader_visible: bool,
) -> tuple[str, ...]:
    blockers = [redact_message(item) for item in string_items(refresh_report.get("blocked_by"))]
    if refresh_report.get("refresh_succeeded") is not True:
        blockers.append("refresh report contains invalid evidence inputs")
    for name, evidence_input in evidence.items():
        if evidence_input.get("status") == "INVALID":
            blockers.append(f"fix invalid {name} evidence before continuing")
    if not stock_ready:
        blockers.append(
            "stock restore evidence must be recorded before any unlock, DSU, flash, "
            "or boot decision"
        )
    if not unlock_ready:
        blockers.append("OEM or Motorola unlock eligibility evidence is missing")
    if not gsi_ready:
        blockers.append("official Google GSI archive evidence is missing")
    if not dsu_preflight_ready:
        blockers.append("read-only DSU preflight evidence is missing")
    if not fastboot_ready:
        blockers.append("host fastboot evidence is missing")
    if not manual_bootloader_visible:
        blockers.append("manual bootloader-mode fastboot visibility has not been recorded")
    return tuple(dict.fromkeys(blockers))


def refresh_step(*, refresh_succeeded: bool) -> OperatorStep:
    return OperatorStep(
        step_id="refresh_rom0_evidence",
        title="Refresh ROM-0 evidence",
        kind=StepKind.LOCAL_READ_ONLY,
        status=StepStatus.DONE if refresh_succeeded else StepStatus.READY,
        summary=(
            "Read-only probe, action packet, and bootloader guide are current."
            if refresh_succeeded
            else "Refresh evidence before relying on this checklist."
        ),
        safe_commands=(".venv/bin/python scripts/refresh_rom0_action_packet.py",),
        evidence_paths=(
            ".goffy-validation/rom-feasibility-current.json",
            ".goffy-validation/rom-0-refresh-report.json",
        ),
    )


def stock_restore_step(*, refresh_succeeded: bool, stock_ready: bool) -> OperatorStep:
    return OperatorStep(
        step_id="record_stock_restore",
        title="Record exact stock restore evidence",
        kind=StepKind.HUMAN_ONLY,
        status=StepStatus.DONE
        if stock_ready
        else StepStatus.READY
        if refresh_succeeded
        else StepStatus.BLOCKED,
        summary=(
            "Exact stock archive and rollback evidence exists."
            if stock_ready
            else (
                "Record the official Motorola restore archive name, SHA-256, "
                "and rollback doc first."
            )
        ),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_stock_restore_evidence.py "
            "--archive /absolute/path/outside/repo/<exact-kansas-stock-archive.zip> "
            "--source-url https://en-us.support.motorola.com/app/softwarefix "
            "--rollback-doc docs/setup/kansas-stock-rollback.md "
            "--output .goffy-validation/rom-stock-restore-evidence.json",
        )
        if not stock_ready and refresh_succeeded
        else (),
        evidence_paths=(".goffy-validation/rom-stock-restore-evidence.json",),
        blockers=()
        if stock_ready or refresh_succeeded
        else ("refresh ROM-0 evidence before recording restore evidence",),
    )


def unlock_eligibility_step(
    *,
    refresh_succeeded: bool,
    stock_ready: bool,
    unlock_ready: bool,
) -> OperatorStep:
    if unlock_ready:
        status = StepStatus.DONE
    elif refresh_succeeded:
        status = StepStatus.READY
    else:
        status = StepStatus.BLOCKED
    return OperatorStep(
        step_id="record_unlock_eligibility",
        title="Record OEM or Motorola unlock eligibility",
        kind=StepKind.HUMAN_ONLY,
        status=status,
        summary=(
            "Unlock eligibility evidence exists."
            if unlock_ready
            else "Record only redacted OEM-toggle and Motorola eligibility evidence."
        ),
        must_follow_after=("record_stock_restore",),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_unlock_eligibility_evidence.py "
            "--oem-unlocking-visible yes "
            "--oem-unlocking-enabled yes "
            "--probe-json .goffy-validation/rom-feasibility-current.json "
            "--motorola-eligibility eligible "
            "--operator-note-code checked_no_identifiers_stored "
            "--output .goffy-validation/rom-unlock-eligibility-evidence.json",
        )
        if not unlock_ready and refresh_succeeded
        else (),
        evidence_paths=(".goffy-validation/rom-unlock-eligibility-evidence.json",),
        blockers=()
        if stock_ready
        else ("stock restore evidence must be recorded before unlock decisions advance",),
    )


def gsi_candidate_step(
    *,
    refresh_succeeded: bool,
    stock_ready: bool,
    gsi_ready: bool,
) -> OperatorStep:
    return OperatorStep(
        step_id="record_gsi_candidate",
        title="Record official GSI archive evidence",
        kind=StepKind.HUMAN_ONLY,
        status=StepStatus.DONE
        if gsi_ready
        else StepStatus.READY
        if refresh_succeeded
        else StepStatus.BLOCKED,
        summary=(
            "Official Google GSI checksum evidence exists."
            if gsi_ready
            else "After accepting Google's terms, hash the downloaded GSI archive outside the repo."
        ),
        must_follow_after=("record_stock_restore",),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_gsi_candidate_evidence.py "
            "--artifact /absolute/path/outside/repo/"
            "aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip "
            "--source-url https://developer.android.com/topic/generic-system-image/releases "
            "--download-url https://dl.google.com/developers/android/baklava/images/gsi/"
            "aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip "
            "--expected-sha256 2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea "
            '--candidate-name "Official Google Android 16 ARM64 GSI" '
            "--android-release 16 "
            "--architecture arm64 "
            "--output .goffy-validation/rom-gsi-candidate-evidence.json",
        )
        if not gsi_ready and refresh_succeeded
        else (),
        evidence_paths=(".goffy-validation/rom-gsi-candidate-evidence.json",),
        blockers=()
        if stock_ready
        else ("stock restore evidence must be recorded before DSU/GSI decisions advance",),
    )


def dsu_preflight_step(
    *,
    refresh_succeeded: bool,
    stock_ready: bool,
    gsi_ready: bool,
    dsu_preflight_ready: bool,
) -> OperatorStep:
    prerequisites_ready = stock_ready and gsi_ready
    return OperatorStep(
        step_id="record_dsu_preflight",
        title="Record read-only DSU preflight",
        kind=StepKind.LOCAL_READ_ONLY,
        status=StepStatus.DONE
        if dsu_preflight_ready
        else StepStatus.READY
        if refresh_succeeded and prerequisites_ready
        else StepStatus.BLOCKED,
        summary=(
            "Read-only DSU preflight evidence exists."
            if dsu_preflight_ready
            else "Check DSU prerequisites from local evidence without opening DSU or installing."
        ),
        must_follow_after=("record_stock_restore", "record_gsi_candidate"),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_dsu_preflight_evidence.py "
            "--probe-json .goffy-validation/rom-feasibility-current.json "
            "--stock-restore-evidence .goffy-validation/rom-stock-restore-evidence.json "
            "--gsi-candidate-evidence .goffy-validation/rom-gsi-candidate-evidence.json "
            "--output .goffy-validation/rom-dsu-preflight-evidence.json",
        )
        if not dsu_preflight_ready and refresh_succeeded and prerequisites_ready
        else (),
        evidence_paths=(".goffy-validation/rom-dsu-preflight-evidence.json",),
        blockers=()
        if dsu_preflight_ready or prerequisites_ready
        else ("stock restore and official GSI evidence must both exist first",),
    )


def host_fastboot_step(*, refresh_succeeded: bool, fastboot_ready: bool) -> OperatorStep:
    return OperatorStep(
        step_id="record_host_fastboot",
        title="Record host fastboot readiness",
        kind=StepKind.LOCAL_READ_ONLY,
        status=StepStatus.DONE
        if fastboot_ready
        else StepStatus.READY
        if refresh_succeeded
        else StepStatus.BLOCKED,
        summary=(
            "Trusted host fastboot evidence exists."
            if fastboot_ready
            else "Record Android SDK fastboot availability without touching the phone state."
        ),
        safe_commands=(".venv/bin/python scripts/create_rom_fastboot_evidence.py",)
        if not fastboot_ready and refresh_succeeded
        else (),
        evidence_paths=(".goffy-validation/rom-fastboot-evidence.json",),
    )


def manual_bootloader_visibility_step(
    *,
    bootloader_status: str,
    fastboot_ready: bool,
) -> OperatorStep:
    visible = bootloader_status == "MANUAL_BOOTLOADER_VISIBLE"
    ready = bootloader_status == "READY_FOR_MANUAL_BOOTLOADER_CHECK"
    return OperatorStep(
        step_id="record_manual_bootloader_visibility",
        title="Record manual bootloader visibility",
        kind=StepKind.LOCAL_READ_ONLY,
        status=StepStatus.DONE if visible else StepStatus.READY if ready else StepStatus.BLOCKED,
        summary=(
            "The phone has been observed by fastboot while manually in bootloader mode."
            if visible
            else (
                "Only after the human manually enters bootloader mode, record read-only visibility."
            )
        ),
        must_follow_after=("record_host_fastboot",),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_fastboot_evidence.py --manual-bootloader-check",
        )
        if ready
        else (),
        evidence_paths=(
            ".goffy-validation/rom-fastboot-evidence.json",
            ".goffy-validation/rom-bootloader-visibility-guide.json",
        ),
        blockers=()
        if visible or ready
        else ("host fastboot evidence must be valid first",)
        if not fastboot_ready
        else ("manual bootloader-mode fastboot visibility has not been recorded",),
    )


def manual_gates_step(*, stock_ready: bool, unlock_ready: bool) -> OperatorStep:
    ready = stock_ready and unlock_ready
    return OperatorStep(
        step_id="create_manual_gates",
        title="Create ROM-0 manual gates",
        kind=StepKind.TEMPLATE_ONLY,
        status=StepStatus.READY if ready else StepStatus.BLOCKED,
        summary="Create and validate the fail-closed manual gate file from recorded evidence.",
        must_follow_after=("record_stock_restore", "record_unlock_eligibility"),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_manual_gates_template.py "
            "--probe-json .goffy-validation/rom-feasibility-current.json "
            "--unlock-eligibility-evidence .goffy-validation/rom-unlock-eligibility-evidence.json "
            "--stock-restore-evidence .goffy-validation/rom-stock-restore-evidence.json "
            "--output .goffy-validation/rom-0-manual-gates.json",
            ".venv/bin/python scripts/validate_rom_manual_gates.py "
            ".goffy-validation/rom-0-manual-gates.json "
            "--probe-json .goffy-validation/rom-feasibility-current.json",
        )
        if ready
        else (),
        evidence_paths=(".goffy-validation/rom-0-manual-gates.json",),
        blockers=()
        if ready
        else ("stock restore and unlock eligibility evidence must both exist first",),
    )


def readiness_review_step(*, rom_ready: bool) -> OperatorStep:
    return OperatorStep(
        step_id="rom0_readiness_review",
        title="Run ROM-0 readiness review",
        kind=StepKind.LOCAL_READ_ONLY,
        status=StepStatus.READY if rom_ready else StepStatus.BLOCKED,
        summary=(
            "Saved evidence is ready for human ROM-0 review."
            if rom_ready
            else "Readiness review is blocked until all required evidence exists."
        ),
        must_follow_after=(
            "create_manual_gates",
            "record_gsi_candidate",
            "record_dsu_preflight",
            "record_manual_bootloader_visibility",
        ),
        safe_commands=(
            ".venv/bin/python scripts/verify_rom0_readiness.py "
            "--probe-json .goffy-validation/rom-feasibility-current.json "
            "--manual-gates-json .goffy-validation/rom-0-manual-gates.json "
            "--fastboot-evidence-json .goffy-validation/rom-fastboot-evidence.json "
            "--gsi-candidate-evidence-json .goffy-validation/rom-gsi-candidate-evidence.json "
            "--dsu-preflight-evidence-json .goffy-validation/rom-dsu-preflight-evidence.json "
            "--signing-plan-json .goffy-validation/rom-signing/release-signing-plan.json "
            "--apk-verification-json .goffy-validation/rom-signing/release-apk-verification.json "
            "--signed-apk .goffy-validation/rom-signing/GoffyOS-signed.apk "
            "--aosp-root /path/to/aosp "
            "--evidence-root .",
        )
        if rom_ready
        else (),
    )


def destructive_decision_step(*, rom_ready: bool) -> OperatorStep:
    return OperatorStep(
        step_id="destructive_unlock_or_boot_decision",
        title="Destructive unlock or boot decision",
        kind=StepKind.HUMAN_DECISION,
        status=StepStatus.BLOCKED,
        summary=(
            "Even after readiness review, this checklist does not authorize device mutation."
            if rom_ready
            else "Blocked until ROM-0 readiness review succeeds."
        ),
        must_follow_after=("rom0_readiness_review",),
        blockers=("explicit user approval is required in a separate future step",),
    )


def evidence_inputs(refresh_report: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    inputs = refresh_report.get("evidence_inputs")
    if not isinstance(inputs, Sequence) or isinstance(inputs, str):
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in inputs:
        if isinstance(item, Mapping):
            name = string_value(item.get("name"))
            if name:
                result[name] = {
                    "status": string_value(item.get("status")),
                    "detail": redact_message(string_value(item.get("detail"))),
                    "path": display_path(Path(string_value(item.get("path")))),
                }
    return result


def evidence_loaded(evidence: Mapping[str, Mapping[str, str]], name: str) -> bool:
    return evidence.get(name, {}).get("status") == "LOADED"


def unlock_semantically_ready(refresh_report: Mapping[str, Any]) -> bool:
    blocked_by = tuple(str(item) for item in refresh_report.get("blocked_by", ()))
    return UNLOCK_NOT_ACCEPTED_BLOCKER not in blocked_by


def load_refresh_report(path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    resolved, display = confined_existing_path(path, root=root)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(redact_message(str(exc))) from exc
    if not isinstance(payload, dict):
        raise ValueError("ROM-0 refresh report must be a JSON object")
    payload["refresh_report_json"] = display
    return payload


def confined_existing_path(path: Path, *, root: Path) -> tuple[Path, str]:
    candidate, relative = validation_relative_path(path, root=root)
    reject_symlink_path(relative=relative, root=root)
    if not candidate.exists():
        raise ValueError(
            f"ROM-0 refresh report does not exist: {display_path(VALIDATION_DIR / relative)}"
        )
    if not candidate.is_file():
        raise ValueError("ROM-0 refresh report path must be a regular file under .goffy-validation")
    return candidate, display_path(VALIDATION_DIR / relative)


def validation_relative_path(path: Path, *, root: Path) -> tuple[Path, Path]:
    repo_root = root.expanduser().resolve(strict=False)
    validation_root = repo_root / VALIDATION_DIR
    candidate = resolve_under_root(path, root=repo_root)
    try:
        relative = candidate.relative_to(validation_root)
    except ValueError as exc:
        raise ValueError("path must be under .goffy-validation") from exc
    if ".." in relative.parts:
        raise ValueError("path must not escape .goffy-validation")
    return candidate, relative


def reject_symlink_path(*, relative: Path, root: Path) -> None:
    validation_root = root.expanduser().resolve(strict=False) / VALIDATION_DIR
    if validation_root.is_symlink():
        raise ValueError("validation dir must not be a symlink")
    current = validation_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("validation path must not contain symlinks")


def resolve_under_root(path: Path, *, root: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else root / expanded


def display_path(path: Path) -> str:
    return path.as_posix()


def string_value(value: object) -> str:
    return "" if value is None else str(value)


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(redact_message(str(item)) for item in value if str(item))


def assert_no_destructive_authority(checklist: Rom0OperatorChecklist) -> None:
    rendered = json.dumps(asdict(checklist)).lower()
    forbidden = [term for term in FORBIDDEN_COMMAND_TERMS if term in rendered]
    if forbidden:
        raise ValueError(f"ROM-0 operator checklist contains forbidden command(s): {forbidden}")


def render_json(checklist: Rom0OperatorChecklist) -> str:
    return json.dumps(asdict(checklist), indent=2) + "\n"


def render_markdown(checklist: Rom0OperatorChecklist) -> str:
    lines = [
        "# GOFFY ROM-0 Operator Checklist",
        "",
        f"- Status: `{checklist.status}`",
        f"- OK: `{str(checklist.ok).lower()}`",
        f"- Destructive actions: `{checklist.destructive_actions}`",
        f"- Source refresh report: `{checklist.source_refresh_report}`",
    ]
    if checklist.blocked_by:
        lines.extend(("", "## Blocked By"))
        lines.extend(f"- {item}" for item in checklist.blocked_by)
    lines.extend(("", "## Ordered Steps"))
    for step in checklist.steps:
        lines.extend(
            (
                "",
                f"### {step.title}",
                f"- ID: `{step.step_id}`",
                f"- Kind: `{step.kind}`",
                f"- Status: `{step.status}`",
                f"- Summary: {step.summary}",
            )
        )
        if step.must_follow_after:
            lines.append(
                "- Must follow after: "
                + ", ".join(f"`{step_id}`" for step_id in step.must_follow_after)
            )
        if step.safe_commands:
            lines.append("- Safe commands:")
            lines.extend(f"  - `{command}`" for command in step.safe_commands)
        if step.evidence_paths:
            lines.append("- Evidence paths:")
            lines.extend(f"  - `{path}`" for path in step.evidence_paths)
        if step.blockers:
            lines.append("- Blockers:")
            lines.extend(f"  - {item}" for item in step.blockers)
    lines.extend(("", "## Reuse Decision", checklist.reuse_decision, ""))
    return "\n".join(lines)


def write_checklist_outputs(
    checklist: Rom0OperatorChecklist,
    *,
    json_output: Path,
    markdown_output: Path,
    root: Path = ROOT,
) -> None:
    write_output(json_output, render_json(checklist), root=root)
    write_output(markdown_output, render_markdown(checklist), root=root)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an ordered non-destructive ROM-0 operator checklist.",
    )
    parser.add_argument(
        "--refresh-report",
        type=Path,
        default=DEFAULT_REFRESH_REPORT,
        help="ROM-0 refresh report under .goffy-validation.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_JSON_OUTPUT,
        help="Checklist JSON output under .goffy-validation.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT,
        help="Checklist Markdown output under .goffy-validation.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text summary.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        refresh_report = load_refresh_report(args.refresh_report, root=ROOT)
        checklist = build_operator_checklist(
            refresh_report,
            source_refresh_report=Path(refresh_report.get("refresh_report_json", "")),
        )
        write_checklist_outputs(
            checklist,
            json_output=args.output,
            markdown_output=args.markdown_output,
            root=ROOT,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {redact_message(str(exc))}", file=sys.stderr)
        return 1
    print(render_json(checklist) if args.json else render_markdown(checklist))
    return 0 if checklist.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
