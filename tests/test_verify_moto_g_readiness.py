from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
from scripts.setup_doctor import DoctorCheck, DoctorReport
from scripts.verify_moto_g_readiness import (
    HubProbeResult,
    ReadinessCheck,
    bounded_hub_timeout,
    collect_hub_checks,
    collect_readiness_report,
    existing_directory,
    main,
    render_json,
    render_text,
)

from goffy_protocol import PROTOCOL_VERSION


def passing_doctor(root: Path) -> DoctorReport:
    return DoctorReport(
        checks=(
            DoctorCheck("android", "JDK", True, f"ready under {root}", ""),
            DoctorCheck("device", "Authorized Android device", True, "authorized:1", ""),
            DoctorCheck("device", "Hub USB reverse", True, "tcp:8787 reverse is active", ""),
        ),
        repo_root=root,
    )


def passing_hub_probe(timeout_seconds: float) -> HubProbeResult:
    return HubProbeResult(
        status_code=200,
        body=json.dumps(
            {
                "status": "ok",
                "protocolVersion": PROTOCOL_VERSION,
                "toolAccess": "enabled",
                "healthyToolCount": 1,
                "unavailableToolCount": 0,
                "toolRegistryRevision": 1,
            }
        ),
    )


def test_readiness_report_passes_when_all_prerequisites_are_ready(tmp_path: Path) -> None:
    apk = tmp_path / "android/app/build/outputs/apk/debug/app-debug.apk"
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")

    report = collect_readiness_report(
        root=tmp_path,
        doctor_collector=passing_doctor,
        hub_probe=passing_hub_probe,
    )

    assert report.ok
    assert [check.name for check in report.checks][-5:] == [
        "Hub health endpoint",
        "Hub protocol version",
        "Hub tool health",
        "Hub tool access",
        "Debug APK",
    ]


def test_readiness_report_fails_closed_for_missing_apk(tmp_path: Path) -> None:
    report = collect_readiness_report(
        root=tmp_path,
        doctor_collector=passing_doctor,
        hub_probe=passing_hub_probe,
    )

    assert not report.ok
    assert report.checks[-1] == ReadinessCheck(
        category="android",
        name="Debug APK",
        ok=False,
        detail="debug APK is unavailable",
        remediation="Run Android Gradle assembly on a machine with JDK 17 and Android SDK 36.",
    )


def test_hub_checks_fail_when_hub_is_unreachable() -> None:
    def probe(timeout_seconds: float) -> HubProbeResult:
        raise OSError("connection refused")

    checks = collect_hub_checks(probe=probe)

    assert checks == [
        ReadinessCheck(
            category="hub",
            name="Hub health endpoint",
            ok=False,
            detail="unreachable on 127.0.0.1:8787 (OSError)",
            remediation="Start GOFFY Hub locally, then rerun this readiness check.",
        )
    ]


def test_hub_checks_require_tool_health_and_access() -> None:
    def probe(timeout_seconds: float) -> HubProbeResult:
        return HubProbeResult(
            status_code=200,
            body=json.dumps(
                {
                    "status": "degraded",
                    "protocolVersion": PROTOCOL_VERSION,
                    "toolAccess": "disabled",
                    "healthyToolCount": 0,
                    "unavailableToolCount": 1,
                }
            ),
        )

    checks = collect_hub_checks(probe=probe)

    assert checks[0].ok
    assert checks[1].ok
    assert not checks[2].ok
    assert not checks[3].ok


def test_hub_checks_require_current_protocol_version() -> None:
    def probe(timeout_seconds: float) -> HubProbeResult:
        return HubProbeResult(
            status_code=200,
            body=json.dumps(
                {
                    "status": "ok",
                    "protocolVersion": "0.1.0",
                    "toolAccess": "enabled",
                    "healthyToolCount": 1,
                    "unavailableToolCount": 0,
                }
            ),
        )

    checks = collect_hub_checks(probe=probe)

    assert checks[0].ok
    assert checks[1] == ReadinessCheck(
        category="hub",
        name="Hub protocol version",
        ok=False,
        detail="protocolVersion mismatch",
        remediation=(
            f"Start a Hub that reports GOFFY protocol {PROTOCOL_VERSION} before "
            "running Mac status from the phone."
        ),
    )


def test_hub_checks_reject_contradictory_ok_status_with_unavailable_tools() -> None:
    def probe(timeout_seconds: float) -> HubProbeResult:
        return HubProbeResult(
            status_code=200,
            body=json.dumps(
                {
                    "status": "ok",
                    "protocolVersion": PROTOCOL_VERSION,
                    "toolAccess": "enabled",
                    "healthyToolCount": 1,
                    "unavailableToolCount": 5,
                }
            ),
        )

    checks = collect_hub_checks(probe=probe)

    assert checks[0].ok
    assert checks[1].ok
    assert checks[2] == ReadinessCheck(
        category="hub",
        name="Hub tool health",
        ok=False,
        detail="healthy:1; unavailable:5",
        remediation="Wait for Hub tool health to recover or inspect local Hub logs.",
    )
    assert checks[3].ok


def test_hub_checks_reject_boolean_tool_counts() -> None:
    def probe(timeout_seconds: float) -> HubProbeResult:
        return HubProbeResult(
            status_code=200,
            body=json.dumps(
                {
                    "status": "ok",
                    "protocolVersion": PROTOCOL_VERSION,
                    "toolAccess": "enabled",
                    "healthyToolCount": True,
                    "unavailableToolCount": False,
                }
            ),
        )

    checks = collect_hub_checks(probe=probe)

    assert checks[0].ok
    assert checks[1].ok
    assert not checks[2].ok
    assert checks[2].detail == "tool health counters invalid"
    assert checks[3].ok


def test_hub_checks_do_not_reflect_invalid_health_strings() -> None:
    def probe(timeout_seconds: float) -> HubProbeResult:
        return HubProbeResult(
            status_code=200,
            body=json.dumps(
                {
                    "status": "token=secret",
                    "protocolVersion": "serial=ZX1G22",
                    "toolAccess": "bearer=secret",
                    "healthyToolCount": "token=secret",
                    "unavailableToolCount": "serial=ZX1G22",
                }
            ),
        )

    checks = collect_hub_checks(probe=probe)
    rendered_details = " ".join(check.detail for check in checks)

    assert rendered_details == (
        "status invalid protocolVersion mismatch tool health counters invalid toolAccess invalid"
    )
    assert "secret" not in rendered_details
    assert "ZX1G22" not in rendered_details


def test_hub_checks_reject_non_object_json() -> None:
    def probe(timeout_seconds: float) -> HubProbeResult:
        return HubProbeResult(status_code=200, body="[]")

    checks = collect_hub_checks(probe=probe)

    assert checks == [
        ReadinessCheck(
            category="hub",
            name="Hub health endpoint",
            ok=False,
            detail="HTTP 200 but response JSON was not an object",
            remediation="Restart GOFFY Hub and inspect its local logs.",
        )
    ]


def test_renderers_redact_paths(tmp_path: Path) -> None:
    report = collect_readiness_report(
        root=tmp_path,
        doctor_collector=passing_doctor,
        hub_probe=passing_hub_probe,
    )

    rendered = render_text(report)
    payload = json.loads(render_json(report))

    assert str(tmp_path) not in rendered
    assert payload["checks"][0]["detail"] == "ready under <repo>"


def test_main_returns_nonzero_for_blocked_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "scripts.verify_moto_g_readiness.collect_readiness_report",
        lambda root, hub_timeout_seconds=2.0: collect_readiness_report(
            root=root,
            doctor_collector=passing_doctor,
            hub_probe=passing_hub_probe,
        ),
    )

    assert main(["--repo-root", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_bounded_hub_timeout_rejects_unbounded_values() -> None:
    assert bounded_hub_timeout("2.5") == 2.5

    with pytest.raises(argparse.ArgumentTypeError):
        bounded_hub_timeout("0")

    with pytest.raises(argparse.ArgumentTypeError):
        bounded_hub_timeout("11")

    with pytest.raises(argparse.ArgumentTypeError):
        bounded_hub_timeout("nan")


def test_existing_directory_rejects_missing_repo_root(tmp_path: Path) -> None:
    assert existing_directory(str(tmp_path)) == tmp_path

    with pytest.raises(argparse.ArgumentTypeError):
        existing_directory(str(tmp_path / "missing"))


def test_main_rejects_missing_repo_root_without_echoing_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SystemExit):
        main(["--repo-root", str(missing)])

    assert str(missing) not in capsys.readouterr().err
