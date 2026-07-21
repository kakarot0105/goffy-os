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


COMMAND_FIELD_ONLY_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,1454][660,1594]" />',
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
        '  <node text="Battery status matched the local tool contract." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][620,1420]" />',
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
        '  <node text="mac.system_info output matched the registered schema." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][620,1420]" />',
        "</hierarchy>",
    ]
)


MAC_PROCESS_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,900][660,1040]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,1100][660,1180]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1200][260,1240]" />',
        '  <node text="What is running on my Mac" class="android.widget.TextView" '
        'enabled="true" bounds="[60,1200][430,1240]" />',
        '  <node text="VERIFIED" class="android.widget.TextView" enabled="true" '
        'bounds="[500,1200][650,1240]" />',
        '  <node text="MAC  /  mac.processes.list  /  SAFE" '
        'class="android.widget.TextView" enabled="true" bounds="[60,1260][600,1300]" />',
        '  <node text="MAC PROCESSES / 2" class="android.widget.TextView" enabled="true" '
        'bounds="[60,1320][320,1360]" />',
        '  <node text="mac.processes.list output matched the registered schema." '
        'class="android.widget.TextView" enabled="true" bounds="[60,1380][660,1420]" />',
        "</hierarchy>",
    ]
)


DEBUG_SETUP_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="SECURE HUB LINK" class="android.widget.TextView" '
        'enabled="true" bounds="[60,13][205,55]" />',
        '  <node text="NOT CONFIGURED" class="android.widget.TextView" '
        'enabled="true" bounds="[60,55][233,97]" />',
        '  <node text="Hide" class="android.widget.TextView" enabled="true" '
        'bounds="[582,38][637,73]" />',
        '  <node text="ws://127.0.0.1:8787/ws/v1" '
        'class="android.widget.EditText" enabled="true" bounds="[60,301][660,413]" />',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,427][660,580]" />',
        '  <node text="Development bearer token" class="android.widget.TextView" '
        'enabled="true" bounds="[88,735][367,763]" />',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,776][660,871]" />',
        "</hierarchy>",
    ]
)


DEBUG_LINK_BUTTON_UI_XML = DEBUG_SETUP_UI_XML.replace(
    "</hierarchy>",
    '  <node text="Debug link" class="android.widget.TextView" enabled="true" '
    'bounds="[485,890][618,925]" />\n'
    "</hierarchy>",
)


DEBUG_LINK_CONFIGURED_UI_XML = "\n".join(
    [
        "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
        '<hierarchy rotation="0">',
        '  <node text="SECURE HUB LINK" class="android.widget.TextView" '
        'enabled="true" bounds="[60,13][205,55]" />',
        '  <node text="ws://127.0.0.1:8787/ws/v1" class="android.widget.TextView" '
        'enabled="true" bounds="[60,55][297,97]" />',
        '  <node text="" class="android.widget.EditText" enabled="true" '
        'bounds="[60,175][660,315]" />',
        '  <node text="Send" class="android.widget.TextView" enabled="true" '
        'bounds="[520,336][660,420]" />',
        '  <node text="TASK TIMELINE" class="android.widget.TextView" enabled="true" '
        'bounds="[60,505][260,545]" />',
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
        "execute mode only supports the fixed MAC smoke commands",
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


def test_submit_command_reveals_send_button_with_bounded_scroll(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    ui_outputs = iter(
        (
            COMMAND_FIELD_ONLY_UI_XML,
            COMMAND_FIELD_ONLY_UI_XML,
            BASE_UI_XML,
            PHONE_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(ui_outputs), "")
            except StopIteration:
                return CommandResult(0, PHONE_UI_XML, "")
        return CommandResult(0, "ok", "")

    result = smoke.submit_and_verify_command(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        wait_timeout_seconds=5,
        command=smoke.DEFAULT_PHONE_COMMAND,
        expected_markers=("VERIFIED", "%", "Battery status matched the local tool contract."),
        step_name="PHONE command smoke",
        artifact_prefix="phone-command",
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "swipe",
        "360",
        "1450",
        "360",
        "650",
        "450",
    ) in seen
    assert (output_directory / "phone-command.xml").is_file()


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


def test_include_mac_can_smoke_process_list_command(
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
                return CommandResult(0, MAC_PROCESS_UI_XML, "")
            return CommandResult(0, PHONE_UI_XML if cat_calls >= 5 else BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        mac_command=smoke.DEFAULT_MAC_PROCESS_COMMAND,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert any(
        step.name == "MAC command smoke" and step.status is StepStatus.OK for step in report.steps
    )


def test_debug_hub_token_file_must_stay_under_validation_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / smoke.DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    token_file = tmp_path.parent / f"{tmp_path.name}-outside-token"
    token_file.write_text("a" * 32, encoding="utf-8")
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: adb)

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        debug_hub_token_file=token_file,
        trusted_root=tmp_path,
    )

    assert not report.ok
    assert any(
        step.detail == "debug Hub token file must live under .goffy-validation"
        for step in report.steps
    )


def test_debug_hub_token_file_invalid_utf8_returns_bounded_failure(tmp_path: Path) -> None:
    token_file = tmp_path / ".goffy-validation" / "runtime" / "dev-hub-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_bytes(b"\xff\xfe\xfd")

    token, failure = smoke.read_debug_hub_token(tmp_path, token_file)

    assert token == ""
    assert failure is not None
    assert failure.status is StepStatus.FAIL
    assert failure.detail == "debug Hub token file could not be read"


def test_debug_hub_link_rechecks_after_second_bounded_scroll(tmp_path: Path) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    token = "abcdef0123456789abcdef0123456789"  # noqa: S105
    token_file = tmp_path / ".goffy-validation" / "runtime" / "dev-hub-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text(token, encoding="utf-8")
    output_directory = tmp_path / "artifacts"
    output_directory.mkdir()
    target = smoke.DeviceTarget(serial=SERIAL, model="moto g - 2025")
    ui_outputs = iter(
        (
            DEBUG_SETUP_UI_XML,
            DEBUG_SETUP_UI_XML,
            DEBUG_SETUP_UI_XML,
            DEBUG_LINK_BUTTON_UI_XML,
            DEBUG_LINK_CONFIGURED_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            return CommandResult(0, next(ui_outputs), "")
        return CommandResult(0, "ok", "")

    result = smoke.configure_debug_hub_link(
        adb=adb,
        target=target,
        root=tmp_path,
        runner=runner,
        timeout_seconds=30,
        token_file=token_file,
        output_directory=output_directory,
    )

    assert result.status is StepStatus.OK
    swipes = [
        command
        for command in seen
        if adb_args(command) == ("shell", "input", "swipe", "360", "1500", "360", "900", "500")
    ]
    assert len(swipes) == 2


def test_include_mac_can_configure_debug_hub_link_from_local_token_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    apk = tmp_path / smoke.DEBUG_APK_RELATIVE_PATH
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b"apk")
    token = "abcdef0123456789abcdef0123456789"  # noqa: S105
    token_file = tmp_path / ".goffy-validation" / "runtime" / "dev-hub-token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text(token, encoding="utf-8")
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
    setup_outputs = iter(
        (
            DEBUG_SETUP_UI_XML,
            DEBUG_LINK_BUTTON_UI_XML,
            DEBUG_LINK_CONFIGURED_UI_XML,
            DEBUG_LINK_CONFIGURED_UI_XML,
            BASE_UI_XML,
        )
    )
    seen: list[tuple[str, ...]] = []
    submitted_command: str | None = None

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal submitted_command
        seen.append(tuple(command))
        target = target_runner(command)
        if target is not None:
            return target
        if adb_args(command) == ("shell", "input", "text", "check%smy%sbattery%slevel"):
            submitted_command = "phone"
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("shell", "input", "text", "check%smy%sMac%sstatus"):
            submitted_command = "mac"
            return CommandResult(0, "ok", "")
        if adb_args(command) == ("exec-out", "cat", smoke.REMOTE_UI_XML):
            try:
                return CommandResult(0, next(setup_outputs), "")
            except StopIteration:
                if submitted_command == "mac":
                    return CommandResult(0, MAC_UI_XML, "")
                if submitted_command == "phone":
                    return CommandResult(0, PHONE_UI_XML, "")
                return CommandResult(0, BASE_UI_XML, "")
        if adb_args(command) == ("shell", "pidof", smoke.PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(0, "ok", "")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        include_mac=True,
        debug_hub_token_file=token_file,
        runner=runner,
        trusted_root=tmp_path,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert any(
        step.name == "Configure debug Hub link" and step.status is StepStatus.OK
        for step in report.steps
    )
    assert any(
        step.name == "MAC command smoke" and step.status is StepStatus.OK for step in report.steps
    )
    assert (
        str(adb),
        "-s",
        SERIAL,
        "shell",
        "input",
        "text",
        token,
    ) in seen
    assert (tmp_path / "artifacts" / "debug-hub-link.xml").is_file()
    assert token not in (tmp_path / "artifacts" / "debug-hub-link.xml").read_text(encoding="utf-8")
    rendered = render_text(report)
    payload = render_json(report)
    assert token not in rendered
    assert token not in payload


def test_command_window_requires_markers_after_matching_command() -> None:
    assert command_window_contains(
        PHONE_UI_XML,
        "check my battery level",
        ("VERIFIED", "%", "Battery status matched the local tool contract."),
    )
    assert not command_window_contains(
        PHONE_UI_XML,
        "check my battery level",
        ("VERIFIED", "Darwin", "mac.system_info output matched the registered schema."),
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
