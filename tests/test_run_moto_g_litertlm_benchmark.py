from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path

import scripts.run_moto_g_litertlm_benchmark as benchmark
from scripts.run_moto_g_device_smoke import CommandResult
from scripts.run_moto_g_litertlm_benchmark import (
    DEVICE_RESULT_PATH,
    StepStatus,
    build_report,
    is_allowed_device_model_path,
    resolve_device_model_path,
)

SERIAL = "ZY32LBQLMQ"
ADB_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL} device usb:2-1.2 product:kansas_g_sys model:moto_g___2025 device:kansas\n"
)


def write_apks(root: Path) -> None:
    debug_apk = root / benchmark.DEBUG_APK_RELATIVE_PATH
    test_apk = root / benchmark.DEBUG_TEST_APK_RELATIVE_PATH
    debug_apk.parent.mkdir(parents=True)
    test_apk.parent.mkdir(parents=True)
    debug_apk.write_bytes(b"debug apk")
    test_apk.write_bytes(b"test apk")


def test_plan_mode_does_not_execute_commands(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = build_report(
        root=tmp_path,
        model=tmp_path / "tiny.litertlm",
        runner=runner,
    )

    assert report.ok
    assert not report.executed
    assert seen == []
    assert all(step.status is StepStatus.PLANNED for step in report.steps)
    assert any(step.name == "Push local model" for step in report.steps)


def test_execute_requires_explicit_device_mutation_confirmation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        device_model_path="/sdcard/Android/data/dev.goffy.os/files/models/tiny.litertlm",
    )

    assert not report.ok
    assert not report.executed
    assert "missing explicit --confirm-device-mutation" in {step.detail for step in report.steps}


def test_execute_requires_model_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_apks(tmp_path)
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {"provide --model or --device-model-path"}


def test_execute_rejects_non_app_owned_device_model_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_apks(tmp_path)
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        device_model_path="/sdcard/Download/tiny.litertlm",
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {
        "device model path must be app-owned and end with .litertlm"
    }


def test_execute_rejects_traversal_device_model_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        device_model_path=(
            "/sdcard/Android/data/dev.goffy.os/files/models/"
            "../../../../../../sdcard/Download/tiny.litertlm"
        ),
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {
        "device model path must be app-owned and end with .litertlm"
    }


def test_device_model_path_normalization_accepts_owned_storage_prefixes() -> None:
    assert is_allowed_device_model_path(
        "/sdcard/Android/data/dev.goffy.os/files/models//tiny.litertlm"
    )
    assert (
        resolve_device_model_path(
            None,
            "/storage/emulated/0/Android/data/dev.goffy.os/files/models//tiny.litertlm",
        )
        == "/storage/emulated/0/Android/data/dev.goffy.os/files/models/tiny.litertlm"
    )


def test_execute_runs_fixed_instrumentation_and_pulls_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_apks(tmp_path)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    adb.parent.mkdir(parents=True)
    adb.write_text("", encoding="utf-8")
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: adb)
    seen: list[tuple[str, ...]] = []
    prompt = "benchmark prompt; echo $HOME # 'quoted'"

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        if normalized == (str(adb), "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if ":app:assembleDebugAndroidTest" in normalized:
            return CommandResult(0, "BUILD SUCCESSFUL\n", "")
        if normalized[-3:-1] == ("install", "-r"):
            return CommandResult(0, "Success\n", "")
        if any("instrument" in part for part in normalized):
            remote_command = normalized[-1]
            remote_parts = shlex.split(remote_command)
            assert DEVICE_RESULT_PATH in remote_command
            assert remote_parts[remote_parts.index("prompt") + 1] == prompt
            assert "timeoutMillis" in remote_command
            assert "300000" in remote_command
            return CommandResult(0, "OK (1 test)\n", "")
        if "pull" in normalized:
            destination = Path(normalized[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                '{"status":"PASS","outputChunkCount":1}\n',
                encoding="utf-8",
            )
            return CommandResult(0, "1 file pulled\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        device_model_path="/sdcard/Android/data/dev.goffy.os/files/models/tiny.litertlm",
        prompt=prompt,
        runner=runner,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert report.executed
    assert report.result_artifact is not None
    assert Path(report.result_artifact).is_file()
    assert any(any("instrument" in part for part in command) for command in seen)
    assert any(
        step.name == "Verify benchmark JSON" and step.status is StepStatus.OK
        for step in report.steps
    )


def test_execute_surfaces_json_level_benchmark_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_apks(tmp_path)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    adb.parent.mkdir(parents=True)
    adb.write_text("", encoding="utf-8")
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: adb)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == (str(adb), "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if ":app:assembleDebugAndroidTest" in normalized:
            return CommandResult(0, "BUILD SUCCESSFUL\n", "")
        if normalized[-3:-1] == ("install", "-r"):
            return CommandResult(0, "Success\n", "")
        if any("instrument" in part for part in normalized):
            return CommandResult(0, "OK (1 test)\n", "")
        if "pull" in normalized:
            destination = Path(normalized[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                (
                    '{"status":"FAIL","outputChunkCount":0,'
                    '"errorClass":"NoModelOutput",'
                    '"errorMessage":"model returned without streaming any chunks"}\n'
                ),
                encoding="utf-8",
            )
            return CommandResult(0, "1 file pulled\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        device_model_path="/sdcard/Android/data/dev.goffy.os/files/models/tiny.litertlm",
        prompt="benchmark prompt",
        runner=runner,
        output_directory=tmp_path / "artifacts",
    )

    verify_step = next(step for step in report.steps if step.name == "Verify benchmark JSON")
    assert not report.ok
    assert report.result_artifact is not None
    assert Path(report.result_artifact).is_file()
    assert verify_step.status is StepStatus.FAIL
    assert "NoModelOutput" in verify_step.detail
    assert "outputChunkCount=0" in verify_step.detail


def test_execute_stops_before_pull_when_instrumentation_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    write_apks(tmp_path)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    adb.parent.mkdir(parents=True)
    adb.write_text("", encoding="utf-8")
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: adb)
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        if normalized == (str(adb), "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if ":app:assembleDebugAndroidTest" in normalized:
            return CommandResult(0, "BUILD SUCCESSFUL\n", "")
        if normalized[-3:-1] == ("install", "-r"):
            return CommandResult(0, "Success\n", "")
        if any("instrument" in part for part in normalized):
            return CommandResult(1, "", "Error: Invalid instrumentation")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        device_model_path="/sdcard/Android/data/dev.goffy.os/files/models/tiny.litertlm",
        prompt="benchmark prompt",
        runner=runner,
        output_directory=tmp_path / "artifacts",
    )

    assert not report.ok
    assert any(step.name == "Run LiteRT-LM benchmark" for step in report.steps)
    assert not any("pull" in command for command in seen)
