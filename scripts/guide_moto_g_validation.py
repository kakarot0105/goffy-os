from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = ROOT / "protocol" / "python"
if __package__ in {None, ""}:
    for import_root in (ROOT, PROTOCOL_ROOT):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

import scripts.record_moto_g_smoke as smoke  # noqa: E402
from scripts.setup_doctor import DoctorReport, safe_text  # noqa: E402
from scripts.verify_moto_g_readiness import existing_directory  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.moto-g-physical-guide.v1"


class GuideStatus(StrEnum):
    DONE = "DONE"
    READY = "READY"
    MANUAL = "MANUAL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class GuideStep:
    step_id: str
    title: str
    status: GuideStatus
    detail: str
    command: tuple[str, ...] = ()
    mutates_device: bool = False
    requires_confirmation: bool = False


@dataclass(frozen=True)
class GuideReport:
    record: smoke.SmokeRecord
    steps: tuple[GuideStep, ...]
    repo_root: Path = ROOT
    home: Path = Path.home()

    @property
    def ok(self) -> bool:
        return self.record.physical_smoke_passed

    @property
    def next_step_id(self) -> str | None:
        next_step = next((step for step in self.steps if step.status is not GuideStatus.DONE), None)
        return None if next_step is None else next_step.step_id


def readiness_command() -> tuple[str, ...]:
    return (".venv/bin/python", "scripts/record_moto_g_smoke.py", "--json")


def usb_setup_command() -> tuple[str, ...]:
    return (
        ".venv/bin/python",
        "scripts/run_moto_g_usb_setup.py",
        "--execute",
        "--confirm-device-mutation",
    )


def smoke_record_command() -> tuple[str, ...]:
    return (
        ".venv/bin/python",
        "scripts/record_moto_g_smoke.py",
        "--app-launched",
        "pass",
        "--command-submitted",
        "pass",
        "--mac-status-displayed",
        "pass",
        "--timeline-recorded",
        "pass",
        "--restart-restored",
        "pass",
        "--json",
    )


def summarize_blockers(blockers: tuple[str, ...]) -> str:
    if not blockers:
        return "no blockers"
    visible = ", ".join(blockers[:5])
    if len(blockers) > 5:
        visible += f", +{len(blockers) - 5} more"
    return visible


def prerequisite_blockers(record: smoke.SmokeRecord) -> tuple[str, ...]:
    blockers = [
        f"{check.category}/{check.name}" for check in record.readiness.checks if not check.ok
    ]
    return tuple(blocker for blocker in blockers if blocker != "device/Hub USB reverse")


def build_steps(record: smoke.SmokeRecord) -> tuple[GuideStep, ...]:
    prereq_blockers = prerequisite_blockers(record)
    if prereq_blockers:
        prerequisite_status = GuideStatus.BLOCKED
        prerequisite_detail = f"Resolve prerequisites: {summarize_blockers(prereq_blockers)}"
    else:
        prerequisite_status = GuideStatus.DONE
        prerequisite_detail = "Toolchain, Hub, device, and APK prerequisites are ready."

    if record.ready_for_manual_smoke:
        usb_status = GuideStatus.DONE
        usb_detail = "USB reverse and debug APK are ready for the phone smoke test."
        usb_command: tuple[str, ...] = ()
    elif record.usb_setup.ok:
        usb_status = GuideStatus.READY
        usb_detail = "Run the fixed USB setup command, then launch GOFFY manually."
        usb_command = usb_setup_command()
    else:
        usb_status = GuideStatus.BLOCKED
        blockers = summarize_blockers(record.usb_setup.readiness_blockers)
        usb_detail = f"USB setup is blocked: {blockers}"
        usb_command = (".venv/bin/python", "scripts/run_moto_g_usb_setup.py", "--json")

    if record.physical_smoke_passed:
        manual_status = GuideStatus.DONE
        manual_detail = "Manual phone smoke checklist passed."
    elif record.manual.failed:
        manual_status = GuideStatus.BLOCKED
        manual_detail = "A manual phone smoke checklist item failed; fix it before rerunning."
    elif record.ready_for_manual_smoke:
        manual_status = GuideStatus.MANUAL
        manual_detail = (
            "On the Moto G, launch GOFFY, submit `Show my Mac status`, "
            "verify timeline, then restart and repeat."
        )
    else:
        manual_status = GuideStatus.BLOCKED
        manual_detail = "Manual phone checks are blocked until readiness and USB setup pass."

    if record.physical_smoke_passed:
        evidence_status = GuideStatus.DONE
        evidence_detail = "Physical smoke evidence is complete."
    elif record.manual.failed:
        evidence_status = GuideStatus.BLOCKED
        evidence_detail = "Do not record passing evidence while any manual item is failed."
    elif record.manual.complete:
        evidence_status = GuideStatus.READY
        evidence_detail = "Record the bounded manual checklist result."
    elif record.ready_for_manual_smoke:
        evidence_status = GuideStatus.MANUAL
        evidence_detail = "Complete the manual phone checklist before recording final evidence."
    else:
        evidence_status = GuideStatus.BLOCKED
        evidence_detail = "Evidence capture is blocked until readiness and manual checks pass."

    return (
        GuideStep(
            step_id="preflight-readiness",
            title="Resolve trusted readiness prerequisites",
            status=prerequisite_status,
            detail=prerequisite_detail,
            command=readiness_command(),
        ),
        GuideStep(
            step_id="usb-setup",
            title="Prepare USB loopback and debug APK",
            status=usb_status,
            detail=usb_detail,
            command=usb_command,
            mutates_device=usb_status is GuideStatus.READY,
            requires_confirmation=usb_status is GuideStatus.READY,
        ),
        GuideStep(
            step_id="manual-phone-smoke",
            title="Run manual `Show my Mac status` phone smoke",
            status=manual_status,
            detail=manual_detail,
        ),
        GuideStep(
            step_id="record-evidence",
            title="Record bounded smoke evidence",
            status=evidence_status,
            detail=evidence_detail,
            command=smoke_record_command(),
        ),
    )


def build_report(
    *,
    root: Path = ROOT,
    manual: smoke.ManualSmokeEvidence | None = None,
    record: smoke.SmokeRecord | None = None,
) -> GuideReport:
    resolved_root = root.resolve()
    smoke_record = record or smoke.build_record(root=resolved_root, manual=manual)
    return GuideReport(
        record=smoke_record,
        steps=build_steps(smoke_record),
        repo_root=resolved_root,
    )


def redaction_report(report: GuideReport) -> DoctorReport:
    return DoctorReport(checks=(), repo_root=report.repo_root, home=report.home)


def format_command(command: tuple[str, ...], *, report: GuideReport) -> str:
    redactor = redaction_report(report)
    return " ".join(safe_text(part, report=redactor) for part in command)


def smoke_payload(record: smoke.SmokeRecord) -> dict[str, Any]:
    payload = json.loads(smoke.render_json(record))
    if not isinstance(payload, dict):
        raise TypeError("smoke recorder returned a non-object payload")
    return payload


def render_json(report: GuideReport) -> str:
    redactor = redaction_report(report)
    payload: dict[str, Any] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": report.ok,
        "nextStepId": report.next_step_id,
        "steps": [
            {
                **asdict(step),
                "status": step.status.value,
                "command": [safe_text(part, report=redactor) for part in step.command],
            }
            for step in report.steps
        ],
        "smokeRecord": smoke_payload(report.record),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_text(report: GuideReport) -> str:
    lines = ["GOFFY Moto G physical validation guide"]
    lines.append(f"overall: {'passed' if report.ok else 'not-passed'}")
    lines.append(f"next-step: {report.next_step_id or 'none'}")
    lines.append("")
    lines.append("steps:")
    for step in report.steps:
        lines.append(f"[{step.status}] {step.step_id}: {step.title}")
        lines.append(f"       detail: {step.detail}")
        if step.command:
            lines.append(f"       command: {format_command(step.command, report=report)}")
        if step.mutates_device:
            lines.append("       mutates-device: true")
        if step.requires_confirmation:
            lines.append("       requires-confirmation: true")
    lines.append("")
    if report.ok:
        lines.append("Physical Moto G validation evidence is complete.")
    else:
        lines.append("Follow the next non-DONE step; this guide does not control the phone.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=existing_directory, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--app-launched",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    parser.add_argument(
        "--command-submitted",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    parser.add_argument(
        "--mac-status-displayed",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    parser.add_argument(
        "--timeline-recorded",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    parser.add_argument(
        "--restart-restored",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    args = parser.parse_args(argv)

    manual = smoke.ManualSmokeEvidence(
        app_launched=args.app_launched,
        command_submitted=args.command_submitted,
        mac_status_displayed=args.mac_status_displayed,
        timeline_recorded=args.timeline_recorded,
        restart_restored=args.restart_restored,
    )
    report = build_report(root=args.repo_root, manual=manual)
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
