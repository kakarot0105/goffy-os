from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = ROOT / "protocol" / "python"
if __package__ in {None, ""}:
    for import_root in (ROOT, PROTOCOL_ROOT):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

from scripts.run_moto_g_usb_setup import (  # noqa: E402  # noqa: E402  # noqa: E402
    UsbSetupReport,
    collect_setup_readiness,
    trusted_adb_path,
)
from scripts.run_moto_g_usb_setup import (  # noqa: E402
    build_report as build_usb_setup_report,
)
from scripts.run_moto_g_usb_setup import (  # noqa: E402
    render_json as render_usb_setup_json,
)
from scripts.setup_doctor import DoctorReport, safe_text  # noqa: E402
from scripts.verify_moto_g_readiness import (  # noqa: E402
    DEBUG_APK_RELATIVE_PATH,
    ReadinessReport,
    existing_directory,
)
from scripts.verify_moto_g_readiness import (  # noqa: E402
    render_json as render_readiness_json,
)

JSON_SCHEMA_VERSION = "goffy.moto-g-physical-smoke.v1"


class ManualStatus(StrEnum):
    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True)
class ApkEvidence:
    relative_path: str
    present: bool
    size_bytes: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class ManualSmokeEvidence:
    app_launched: ManualStatus = ManualStatus.NOT_RUN
    command_submitted: ManualStatus = ManualStatus.NOT_RUN
    mac_status_displayed: ManualStatus = ManualStatus.NOT_RUN
    timeline_recorded: ManualStatus = ManualStatus.NOT_RUN
    restart_restored: ManualStatus = ManualStatus.NOT_RUN

    @property
    def statuses(self) -> tuple[ManualStatus, ...]:
        return (
            self.app_launched,
            self.command_submitted,
            self.mac_status_displayed,
            self.timeline_recorded,
            self.restart_restored,
        )

    @property
    def started(self) -> bool:
        return any(status is not ManualStatus.NOT_RUN for status in self.statuses)

    @property
    def complete(self) -> bool:
        return all(status is not ManualStatus.NOT_RUN for status in self.statuses)

    @property
    def failed(self) -> bool:
        return any(status is ManualStatus.FAIL for status in self.statuses)

    @property
    def passed(self) -> bool:
        return all(status is ManualStatus.PASS for status in self.statuses)


@dataclass(frozen=True)
class SmokeRecord:
    timestamp_utc: str
    readiness: ReadinessReport
    usb_setup: UsbSetupReport
    apk: ApkEvidence
    manual: ManualSmokeEvidence
    repo_root: Path = ROOT
    home: Path = Path.home()

    @property
    def ready_for_manual_smoke(self) -> bool:
        return self.readiness.ok and self.apk.present

    @property
    def physical_smoke_passed(self) -> bool:
        return self.ready_for_manual_smoke and self.manual.passed

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = [
            f"{check.category}/{check.name}" for check in self.readiness.checks if not check.ok
        ]
        blockers.extend(f"usb/{blocker}" for blocker in self.usb_setup.readiness_blockers)
        if not self.apk.present:
            blockers.append("android/Debug APK")
        if self.manual.failed:
            blockers.append("manual/manual checklist failed")
        if not self.manual.complete:
            blockers.append("manual/manual checklist incomplete")
        return tuple(dict.fromkeys(blockers))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_apk_evidence(root: Path) -> ApkEvidence:
    apk = root / DEBUG_APK_RELATIVE_PATH
    if not apk.is_file():
        return ApkEvidence(
            relative_path=DEBUG_APK_RELATIVE_PATH.as_posix(),
            present=False,
        )
    return ApkEvidence(
        relative_path=DEBUG_APK_RELATIVE_PATH.as_posix(),
        present=True,
        size_bytes=apk.stat().st_size,
        sha256=sha256_file(apk),
    )


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_record(
    *,
    root: Path = ROOT,
    manual: ManualSmokeEvidence | None = None,
    timestamp_utc: str | None = None,
    readiness: ReadinessReport | None = None,
    usb_setup: UsbSetupReport | None = None,
) -> SmokeRecord:
    resolved_root = root.resolve()
    readiness_report = readiness or collect_setup_readiness(
        root=resolved_root,
        adb=trusted_adb_path(),
    )
    usb_setup_report = usb_setup or build_usb_setup_report(root=resolved_root, execute=False)
    return SmokeRecord(
        timestamp_utc=timestamp_utc or utc_timestamp(),
        readiness=readiness_report,
        usb_setup=usb_setup_report,
        apk=collect_apk_evidence(resolved_root),
        manual=manual or ManualSmokeEvidence(),
        repo_root=resolved_root,
    )


def redaction_report(record: SmokeRecord) -> DoctorReport:
    return DoctorReport(checks=(), repo_root=record.repo_root, home=record.home)


def manual_as_dict(manual: ManualSmokeEvidence) -> dict[str, str]:
    return {
        "appLaunched": manual.app_launched.value,
        "commandSubmitted": manual.command_submitted.value,
        "macStatusDisplayed": manual.mac_status_displayed.value,
        "timelineRecorded": manual.timeline_recorded.value,
        "restartRestored": manual.restart_restored.value,
    }


def readiness_payload(readiness: ReadinessReport) -> dict[str, Any]:
    payload = json.loads(render_readiness_json(readiness))
    if not isinstance(payload, dict):
        raise TypeError("readiness renderer returned a non-object payload")
    return payload


def usb_setup_payload(usb_setup: UsbSetupReport) -> dict[str, Any]:
    payload = json.loads(render_usb_setup_json(usb_setup))
    if not isinstance(payload, dict):
        raise TypeError("USB setup renderer returned a non-object payload")
    return payload


def render_json(record: SmokeRecord) -> str:
    redactor = redaction_report(record)
    payload: dict[str, Any] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": record.physical_smoke_passed,
        "timestampUtc": record.timestamp_utc,
        "readyForManualSmoke": record.ready_for_manual_smoke,
        "manualStarted": record.manual.started,
        "manualComplete": record.manual.complete,
        "manualFailed": record.manual.failed,
        "manualPassed": record.manual.passed,
        "physicalSmokePassed": record.physical_smoke_passed,
        "blockers": [safe_text(blocker, report=redactor) for blocker in record.blockers],
        "apk": asdict(record.apk),
        "manual": manual_as_dict(record.manual),
        "readiness": readiness_payload(record.readiness),
        "usbSetup": usb_setup_payload(record.usb_setup),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_text(record: SmokeRecord) -> str:
    redactor = redaction_report(record)
    lines = ["GOFFY Moto G physical smoke record"]
    lines.append(f"timestamp: {record.timestamp_utc}")
    lines.append(f"readiness: {'ready' if record.ready_for_manual_smoke else 'not-ready'}")
    if record.manual.failed:
        manual_status_summary = "failed"
    elif record.manual.passed:
        manual_status_summary = "passed"
    else:
        manual_status_summary = "not-passed"
    lines.append(f"manual: {manual_status_summary}")
    lines.append(f"physical-smoke: {'passed' if record.physical_smoke_passed else 'not-passed'}")
    lines.append("")
    lines.append("apk:")
    lines.append(f"- path: {record.apk.relative_path}")
    lines.append(f"- present: {str(record.apk.present).lower()}")
    if record.apk.present:
        lines.append(f"- size-bytes: {record.apk.size_bytes}")
        lines.append(f"- sha256: {record.apk.sha256}")
    lines.append("")
    lines.append("manual checklist:")
    for label, status in manual_as_dict(record.manual).items():
        lines.append(f"- {label}: {status}")
    if record.blockers:
        lines.append("")
        lines.append("blockers:")
        for blocker in record.blockers:
            lines.append(f"- {safe_text(blocker, report=redactor)}")
    lines.append("")
    if record.physical_smoke_passed:
        lines.append("Physical Moto G smoke evidence is complete.")
    elif record.manual.failed:
        lines.append("The manual phone checklist has a failed item; fix it before rerunning.")
    elif not record.ready_for_manual_smoke:
        lines.append("Resolve readiness blockers before treating the phone smoke test as valid.")
    else:
        lines.append("Run the manual phone checklist and record each result.")
    return "\n".join(lines)


def manual_status(value: str) -> ManualStatus:
    normalized = value.replace("-", "_").upper()
    try:
        return ManualStatus(normalized)
    except ValueError as exc:
        allowed = ", ".join(status.value.lower().replace("_", "-") for status in ManualStatus)
        raise argparse.ArgumentTypeError(f"manual status must be one of: {allowed}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=existing_directory, default=ROOT)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--app-launched", type=manual_status, default=ManualStatus.NOT_RUN)
    parser.add_argument("--command-submitted", type=manual_status, default=ManualStatus.NOT_RUN)
    parser.add_argument("--mac-status-displayed", type=manual_status, default=ManualStatus.NOT_RUN)
    parser.add_argument("--timeline-recorded", type=manual_status, default=ManualStatus.NOT_RUN)
    parser.add_argument("--restart-restored", type=manual_status, default=ManualStatus.NOT_RUN)
    args = parser.parse_args(argv)

    manual = ManualSmokeEvidence(
        app_launched=args.app_launched,
        command_submitted=args.command_submitted,
        mac_status_displayed=args.mac_status_displayed,
        timeline_recorded=args.timeline_recorded,
        restart_restored=args.restart_restored,
    )
    record = build_record(root=args.repo_root, manual=manual)
    print(render_json(record) if args.json else render_text(record))
    return 0 if record.physical_smoke_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
