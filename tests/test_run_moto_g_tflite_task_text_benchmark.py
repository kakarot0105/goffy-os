from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.run_moto_g_tflite_task_text_benchmark as benchmark
from scripts.run_moto_g_device_smoke import CommandResult
from scripts.run_moto_g_tflite_task_text_benchmark import (
    DEVICE_RESULT_PATH,
    StepStatus,
    build_report,
    classifier_json_step,
    command_sha256,
    is_allowed_device_model_path,
    resolve_device_model_path,
)

SERIAL = "ZY32LBQLMQ"
MODEL_SHA = "8cbbb42f2d62dcf85898a5f729e15a772f60f8b8321bb5f38ce42c6e6e04e87a"
ADB_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL} device usb:2-1.2 product:kansas_g_sys model:moto_g___2025 device:kansas\n"
)


def write_modeldebug_apks(root: Path) -> None:
    app_apk = root / benchmark.MODEL_DEBUG_APK_RELATIVE_PATH
    test_apk = root / benchmark.MODEL_DEBUG_TEST_APK_RELATIVE_PATH
    app_apk.parent.mkdir(parents=True)
    test_apk.parent.mkdir(parents=True)
    app_apk.write_bytes(b"model debug apk")
    test_apk.write_bytes(b"model debug test apk")


def test_plan_mode_does_not_execute_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = build_report(
        root=tmp_path,
        model=tmp_path / "tiny.tflite",
        runner=runner,
    )

    assert report.ok
    assert not report.executed
    assert seen == []
    assert all(step.status is StepStatus.PLANNED for step in report.steps)
    assert any("-Pgoffy.testBuildType=modelDebug" in step.command for step in report.steps)


def test_execute_requires_explicit_device_mutation_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        device_model_path="/sdcard/Android/data/dev.goffy.os.model/files/models/tiny.tflite",
    )

    assert not report.ok
    assert not report.executed
    assert "missing explicit --confirm-device-mutation" in {step.detail for step in report.steps}


def test_execute_requires_model_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_modeldebug_apks(tmp_path)
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {"provide --model or --device-model-path"}


def test_execute_rejects_non_app_owned_device_model_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_modeldebug_apks(tmp_path)
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        device_model_path="/sdcard/Download/tiny.tflite",
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {
        "device model path must be app-owned and end with .tflite"
    }


def test_execute_rejects_litertlm_device_model_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        device_model_path="/sdcard/Android/data/dev.goffy.os.model/files/models/tiny.litertlm",
    )

    assert not report.ok
    assert {step.detail for step in report.steps} == {
        "device model path must be app-owned and end with .tflite"
    }


def test_device_model_path_normalization_accepts_owned_storage_prefixes() -> None:
    assert is_allowed_device_model_path(
        "/sdcard/Android/data/dev.goffy.os.model/files/models//tiny.tflite"
    )
    assert (
        resolve_device_model_path(
            None,
            "/storage/emulated/0/Android/data/dev.goffy.os.model/files/models//tiny.tflite",
        )
        == "/storage/emulated/0/Android/data/dev.goffy.os.model/files/models/tiny.tflite"
    )


def test_execute_runs_fixed_modeldebug_instrumentation_and_pulls_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_modeldebug_apks(tmp_path)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    adb.parent.mkdir(parents=True)
    adb.write_text("", encoding="utf-8")
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: adb)
    seen: list[tuple[str, ...]] = []
    command_text = "classify this; echo $HOME # 'quoted'"

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        if normalized == (str(adb), "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if ":app:assembleModelDebugAndroidTest" in normalized:
            assert "-Pgoffy.testBuildType=modelDebug" in normalized
            return CommandResult(0, "BUILD SUCCESSFUL\n", "")
        if normalized[-3:-1] == ("install", "-r"):
            return CommandResult(0, "Success\n", "")
        if any("instrument" in part for part in normalized):
            remote_command = normalized[-1]
            remote_parts = shlex.split(remote_command)
            assert "TfliteTaskTextClassifierInstrumentedTest" in remote_command
            assert (
                "dev.goffy.os.model.test/androidx.test.runner.AndroidJUnitRunner" in remote_command
            )
            assert DEVICE_RESULT_PATH in remote_command
            assert remote_parts[remote_parts.index("command") + 1] == command_text
            return CommandResult(0, "OK (1 test)\n", "")
        if "pull" in normalized:
            destination = Path(normalized[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                (
                    '{"status":"PASS","categoryCount":2,"topLabel":"PHONE",'
                    f'"topScore":0.91,"modelBytes":4096,"modelSha256":"{MODEL_SHA}",'
                    f'"commandSha256":"{command_sha256(command_text)}","inferenceMillis":12,'
                    '"observationType":"Candidate","observationRoute":"PHONE",'
                    '"observationConfidence":0.91,"nonAuthoritative":true}\n'
                ),
                encoding="utf-8",
            )
            return CommandResult(0, "1 file pulled\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        device_model_path="/sdcard/Android/data/dev.goffy.os.model/files/models/tiny.tflite",
        command_text=command_text,
        runner=runner,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert report.executed
    assert report.result_artifact is not None
    assert Path(report.result_artifact).is_file()
    assert any(
        step.name == "Verify classifier benchmark JSON" and step.status is StepStatus.OK
        for step in report.steps
    )
    assert any(any("instrument" in part for part in command) for command in seen)


def test_classifier_json_requires_non_authoritative_output(tmp_path: Path) -> None:
    artifact = tmp_path / "tflite-task-text-classifier.json"
    artifact.write_text(
        (
            '{"status":"PASS","categoryCount":1,"topLabel":"PHONE",'
            '"topScore":0.91,"inferenceMillis":12,'
            '"observationType":"Candidate","observationRoute":"PHONE",'
            '"observationConfidence":0.91}\n'
        ),
        encoding="utf-8",
    )

    step = classifier_json_step(artifact)

    assert step.status is StepStatus.FAIL
    assert "non-authoritative" in step.detail


def test_classifier_json_requires_rejection_reason(tmp_path: Path) -> None:
    artifact = tmp_path / "tflite-task-text-classifier.json"
    command_hash = command_sha256("rejected command")
    artifact.write_text(
        (
            '{"status":"PASS","categoryCount":1,"topLabel":"NOTES",'
            f'"topScore":0.91,"modelBytes":4096,"modelSha256":"{MODEL_SHA}",'
            f'"commandSha256":"{command_hash}",'
            '"inferenceMillis":12,'
            '"observationType":"Rejected","nonAuthoritative":true}\n'
        ),
        encoding="utf-8",
    )

    step = classifier_json_step(artifact)

    assert step.status is StepStatus.FAIL
    assert "rejected observation" in step.detail


def test_classifier_json_requires_candidate_confidence_gate(tmp_path: Path) -> None:
    artifact = tmp_path / "tflite-task-text-classifier.json"
    command_hash = command_sha256("low confidence command")
    artifact.write_text(
        (
            '{"status":"PASS","categoryCount":1,"topLabel":"PHONE",'
            f'"topScore":0.51,"modelBytes":4096,"modelSha256":"{MODEL_SHA}",'
            f'"commandSha256":"{command_hash}",'
            '"inferenceMillis":12,'
            '"observationType":"Candidate","observationRoute":"PHONE",'
            '"observationConfidence":0.51,"nonAuthoritative":true}\n'
        ),
        encoding="utf-8",
    )

    step = classifier_json_step(artifact)

    assert step.status is StepStatus.FAIL
    assert "confidence gate" in step.detail
