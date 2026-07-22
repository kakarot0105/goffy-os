from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_fastboot_evidence import (  # noqa: E402
    ABSOLUTE_POSIX_PATH,
    ABSOLUTE_WINDOWS_PATH,
)
from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402
from scripts.verify_rom0_readiness import validate_fastboot_evidence  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.rom-bootloader-visibility-guide.v1"
VALIDATION_DIR = Path(".goffy-validation")
DEFAULT_FASTBOOT_EVIDENCE = VALIDATION_DIR / "rom-fastboot-evidence.json"
DEFAULT_JSON_OUTPUT = VALIDATION_DIR / "rom-bootloader-visibility-guide.json"
DEFAULT_MARKDOWN_OUTPUT = VALIDATION_DIR / "rom-bootloader-visibility-guide.md"
FASTBOOT_HOST_COMMAND = ".venv/bin/python scripts/create_rom_fastboot_evidence.py"
FASTBOOT_MANUAL_COMMAND = (
    ".venv/bin/python scripts/create_rom_fastboot_evidence.py --manual-bootloader-check"
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


class GuideStatus(StrEnum):
    HOST_EVIDENCE_MISSING = "HOST_EVIDENCE_MISSING"
    FASTBOOT_EVIDENCE_INVALID = "FASTBOOT_EVIDENCE_INVALID"
    READY_FOR_MANUAL_BOOTLOADER_CHECK = "READY_FOR_MANUAL_BOOTLOADER_CHECK"
    MANUAL_BOOTLOADER_VISIBLE = "MANUAL_BOOTLOADER_VISIBLE"


class StepStatus(StrEnum):
    READY = "READY"
    RECORDED = "RECORDED"
    BLOCKED = "BLOCKED"


class StepKind(StrEnum):
    LOCAL_READ_ONLY = "LOCAL_READ_ONLY"
    HUMAN_ONLY = "HUMAN_ONLY"


@dataclass(frozen=True)
class GuideStep:
    step_id: str
    title: str
    kind: StepKind
    status: StepStatus
    summary: str
    instructions: tuple[str, ...]
    safe_commands: tuple[str, ...] = ()
    evidence_output: str = ""
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class FastbootEvidenceInput:
    path: str
    status: str
    accepted_evidence: dict[str, str]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class BootloaderVisibilityGuide:
    schema_version: str
    generated_at: str
    ok: bool
    status: GuideStatus
    destructive_actions: str
    fastboot_evidence: FastbootEvidenceInput
    steps: tuple[GuideStep, ...]
    blocked_by: tuple[str, ...]
    warnings: tuple[str, ...]


def build_visibility_guide(
    *,
    fastboot_evidence_json: Path = DEFAULT_FASTBOOT_EVIDENCE,
    root: Path = ROOT,
) -> BootloaderVisibilityGuide:
    evidence_input = load_fastboot_evidence_input(fastboot_evidence_json, root=root)
    evidence = evidence_input.accepted_evidence
    status = guide_status(evidence_input)
    blocked_by = guide_blockers(status=status, evidence_input=evidence_input)
    warnings = guide_warnings(status=status, evidence_input=evidence_input)
    guide = BootloaderVisibilityGuide(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=status is GuideStatus.MANUAL_BOOTLOADER_VISIBLE,
        status=status,
        destructive_actions="withheld",
        fastboot_evidence=evidence_input,
        steps=(
            host_fastboot_step(evidence_input),
            human_bootloader_entry_step(status=status),
            manual_visibility_step(status=status, evidence=evidence),
        ),
        blocked_by=blocked_by,
        warnings=warnings,
    )
    assert_no_destructive_authority(guide)
    return guide


def load_fastboot_evidence_input(path: Path, *, root: Path) -> FastbootEvidenceInput:
    resolved, display = confined_existing_evidence_path(path, root=root)
    if resolved is None:
        return FastbootEvidenceInput(
            path=display,
            status="MISSING",
            accepted_evidence={},
            blockers=("redacted fastboot evidence has not been created",),
            warnings=(),
        )
    section = validate_fastboot_evidence(resolved)
    safe_blockers = tuple(redact_message(item) for item in section.blockers)
    safe_warnings = tuple(redact_message(item) for item in section.warnings)
    return FastbootEvidenceInput(
        path=display,
        status="LOADED" if section.ok else "INVALID",
        accepted_evidence=section.evidence or {},
        blockers=safe_blockers,
        warnings=safe_warnings,
    )


def guide_status(evidence_input: FastbootEvidenceInput) -> GuideStatus:
    if evidence_input.status == "MISSING":
        return GuideStatus.HOST_EVIDENCE_MISSING
    if evidence_input.status != "LOADED":
        return GuideStatus.FASTBOOT_EVIDENCE_INVALID
    if evidence_input.accepted_evidence.get("status") == "MANUAL_BOOTLOADER_VISIBLE":
        return GuideStatus.MANUAL_BOOTLOADER_VISIBLE
    return GuideStatus.READY_FOR_MANUAL_BOOTLOADER_CHECK


def guide_blockers(
    *,
    status: GuideStatus,
    evidence_input: FastbootEvidenceInput,
) -> tuple[str, ...]:
    if status is GuideStatus.MANUAL_BOOTLOADER_VISIBLE:
        return ()
    if status is GuideStatus.HOST_EVIDENCE_MISSING:
        return ("create host fastboot evidence before manual bootloader visibility",)
    if status is GuideStatus.FASTBOOT_EVIDENCE_INVALID:
        return evidence_input.blockers or ("fastboot evidence did not validate",)
    return ("manual bootloader-mode fastboot visibility has not been recorded",)


def guide_warnings(
    *,
    status: GuideStatus,
    evidence_input: FastbootEvidenceInput,
) -> tuple[str, ...]:
    warnings = list(evidence_input.warnings)
    if status is GuideStatus.READY_FOR_MANUAL_BOOTLOADER_CHECK:
        warnings.append("enter bootloader mode manually before running the visibility check")
    return tuple(dict.fromkeys(warnings))


def host_fastboot_step(evidence_input: FastbootEvidenceInput) -> GuideStep:
    recorded = evidence_input.status == "LOADED"
    return GuideStep(
        step_id="record_host_fastboot",
        title="Record host fastboot readiness",
        kind=StepKind.LOCAL_READ_ONLY,
        status=StepStatus.RECORDED if recorded else StepStatus.READY,
        summary=(
            "Trusted Android SDK fastboot evidence exists."
            if recorded
            else "Create redacted host fastboot evidence without touching the phone."
        ),
        instructions=(
            "Run only the GOFFY fastboot evidence helper.",
            "The helper checks the trusted Android SDK fastboot path and version.",
            "It must not reboot, unlock, flash, erase, wipe, boot, or write to the phone.",
        ),
        safe_commands=(FASTBOOT_HOST_COMMAND,),
        evidence_output=display_path(DEFAULT_FASTBOOT_EVIDENCE),
    )


def human_bootloader_entry_step(*, status: GuideStatus) -> GuideStep:
    visible = status is GuideStatus.MANUAL_BOOTLOADER_VISIBLE
    ready = status is GuideStatus.READY_FOR_MANUAL_BOOTLOADER_CHECK
    step_status = (
        StepStatus.RECORDED if visible else StepStatus.READY if ready else StepStatus.BLOCKED
    )
    return GuideStep(
        step_id="manual_enter_bootloader",
        title="Manually enter bootloader mode",
        kind=StepKind.HUMAN_ONLY,
        status=step_status,
        summary=(
            "The phone has already been observed by fastboot in bootloader mode."
            if visible
            else "The human must put the phone into bootloader mode without GOFFY reboot commands."
        ),
        instructions=(
            "Use only physical-device controls or an already-visible Android bootloader UI.",
            "Do not trigger host-initiated reboot-to-bootloader from GOFFY automation.",
            "Do not select unlock, wipe, factory reset, rescue, or flashing options.",
            "Keep the phone connected by USB after bootloader mode is visible.",
        ),
        blockers=()
        if ready or visible
        else ("host fastboot evidence must be valid before this manual step",),
    )


def manual_visibility_step(
    *,
    status: GuideStatus,
    evidence: Mapping[str, str],
) -> GuideStep:
    visible = status is GuideStatus.MANUAL_BOOTLOADER_VISIBLE
    ready = status is GuideStatus.READY_FOR_MANUAL_BOOTLOADER_CHECK
    device_count = evidence.get("bootloader_device_count", "0")
    step_status = (
        StepStatus.RECORDED if visible else StepStatus.READY if ready else StepStatus.BLOCKED
    )
    return GuideStep(
        step_id="record_manual_fastboot_visibility",
        title="Record read-only bootloader visibility",
        kind=StepKind.LOCAL_READ_ONLY,
        status=step_status,
        summary=(
            f"Fastboot saw {device_count} redacted bootloader device(s)."
            if visible
            else (
                "Run the read-only visibility check only after the phone is manually "
                "in bootloader mode."
            )
        ),
        instructions=(
            "Run only the GOFFY helper with --manual-bootloader-check.",
            "The helper may run fastboot devices, but no unlock/flash/erase/wipe/"
            "boot/reboot command.",
            "The resulting JSON must redact device serials before ROM-0 readiness consumes it.",
        ),
        safe_commands=(FASTBOOT_MANUAL_COMMAND,) if ready else (),
        evidence_output=display_path(DEFAULT_FASTBOOT_EVIDENCE),
        blockers=()
        if ready or visible
        else ("host fastboot evidence must be valid before manual visibility can be recorded",),
    )


def confined_existing_evidence_path(path: Path, *, root: Path) -> tuple[Path | None, str]:
    candidate, relative = validation_relative_path(path, root=root)
    display = display_path(VALIDATION_DIR / relative)
    reject_symlink_path(relative=relative, root=root)
    if not candidate.exists():
        return None, display
    if not candidate.is_file():
        raise ValueError("fastboot evidence path must be a regular file under .goffy-validation")
    return candidate, display


def validation_relative_path(path: Path, *, root: Path) -> tuple[Path, Path]:
    repo_root = root.expanduser().resolve(strict=False)
    validation_root = repo_root / VALIDATION_DIR
    candidate = resolve_under_root(path, root=repo_root)
    try:
        relative = candidate.relative_to(validation_root)
    except ValueError as exc:
        raise ValueError("fastboot evidence path must be under .goffy-validation") from exc
    if ".." in relative.parts:
        raise ValueError("fastboot evidence path must not escape .goffy-validation")
    return candidate, relative


def reject_symlink_path(*, relative: Path, root: Path) -> None:
    validation_root = root.expanduser().resolve(strict=False) / VALIDATION_DIR
    if validation_root.is_symlink():
        raise ValueError("validation dir must not be a symlink")
    current = validation_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("fastboot evidence path must not contain symlinks")


def resolve_under_root(path: Path, *, root: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else root / expanded


def display_path(path: Path) -> str:
    return path.as_posix()


def redact_message(text: str) -> str:
    return ABSOLUTE_POSIX_PATH.sub("<path>", ABSOLUTE_WINDOWS_PATH.sub("<path>", text))


def assert_no_destructive_authority(guide: BootloaderVisibilityGuide) -> None:
    rendered = json.dumps(asdict(guide)).lower()
    forbidden = [term for term in FORBIDDEN_COMMAND_TERMS if term in rendered]
    if forbidden:
        raise ValueError(f"bootloader visibility guide contains forbidden command(s): {forbidden}")


def render_json(guide: BootloaderVisibilityGuide) -> str:
    return json.dumps(asdict(guide), indent=2) + "\n"


def render_markdown(guide: BootloaderVisibilityGuide) -> str:
    lines = [
        "# GOFFY ROM Bootloader Visibility Guide",
        "",
        f"- Status: `{guide.status}`",
        f"- OK: `{str(guide.ok).lower()}`",
        f"- Destructive actions: `{guide.destructive_actions}`",
        f"- Fastboot evidence: `{guide.fastboot_evidence.status}`",
    ]
    if guide.blocked_by:
        lines.extend(("", "## Blocked By"))
        lines.extend(f"- {item}" for item in guide.blocked_by)
    if guide.warnings:
        lines.extend(("", "## Warnings"))
        lines.extend(f"- {item}" for item in guide.warnings)
    lines.extend(("", "## Steps"))
    for step in guide.steps:
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
        lines.append("- Instructions:")
        lines.extend(f"  - {item}" for item in step.instructions)
        if step.safe_commands:
            lines.append("- Safe commands:")
            lines.extend(f"  - `{command}`" for command in step.safe_commands)
        if step.evidence_output:
            lines.append(f"- Evidence output: `{step.evidence_output}`")
        if step.blockers:
            lines.append("- Blockers:")
            lines.extend(f"  - {item}" for item in step.blockers)
    lines.append("")
    return "\n".join(lines)


def render_text(guide: BootloaderVisibilityGuide) -> str:
    lines = [
        "GOFFY ROM bootloader visibility guide",
        f"schema: {guide.schema_version}",
        f"overall: {guide.status}",
        f"ok: {str(guide.ok).lower()}",
        f"destructive actions: {guide.destructive_actions}",
        f"fastboot evidence: {guide.fastboot_evidence.status}",
    ]
    if guide.blocked_by:
        lines.append("blocked by:")
        lines.extend(f"- {item}" for item in guide.blocked_by)
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a read-only GOFFY guide for manually entering bootloader mode and "
            "recording fastboot visibility evidence."
        ),
    )
    parser.add_argument(
        "--fastboot-evidence-json",
        type=Path,
        default=DEFAULT_FASTBOOT_EVIDENCE,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_JSON_OUTPUT,
        help="JSON output path under .goffy-validation.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT,
        help="Markdown output path under .goffy-validation.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        guide = build_visibility_guide(
            fastboot_evidence_json=args.fastboot_evidence_json,
            root=ROOT,
        )
        write_output(args.output, render_json(guide), root=ROOT)
        write_output(args.markdown_output, render_markdown(guide), root=ROOT)
        print(render_json(guide) if args.json else render_text(guide), end="")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {redact_message(str(exc))}", file=sys.stderr)
        return 1
    return 0 if guide.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
