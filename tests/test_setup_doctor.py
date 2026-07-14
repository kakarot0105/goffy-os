from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.setup_doctor as setup_doctor
from scripts.android_preflight import Check
from scripts.setup_doctor import (
    DEV_MODULES,
    AdbDeviceSummary,
    AdbReverseSummary,
    DeviceCommandResult,
    DoctorCheck,
    DoctorReport,
    collect_device_checks,
    collect_doctor_report,
    collect_python_checks,
    main,
    parse_adb_devices,
    parse_adb_reverse_list,
    render_json,
    render_text,
)

ROOT = Path(__file__).resolve().parents[1]


def test_python_checks_accept_supported_runtime_and_modules() -> None:
    checks = collect_python_checks(
        version_info=(3, 12, 4),
        executable="/opt/goffy-test/python",
        module_finder=lambda module: True,
    )

    assert all(check.ok for check in checks)
    assert checks[0].detail == "Python 3.12.4 at /opt/goffy-test/python"


def test_python_checks_report_missing_runtime_and_dev_modules() -> None:
    checks = collect_python_checks(
        version_info=(3, 11, 9),
        executable="/opt/goffy-test/python",
        module_finder=lambda module: module not in {"jsonschema", "ruff"},
    )

    assert not checks[0].ok
    assert not checks[1].ok
    assert "Python 3.12+" in checks[0].remediation
    assert "jsonschema" in checks[1].detail
    assert "ruff" in checks[1].detail


def test_python_dependency_contract_covers_verifier_and_test_imports() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependency_specs = [
        *pyproject["project"]["dependencies"],
        *pyproject["project"]["optional-dependencies"]["dev"],
    ]
    expected_packages = {package_name(spec) for spec in dependency_specs}

    assert set(DEV_MODULES) == expected_packages


def package_name(dependency_spec: str) -> str:
    return re.split(r"[\[<>=!~;,\s]", dependency_spec, maxsplit=1)[0].lower()


def test_doctor_report_includes_android_preflight_checks(tmp_path: Path) -> None:
    def android_collector(root: Path) -> list[Check]:
        return [
            Check(
                name="JDK",
                ok=True,
                detail="ready",
                remediation="install JDK",
            ),
            Check(
                name="Gradle wrapper",
                ok=False,
                detail=f"missing under {root}",
                remediation="restore wrapper",
            ),
        ]

    report = collect_doctor_report(
        root=tmp_path,
        module_finder=lambda module: True,
        android_collector=android_collector,
    )

    assert not report.ok
    assert report.checks[-2] == DoctorCheck(
        category="android",
        name="JDK",
        ok=True,
        detail="ready",
        remediation="",
    )
    assert report.checks[-1] == DoctorCheck(
        category="android",
        name="Gradle wrapper",
        ok=False,
        detail=f"missing under {tmp_path}",
        remediation="restore wrapper",
    )


def test_render_text_groups_checks_and_includes_next_step() -> None:
    report = DoctorReport(
        checks=(
            DoctorCheck("python", "Python runtime", True, "ready", ""),
            DoctorCheck("android", "adb", False, "missing", "install platform tools"),
        )
    )

    rendered = render_text(report)

    assert "GOFFY setup doctor" in rendered
    assert "PYTHON" in rendered
    assert "ANDROID" in rendered
    assert "[FAIL] adb: missing" in rendered
    assert "Resolve failed checks" in rendered


def test_render_text_escapes_control_characters_and_redacts_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    report = DoctorReport(
        checks=(
            DoctorCheck(
                "android",
                "JDK",
                False,
                f"{repo}/jdk and /opt/homebrew/jdk\n[OK] forged\x1b[31m",
                f"set JAVA_HOME under {home}\rnow",
            ),
        ),
        repo_root=repo,
        home=home,
    )

    rendered = render_text(report)

    assert "[FAIL] JDK: <repo>/jdk and <path>\\n[OK] forged" in rendered
    assert "fix: set JAVA_HOME under <home>\\rnow" in rendered
    assert str(repo) not in rendered
    assert str(home) not in rendered


def test_render_json_is_machine_readable() -> None:
    repo = Path("/opt/goffy-test/repo")
    report = DoctorReport(
        checks=(DoctorCheck("python", "Python runtime", True, f"ready at {repo}", ""),),
        repo_root=repo,
    )

    payload = json.loads(render_json(report))

    assert payload["ok"] is True
    assert payload["schemaVersion"] == "goffy.setup-doctor.v1"
    assert payload["checks"][0]["category"] == "python"
    assert payload["checks"][0]["detail"] == "ready at <repo>"


def test_render_json_redacts_non_repo_absolute_paths() -> None:
    report = DoctorReport(
        checks=(
            DoctorCheck(
                "android",
                "JDK",
                False,
                "known location: /Applications/Android Studio.app/Contents/jbr/Contents/Home",
                "install under /opt/homebrew",
            ),
        )
    )

    payload = json.loads(render_json(report))

    assert payload["checks"][0]["detail"] == "known location: <path>"
    assert payload["checks"][0]["remediation"] == "install under <path>"


def test_parse_adb_devices_ignores_serials() -> None:
    devices = parse_adb_devices(
        "* daemon not running; starting now at tcp:5037\n"
        "* daemon started successfully\n"
        "List of devices attached\n"
        "ABC123 device product:foo model:moto_g transport_id:1\n"
        "XYZ987 unauthorized usb:1-2\n"
        "BOOT01 bootloader usb:1-3\n"
        "NOPERM no permissions (udev rules)\n"
    )

    assert devices == [
        AdbDeviceSummary(serial="ABC123", status="device"),
        AdbDeviceSummary(serial="XYZ987", status="unauthorized"),
        AdbDeviceSummary(serial="BOOT01", status="bootloader"),
        AdbDeviceSummary(serial="NOPERM", status="no permissions"),
    ]


def test_parse_adb_reverse_list_ignores_serials() -> None:
    entries = parse_adb_reverse_list(
        "* daemon started successfully\n"
        "host tcp:8787 tcp:8787\n"
        "ABC123 tcp:8787 tcp:8787\n"
        "XYZ987 localabstract:foo localabstract:foo\n"
        "XYZ987 tcp:9999 tcp:9999\n"
    )

    assert entries == [
        AdbReverseSummary(serial="host", local="tcp:8787", remote="tcp:8787"),
        AdbReverseSummary(serial="ABC123", local="tcp:8787", remote="tcp:8787"),
        AdbReverseSummary(serial="XYZ987", local="tcp:9999", remote="tcp:9999"),
    ]


def test_device_checks_report_missing_adb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_doctor, "discover_adb_path", lambda: None)

    checks = collect_device_checks()

    assert checks == [
        DoctorCheck(
            category="device",
            name="adb executable",
            ok=False,
            detail="adb unavailable",
            remediation="Install Android SDK Platform Tools and ensure adb is on PATH.",
        )
    ]


def test_doctor_report_skips_device_probe_when_adb_preflight_fails(tmp_path: Path) -> None:
    def android_collector(root: Path) -> list[Check]:
        return [
            Check(
                name="adb",
                ok=False,
                detail="adb not found",
                remediation="install adb",
            )
        ]

    report = collect_doctor_report(
        root=tmp_path,
        module_finder=lambda module: True,
        android_collector=android_collector,
        include_device=True,
    )

    assert report.checks[-1] == DoctorCheck(
        category="device",
        name="Device diagnostics",
        ok=False,
        detail="skipped because Android adb preflight failed",
        remediation="Fix the Android adb preflight first, then rerun with --include-device.",
    )


def test_render_json_does_not_redact_plain_slash_prose() -> None:
    report = DoctorReport(
        checks=(
            DoctorCheck(
                "device",
                "Device diagnostics",
                False,
                "skipped",
                "Fix Android / adb first.",
            ),
        )
    )

    payload = json.loads(render_json(report))

    assert payload["checks"][0]["remediation"] == "Fix Android / adb first."


def test_device_checks_accept_authorized_device_and_reverse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(setup_doctor, "discover_adb_path", lambda: Path("/opt/android/adb"))

    def runner(command: Sequence[str], root: Path, timeout: int) -> DeviceCommandResult:
        seen.append(tuple(command))
        if tuple(command)[1:] == ("devices", "-l"):
            return DeviceCommandResult(
                0,
                "List of devices attached\nABC123 device product:foo model:moto_g\n",
                "",
            )
        return DeviceCommandResult(0, "host tcp:8787 tcp:8787\n", "")

    checks = collect_device_checks(root=tmp_path, runner=runner)
    rendered = render_text(DoctorReport(tuple(checks), repo_root=tmp_path))

    assert all(check.ok for check in checks)
    assert seen == [
        ("/opt/android/adb", "devices", "-l"),
        ("/opt/android/adb", "reverse", "--list"),
    ]
    assert "ABC123" not in rendered


def test_device_checks_reject_unauthorized_device(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(setup_doctor, "discover_adb_path", lambda: Path("/opt/android/adb"))

    def runner(command: Sequence[str], root: Path, timeout: int) -> DeviceCommandResult:
        return DeviceCommandResult(
            0,
            "List of devices attached\nABC123 unauthorized usb:1-2\n",
            "",
        )

    checks = collect_device_checks(root=tmp_path, runner=runner)

    assert len(checks) == 1
    assert not checks[0].ok
    assert "unauthorized:1" in checks[0].detail


def test_device_checks_require_hub_reverse(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(setup_doctor, "discover_adb_path", lambda: Path("/opt/android/adb"))

    def runner(command: Sequence[str], root: Path, timeout: int) -> DeviceCommandResult:
        if tuple(command)[1:] == ("devices", "-l"):
            return DeviceCommandResult(0, "List of devices attached\nABC123 device\n", "")
        return DeviceCommandResult(0, "ABC123 tcp:9999 tcp:9999\n", "")

    checks = collect_device_checks(root=tmp_path, runner=runner)

    assert checks[0].ok
    assert not checks[1].ok
    assert checks[1].name == "Hub USB reverse"


def test_device_checks_require_reverse_on_authorized_device(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(setup_doctor, "discover_adb_path", lambda: Path("/opt/android/adb"))

    def runner(command: Sequence[str], root: Path, timeout: int) -> DeviceCommandResult:
        if tuple(command)[1:] == ("devices", "-l"):
            return DeviceCommandResult(
                0,
                "List of devices attached\nABC123 device\nXYZ987 unauthorized\n",
                "",
            )
        return DeviceCommandResult(0, "XYZ987 tcp:8787 tcp:8787\n", "")

    checks = collect_device_checks(root=tmp_path, runner=runner)
    rendered = render_text(DoctorReport(tuple(checks), repo_root=tmp_path))

    assert checks[0].ok
    assert not checks[1].ok
    assert "ABC123" not in rendered
    assert "XYZ987" not in rendered


def test_main_returns_zero_for_ready_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_doctor,
        "collect_doctor_report",
        lambda root, include_device=False: DoctorReport(
            checks=(DoctorCheck("python", "Python runtime", True, "ready", ""),),
            repo_root=root,
        ),
    )

    exit_code = main(["--repo-root", "/opt/goffy-test/repo"])

    assert exit_code == 0
    assert "GOFFY setup doctor" in capsys.readouterr().out


def test_main_returns_nonzero_for_blocked_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_doctor,
        "collect_doctor_report",
        lambda root, include_device=False: DoctorReport(
            checks=(DoctorCheck("android", "adb", False, "missing", "install adb"),),
            repo_root=root,
        ),
    )

    exit_code = main(["--repo-root", "/opt/goffy-test/repo", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False


def test_main_passes_include_device_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []

    def collect(root: Path, include_device: bool = False) -> DoctorReport:
        calls.append(include_device)
        return DoctorReport(
            checks=(DoctorCheck("python", "Python runtime", True, "ready", ""),),
            repo_root=root,
        )

    monkeypatch.setattr(setup_doctor, "collect_doctor_report", collect)

    assert main(["--repo-root", "/opt/goffy-test/repo", "--include-device"]) == 0
    assert calls == [True]
