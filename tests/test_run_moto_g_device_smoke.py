from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.run_moto_g_device_smoke as smoke
from scripts.run_moto_g_device_smoke import (
    CommandResult,
    DeviceSmokeStep,
    StepStatus,
    build_report,
    command_window_contains,
    main,
    render_json,
    render_text,
    timeline_command_occurrences,
)

SERIAL = "ZY32LBQLMQ"
ADB_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL} device usb:2-1.2 product:kansas_g_sys model:moto_g___2025 device:kansas\n"
)

BASE_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        "</hierarchy>",
    ]
)


PHONE_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="check my battery level" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][400,1240]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="PHONE  /  phone.battery.status  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="42%" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1320][160,1360]" />',
        "</hierarchy>",
    ]
)


MAC_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="check my Mac status" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][400,1240]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="MAC  /  mac.system_info  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="Darwin / arm64" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1320][260,1360]" />',
        "</hierarchy>",
    ]
)


def adb_args(command: Sequence[str]) -> tuple[str, ...]:
    if len(command) >= 3 and command[1] == "-s":
        return tuple(command[3:])
    return tuple(command[1:])


def target_runner(command: Sequence[str]) -> CommandResult | None:
    args = tuple(command[1:])
    if args == ("devices", "-l"):
        return CommandResult(0, ADB_DEVICES, "")
    if adb_args(command) == ("shell", "getprop", "ro.product.model"):
        return CommandResult(0, "moto g - 2025\n", "")
    return None


def test_plan_mode_never_executes_device_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = build_report(root=tmp_path, runner=runner, include_mac=True)

    assert report.ok
    assert not report.executed
    assert seen == []
    assert all(step.status is StepStatus.PLANNED for step in report.steps)
    assert report.mac_command == smoke.DEFAULT_MAC_COMMAND


def test_execute_requires_explicit_device_mutation_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(root=tmp_path, execute=True, trusted_root=tmp_path)

    assert not report.ok
    assert not report.executed
    assert report.steps[0].detail == "missing explicit --confirm-device-mutation"


def test_execute_blocks_missing_debug_apk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {"android/debug APK missing"}


def test_execute_rejects_non_smoke_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    apk = tmp_path / smoke.DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        phone_command="turn on flashlight",
        mac_command="open calculator",
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {
        "execute mode only supports the fixed PHONE smoke command",
        "execute mode only supports the fixed MAC smoke command",
    }


def test_execute_requires_single_or_explicit_moto_g_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / smoke.DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        if tuple(command[1:]) == ("devices", "-l"):
            return CommandResult(
                0,
                "List of devices attached\n"
                "one device model:moto_g___2025\n"
                "two device model:moto_g___2025\n",
                "",
            )
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert report.steps == (
        DeviceSmokeStep(
            name="Verify Moto G target",
            status=StepStatus.FAIL,
            command=(str(adb), "devices", "-l"),
            detail="multiple authorized devices",
            remediation="Connect exactly one Moto G or pass --device-serial.",
        ),
    )


def test_execute_rejects_non_moto_g_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / smoke.DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        if tuple(command[1:]) == ("devices", "-l"):
            return CommandResult(0, "List of devices attached\npixel device model:Pixel_9\n", "")
        if adb_args(command) == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "Pixel 9\n", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert report.steps[0].detail == "connected device is not the approved Moto G target"


def test_execute_runs_fixed_setup_launch_and_phone_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / smoke.DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.OK,
            artifact="final.png",
        ),
    )
    seen: list[tuple[str, ...]] = []
    cat_calls = 0

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal cat_calls
        seen.append(tuple(command))
        target = target_runner(command)
        if target is not None:
            return target
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            cat_calls += 1
            return CommandResult(0, PHONE_UI_XML if cat_calls >= 5 else BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(0, "1234\n", "")
        if adb_args(command) == ("logcat", "-d", "--pid", "1234", "-t", "200"):
            return CommandResult(0, "goffy log\n", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert report.executed
    assert (tmp_path / "artifacts" / "phone-command.xml").is_file()
    assert (tmp_path / "artifacts" / "goffy-logcat.txt").read_text(
        encoding="utf-8"
    ) == "goffy log\n"
    assert (str(adb), "-s", SERIAL, "reverse", "tcp:8787", "tcp:8787") in seen
    assert (str(adb), "-s", SERIAL, "install", "-r", str(apk)) in seen
    assert (str(adb), "-s", SERIAL, "shell", "am", "force-stop", smoke.PACKAGE_NAME) in seen
    assert (str(adb), "-s", SERIAL, "shell", "am", "start", "-W", "-n", smoke.MAIN_ACTIVITY) in seen
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "text",
        "check%smy%sbattery%slevel",
    ) in seen
    assert (str(adb), "-s", SERIAL, "logcat", "-d", "--pid", "1234", "-t", "200") in seen


def test_stale_ui_does_not_pass_without_fresh_command_card(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / smoke.DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(name="Capture screenshot", status=StepStatus.OK),
    )

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        target = target_runner(command)
        if target is not None:
            return target
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            return CommandResult(0, PHONE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
        wait_timeout_seconds=1,
    )

    assert not report.ok
    assert any(
        step.name == "PHONE command smoke"
        and step.status is StepStatus.FAIL
        and "fresh command card" in step.detail
        for step in report.steps
    )


def test_include_mac_requires_mac_visible_markers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / smoke.DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)
    monkeypatch.setattr(
        smoke,
        "capture_screenshot",
        lambda **kwargs: DeviceSmokeStep(
            name="Capture screenshot",
            status=StepStatus.OK,
            artifact="final.png",
        ),
    )
    cat_calls = 0

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal cat_calls
        target = target_runner(command)
        if target is not None:
            return target
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            cat_calls += 1
            if cat_calls >= 8:
                return CommandResult(0, MAC_UI_XML, "")
            return CommandResult(0, PHONE_UI_XML if cat_calls >= 5 else BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert any(
        step.name == "MAC command smoke" and step.status is StepStatus.OK for step in report.steps
    )


def test_command_window_requires_markers_after_matching_command() -> None:
    assert command_window_contains(
        PHONE_UI_XML,
        "check my battery level",
        ("VERIFIED", "PHONE", "phone.battery.status", "%"),
    )
    assert not command_window_contains(
        PHONE_UI_XML,
        "check my battery level",
        ("VERIFIED", "MAC", "mac.system_info", "Darwin"),
    )
    assert timeline_command_occurrences(PHONE_UI_XML, "check my battery level") == 1


def test_renderers_redact_paths_and_mark_mutating_steps(tmp_path: Path) -> None:
    report = smoke.DeviceSmokeReport(
        executed=True,
        ok=False,
        output_directory=str(tmp_path / "artifacts"),
        phone_command=str(tmp_path / "phone-command"),
        mac_command=str(tmp_path / "mac-command"),
        steps=(
            DeviceSmokeStep(
                name="Launch GOFFY",
                status=StepStatus.OK,
                command=("/opt/android/adb", "shell", "am", "start", "-n", smoke.MAIN_ACTIVITY),
                mutates_device=True,
                detail=str(tmp_path / "detail"),
                artifact="final.png",
            ),
        ),
        repo_root=tmp_path,
    )

    rendered = render_text(report)
    payload = render_json(report)

    assert str(tmp_path) not in rendered
    assert str(tmp_path) not in payload
    assert "mutates-device: true" in rendered
    assert "final.png" in rendered


def test_main_plan_json_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json"]) == 0

    assert '"schemaVersion": "goffy.moto-g-device-smoke.v1"' in capsys.readouterr().out
