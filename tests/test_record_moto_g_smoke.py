from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
import scripts.record_moto_g_smoke as smoke
from scripts.record_moto_g_smoke import (
    ApkEvidence,
    ManualSmokeEvidence,
    ManualStatus,
    SmokeRecord,
    build_record,
    collect_apk_evidence,
    main,
    manual_status,
    render_json,
    render_text,
)
from scripts.run_moto_g_usb_setup import UsbSetupReport
from scripts.verify_moto_g_readiness import DEBUG_APK_RELATIVE_PATH, ReadinessCheck, ReadinessReport


def passing_readiness(root: Path) -> ReadinessReport:
    return ReadinessReport(
        checks=(
            ReadinessCheck("android", "JDK", True, "ready", ""),
            ReadinessCheck("device", "Authorized Android device", True, "authorized:1", ""),
            ReadinessCheck("device", "Hub USB reverse", True, "tcp:8787 reverse is active", ""),
            ReadinessCheck("hub", "Hub health endpoint", True, "status:ok", ""),
            ReadinessCheck("hub", "Hub protocol version", True, "protocolVersion:0.2.0", ""),
            ReadinessCheck("hub", "Hub tool health", True, "healthy:1; unavailable:0", ""),
            ReadinessCheck("hub", "Hub tool access", True, "toolAccess:enabled", ""),
            ReadinessCheck("android", "Debug APK", True, str(root / DEBUG_APK_RELATIVE_PATH), ""),
        ),
        repo_root=root,
    )


def blocked_readiness(root: Path) -> ReadinessReport:
    return ReadinessReport(
        checks=(
            ReadinessCheck("android", "JDK", False, f"missing under {root}", "install JDK"),
            ReadinessCheck("android", "Debug APK", False, "debug APK is unavailable", "build APK"),
        ),
        repo_root=root,
    )


def passing_usb(root: Path) -> UsbSetupReport:
    return UsbSetupReport(
        executed=False,
        readiness_ok=True,
        readiness_blockers=(),
        steps=(),
        repo_root=root,
    )


def passing_manual() -> ManualSmokeEvidence:
    return ManualSmokeEvidence(
        app_launched=ManualStatus.PASS,
        command_submitted=ManualStatus.PASS,
        mac_status_displayed=ManualStatus.PASS,
        timeline_recorded=ManualStatus.PASS,
        restart_restored=ManualStatus.PASS,
    )


def write_debug_apk(root: Path, content: bytes = b"apk") -> Path:
    apk = root / DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(content)
    return apk


def test_collect_apk_evidence_hashes_fixed_debug_apk(tmp_path: Path) -> None:
    write_debug_apk(tmp_path, b"goffy-apk")

    evidence = collect_apk_evidence(tmp_path)

    assert evidence == ApkEvidence(
        relative_path=DEBUG_APK_RELATIVE_PATH.as_posix(),
        present=True,
        size_bytes=9,
        sha256="4b1a58a7a77f9a0baf3d9d6922ddc97e608b45bbac8ec79186446f9a5fbd1d9f",
    )


def test_record_passes_only_when_readiness_apk_and_manual_checks_pass(tmp_path: Path) -> None:
    write_debug_apk(tmp_path)

    record = build_record(
        root=tmp_path,
        manual=passing_manual(),
        timestamp_utc="2026-07-14T12:00:00Z",
        readiness=passing_readiness(tmp_path),
        usb_setup=passing_usb(tmp_path),
    )
    payload = json.loads(render_json(record))

    assert record.physical_smoke_passed
    assert payload["ok"] is True
    assert payload["readyForManualSmoke"] is True
    assert payload["manualPassed"] is True
    assert payload["blockers"] == []
    assert payload["apk"]["relative_path"] == DEBUG_APK_RELATIVE_PATH.as_posix()


def test_missing_apk_blocks_even_if_injected_readiness_is_ready(tmp_path: Path) -> None:
    record = build_record(
        root=tmp_path,
        manual=passing_manual(),
        timestamp_utc="2026-07-14T12:00:00Z",
        readiness=passing_readiness(tmp_path),
        usb_setup=passing_usb(tmp_path),
    )

    assert not record.ready_for_manual_smoke
    assert not record.physical_smoke_passed
    assert "android/Debug APK" in record.blockers


def test_incomplete_manual_checks_are_reported_without_claiming_success(tmp_path: Path) -> None:
    write_debug_apk(tmp_path)
    record = build_record(
        root=tmp_path,
        timestamp_utc="2026-07-14T12:00:00Z",
        readiness=passing_readiness(tmp_path),
        usb_setup=passing_usb(tmp_path),
    )
    payload = json.loads(render_json(record))

    assert not record.physical_smoke_passed
    assert payload["manualStarted"] is False
    assert payload["manualComplete"] is False
    assert payload["manualFailed"] is False
    assert "manual/manual checklist incomplete" in payload["blockers"]


def test_failed_manual_check_is_reported_even_when_incomplete(tmp_path: Path) -> None:
    write_debug_apk(tmp_path)
    record = build_record(
        root=tmp_path,
        manual=ManualSmokeEvidence(app_launched=ManualStatus.FAIL),
        timestamp_utc="2026-07-14T12:00:00Z",
        readiness=passing_readiness(tmp_path),
        usb_setup=passing_usb(tmp_path),
    )
    payload = json.loads(render_json(record))
    rendered = render_text(record)

    assert not record.physical_smoke_passed
    assert payload["manualFailed"] is True
    assert "manual/manual checklist failed" in payload["blockers"]
    assert "manual/manual checklist incomplete" in payload["blockers"]
    assert "manual: failed" in rendered
    assert "failed item" in rendered


def test_render_text_and_json_redact_repo_paths(tmp_path: Path) -> None:
    record = SmokeRecord(
        timestamp_utc="2026-07-14T12:00:00Z",
        readiness=blocked_readiness(tmp_path),
        usb_setup=UsbSetupReport(
            executed=False,
            readiness_ok=False,
            readiness_blockers=(str(tmp_path / "secret"),),
            steps=(),
            repo_root=tmp_path,
        ),
        apk=ApkEvidence(DEBUG_APK_RELATIVE_PATH.as_posix(), present=False),
        manual=ManualSmokeEvidence(app_launched=ManualStatus.FAIL),
        repo_root=tmp_path,
    )

    rendered = render_text(record)
    payload = json.loads(render_json(record))

    assert str(tmp_path) not in rendered
    assert str(tmp_path) not in json.dumps(payload)
    assert "usb/<repo>/secret" in payload["blockers"]


def test_manual_status_accepts_cli_spellings_and_rejects_unknown() -> None:
    assert manual_status("pass") is ManualStatus.PASS
    assert manual_status("not-run") is ManualStatus.NOT_RUN

    with pytest.raises(argparse.ArgumentTypeError):
        manual_status("maybe")


def test_main_returns_nonzero_until_manual_physical_smoke_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_debug_apk(tmp_path)
    monkeypatch.setattr(
        smoke,
        "collect_setup_readiness",
        lambda *, root, adb: passing_readiness(root),
    )
    monkeypatch.setattr(
        smoke,
        "build_usb_setup_report",
        lambda *, root, execute: passing_usb(root),
    )

    assert main(["--repo-root", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["physicalSmokePassed"] is False

    assert (
        main(
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
    assert json.loads(capsys.readouterr().out)["physicalSmokePassed"] is True


def test_build_record_uses_trusted_setup_readiness_not_path_adb(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_debug_apk(tmp_path)
    seen_adb: list[Path | None] = []

    def collect(*, root: Path, adb: Path | None, **kwargs: Any) -> ReadinessReport:
        seen_adb.append(adb)
        return passing_readiness(root)

    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: None)
    monkeypatch.setattr(smoke, "collect_setup_readiness", collect)
    monkeypatch.setattr(
        smoke,
        "build_usb_setup_report",
        lambda *, root, execute: passing_usb(root),
    )

    record = build_record(root=tmp_path, manual=passing_manual())

    assert record.ready_for_manual_smoke
    assert seen_adb == [None]


def test_build_record_invokes_usb_setup_report_in_plan_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_debug_apk(tmp_path)
    seen_execute: list[bool] = []

    def build_usb(*, root: Path, execute: bool = True) -> UsbSetupReport:
        seen_execute.append(execute)
        return passing_usb(root)

    monkeypatch.setattr(
        smoke,
        "collect_setup_readiness",
        lambda *, root, adb: passing_readiness(root),
    )
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: None)
    monkeypatch.setattr(smoke, "build_usb_setup_report", build_usb)

    record = build_record(root=tmp_path, manual=passing_manual())

    assert record.physical_smoke_passed
    assert seen_execute == [False]
