from __future__ import annotations

import json
from pathlib import Path

import pytest
import scripts.guide_moto_g_validation as guide
import scripts.record_moto_g_smoke as smoke
from scripts.guide_moto_g_validation import GuideStatus, build_report, render_json, render_text
from scripts.run_moto_g_usb_setup import UsbSetupReport
from scripts.verify_moto_g_readiness import DEBUG_APK_RELATIVE_PATH, ReadinessCheck, ReadinessReport


def readiness_report(
    root: Path,
    *,
    reverse_ok: bool = True,
    jdk_ok: bool = True,
    trusted_adb_ok: bool = True,
) -> ReadinessReport:
    device_checks = (
        (
            ReadinessCheck("device", "Authorized Android device", True, "authorized:1", ""),
            ReadinessCheck(
                "device",
                "Hub USB reverse",
                reverse_ok,
                "tcp:8787 reverse is active" if reverse_ok else "tcp:8787 reverse missing",
                "",
            ),
        )
        if trusted_adb_ok
        else (
            ReadinessCheck(
                "device",
                "trusted SDK adb executable",
                False,
                "trusted SDK platform-tools adb unavailable",
                "",
            ),
        )
    )
    return ReadinessReport(
        checks=(
            ReadinessCheck("android", "JDK", jdk_ok, "ready" if jdk_ok else f"missing {root}", ""),
            ReadinessCheck("android", "adb", True, "ready", ""),
            *device_checks,
            ReadinessCheck("hub", "Hub health endpoint", True, "status:ok", ""),
            ReadinessCheck("hub", "Hub protocol version", True, "protocolVersion:0.2.0", ""),
            ReadinessCheck("hub", "Hub tool health", True, "healthy:1; unavailable:0", ""),
            ReadinessCheck("hub", "Hub tool access", True, "toolAccess:enabled", ""),
            ReadinessCheck("android", "Debug APK", True, str(root / DEBUG_APK_RELATIVE_PATH), ""),
        ),
        repo_root=root,
    )


def usb_report(root: Path, *, blockers: tuple[str, ...] = ()) -> UsbSetupReport:
    return UsbSetupReport(
        executed=False,
        readiness_ok=not blockers,
        readiness_blockers=blockers,
        steps=(),
        repo_root=root,
    )


def apk_evidence(present: bool = True) -> smoke.ApkEvidence:
    return smoke.ApkEvidence(
        relative_path=DEBUG_APK_RELATIVE_PATH.as_posix(),
        present=present,
        size_bytes=10 if present else None,
        sha256="0" * 64 if present else None,
    )


def passing_manual() -> smoke.ManualSmokeEvidence:
    return smoke.ManualSmokeEvidence(
        app_launched=smoke.ManualStatus.PASS,
        command_submitted=smoke.ManualStatus.PASS,
        mac_status_displayed=smoke.ManualStatus.PASS,
        timeline_recorded=smoke.ManualStatus.PASS,
        restart_restored=smoke.ManualStatus.PASS,
    )


def smoke_record(
    root: Path,
    *,
    reverse_ok: bool = True,
    jdk_ok: bool = True,
    trusted_adb_ok: bool = True,
    manual: smoke.ManualSmokeEvidence | None = None,
    usb_blockers: tuple[str, ...] = (),
    apk_present: bool = True,
) -> smoke.SmokeRecord:
    return smoke.SmokeRecord(
        timestamp_utc="2026-07-14T12:00:00Z",
        readiness=readiness_report(
            root,
            reverse_ok=reverse_ok,
            jdk_ok=jdk_ok,
            trusted_adb_ok=trusted_adb_ok,
        ),
        usb_setup=usb_report(root, blockers=usb_blockers),
        apk=apk_evidence(apk_present),
        manual=manual or smoke.ManualSmokeEvidence(),
        repo_root=root,
    )


def test_guide_blocks_on_prerequisite_failures_and_redacts_paths(tmp_path: Path) -> None:
    report = build_report(
        record=smoke_record(tmp_path, jdk_ok=False, usb_blockers=("android/JDK",))
    )
    payload = json.loads(render_json(report))
    rendered = render_text(report)

    assert report.next_step_id == "preflight-readiness"
    assert report.steps[0].status is GuideStatus.BLOCKED
    assert payload["steps"][0]["status"] == "BLOCKED"
    assert str(tmp_path) not in rendered
    assert str(tmp_path) not in json.dumps(payload)


def test_trusted_adb_blocker_points_to_same_smoke_record_source(tmp_path: Path) -> None:
    report = build_report(
        record=smoke_record(
            tmp_path,
            trusted_adb_ok=False,
            usb_blockers=("device/trusted SDK adb executable",),
        )
    )

    assert report.next_step_id == "preflight-readiness"
    assert "device/trusted SDK adb executable" in report.steps[0].detail
    assert report.steps[0].command == guide.readiness_command()
    assert report.steps[0].command[1] == "scripts/record_moto_g_smoke.py"


def test_guide_recommends_confirmed_usb_setup_when_only_reverse_is_missing(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path, reverse_ok=False))
    usb_step = report.steps[1]

    assert report.next_step_id == "usb-setup"
    assert report.steps[0].status is GuideStatus.DONE
    assert usb_step.status is GuideStatus.READY
    assert usb_step.mutates_device
    assert usb_step.requires_confirmation
    assert usb_step.command == guide.usb_setup_command()


def test_guide_prompts_manual_phone_smoke_when_ready(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path))

    assert report.next_step_id == "manual-phone-smoke"
    assert report.steps[1].status is GuideStatus.DONE
    assert report.steps[2].status is GuideStatus.MANUAL
    assert "Show my Mac status" in report.steps[2].detail


def test_guide_surfaces_manual_failure_before_evidence(tmp_path: Path) -> None:
    manual = smoke.ManualSmokeEvidence(app_launched=smoke.ManualStatus.FAIL)
    report = build_report(record=smoke_record(tmp_path, manual=manual))
    rendered = render_text(report)
    payload = json.loads(render_json(report))

    assert report.next_step_id == "manual-phone-smoke"
    assert report.steps[2].status is GuideStatus.BLOCKED
    assert report.steps[3].status is GuideStatus.BLOCKED
    assert "checklist item failed" in rendered
    assert payload["smokeRecord"]["manualFailed"] is True


def test_guide_is_complete_when_smoke_record_passes(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path, manual=passing_manual()))
    payload = json.loads(render_json(report))

    assert report.ok
    assert report.next_step_id is None
    assert all(step.status is GuideStatus.DONE for step in report.steps)
    assert payload["ok"] is True
    assert payload["nextStepId"] is None


def test_main_returns_nonzero_until_physical_smoke_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def build_smoke(
        root: Path, manual: smoke.ManualSmokeEvidence | None = None
    ) -> smoke.SmokeRecord:
        return smoke_record(root, manual=manual or smoke.ManualSmokeEvidence())

    monkeypatch.setattr("scripts.guide_moto_g_validation.smoke.build_record", build_smoke)

    assert guide.main(["--repo-root", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False

    assert (
        guide.main(
            [
                "--repo-root",
                str(tmp_path),
                "--json",
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
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["ok"] is True
