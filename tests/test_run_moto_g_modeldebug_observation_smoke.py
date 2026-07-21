from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import scripts.run_moto_g_modeldebug_observation_smoke as smoke
from scripts.run_moto_g_device_smoke import CommandResult
from scripts.run_moto_g_modeldebug_observation_smoke import StepStatus, build_report
from scripts.verify_modeldebug_acceptance import (
    IDLE_EVIDENCE_SCHEMA_VERSION,
    build_acceptance_report,
)

SERIAL = "ZY32LBQLMQ"
ADB_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL} device usb:2-1.2 product:kansas_g_sys model:moto_g___2025 device:kansas\n"
)
READY_TEXT = (
    "Local model ready for observe-only fallback; deterministic routing remains authoritative."
)


def test_plan_mode_does_not_execute_commands(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = build_report(root=tmp_path, model=tmp_path / "router.litertlm", runner=runner)

    assert report.ok
    assert not report.executed
    assert seen == []
    assert all(step.status is StepStatus.PLANNED for step in report.steps)
    assert any(step.name == "Seed private router model" for step in report.steps)


def test_execute_requires_explicit_confirmation_and_model(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = build_report(root=tmp_path, execute=True)

    assert not report.ok
    assert not report.executed
    assert {step.detail for step in report.steps} == {
        "missing explicit --confirm-device-mutation",
        "provide --model",
    }


def test_execute_rejects_unsafe_inputs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    model = tmp_path / "bad name.litertlm"
    model.write_text("model", encoding="utf-8")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        model=model,
        command="open settings && send secrets",
    )

    assert not report.ok
    assert not report.executed
    assert {step.detail for step in report.steps} == {
        "host model basename must be safe and end with .litertlm",
        "execute mode only supports the fixed observe-only command `open settings`",
        "command must be 1..120 chars and ADB-input safe",
    }


def test_execute_rejects_custom_safe_command(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    model = tmp_path / "router.litertlm"
    model.write_text("model", encoding="utf-8")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        model=model,
        command="show my battery status",
    )

    assert not report.ok
    assert not report.executed
    assert [step.detail for step in report.steps] == [
        "execute mode only supports the fixed observe-only command `open settings`",
    ]


def test_execute_runs_fixed_modeldebug_observation_flow(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    monotonic_time = 1_000.0

    def monotonic() -> float:
        nonlocal monotonic_time
        monotonic_time += 1.0
        return monotonic_time

    monkeypatch.setattr(smoke.time, "monotonic", monotonic)
    model = tmp_path / "qwen3_0_6b_mixed_int4.litertlm"
    model.write_text("model", encoding="utf-8")
    seen: list[tuple[str, ...]] = []
    xml_values = [
        disabled_runtime_xml(),
        disabled_runtime_xml(),
        enabled_runtime_xml(),
        enabled_runtime_with_command_xml(),
        enabled_runtime_with_command_xml(),
        enabled_runtime_with_command_xml(),
        enabled_runtime_with_typed_command_xml(),
        terminal_observation_xml(),
        terminal_observation_xml(),
    ]
    xml_sequence = iter(xml_values)
    xml_dump_count = 0

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        nonlocal xml_dump_count
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if ":app:assembleModelDebug" in normalized:
            return CommandResult(0, "BUILD SUCCESSFUL\n", "")
        if normalized[-3:-1] == ("install", "-r"):
            return CommandResult(0, "Success\n", "")
        if normalized[3] == "push":
            assert normalized[-1].endswith(
                "/data/local/tmp/goffy-modeldebug-qwen3_0_6b_mixed_int4.litertlm"
            )
            return CommandResult(0, "1 file pushed\n", "")
        if "run-as" in normalized or normalized[-4:-2] == ("shell", "rm"):
            return CommandResult(0, "ok\n", "")
        if normalized[3:] == ("shell", "am", "force-stop", smoke.MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(0, "", "")
        if normalized[3:6] == ("shell", "am", "start"):
            assert smoke.MODEL_DEBUG_MAIN_ACTIVITY in normalized
            return CommandResult(0, "Status: ok\nTotalTime: 2500\n", "")
        if normalized[3:6] == ("shell", "uiautomator", "dump"):
            return CommandResult(0, "UI hierchary dumped\n", "")
        if normalized[3:5] == ("exec-out", "cat"):
            xml_dump_count += 1
            try:
                return CommandResult(0, next(xml_sequence), "")
            except StopIteration:
                return CommandResult(0, terminal_observation_xml(), "")
        if normalized[3:5] == ("shell", "input"):
            return CommandResult(0, "", "")
        if normalized[3:] == ("shell", "dumpsys", "battery"):
            return CommandResult(0, "level: 100\nAC powered: true\n", "")
        if normalized[3:6] == ("shell", "dumpsys", "meminfo"):
            return CommandResult(0, "TOTAL PSS: 123456\n", "")
        if normalized[3:] == ("shell", "pidof", smoke.MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(0, "4242\n", "")
        if "logcat" in normalized:
            return CommandResult(0, "GOFFY log line\nobservation_engine_scope_closed\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        model=model,
        runner=runner,
        output_directory=tmp_path / "artifacts",
    )

    assert report.ok
    assert report.executed
    assert report.observation_elapsed_millis is not None
    assert xml_dump_count <= len(xml_values) + 1
    assert (tmp_path / "artifacts" / "final-ui.xml").is_file()
    assert any(
        command[3:9]
        == (
            "shell",
            "run-as",
            smoke.MODEL_DEBUG_PACKAGE_NAME,
            "mkdir",
            "-p",
            smoke.PRIVATE_MODEL_DIR,
        )
        for command in seen
    )
    assert any(
        step.name == "Unsupported command observation smoke" and step.status is StepStatus.OK
        for step in report.steps
    )

    report_path = smoke.write_report_artifact(report)
    assert report_path is not None
    idle_evidence = write_idle_cleanup_evidence(tmp_path, model_sha256=report.model_sha256)
    acceptance = build_acceptance_report(
        reports=[report_path],
        idle_evidence_json=idle_evidence,
        min_runs=1,
    )

    assert acceptance.ok


def test_seed_stops_after_stage_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    model = tmp_path / "router.litertlm"
    model.write_text("model", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if ":app:assembleModelDebug" in normalized or normalized[3:5] == ("install", "-r"):
            return CommandResult(0, "ok\n", "")
        if normalized[3] == "push":
            return CommandResult(1, "", "push failed")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        model=model,
        runner=runner,
        output_directory=tmp_path / "artifacts",
    )

    assert not report.ok
    assert report.steps[-1].name == "Stage local model"
    assert not any("run-as" in command for command in seen)


def test_seed_cleans_staged_model_after_copy_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(smoke, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    model = tmp_path / "router.litertlm"
    model.write_text("model", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if ":app:assembleModelDebug" in normalized or normalized[3:5] == ("install", "-r"):
            return CommandResult(0, "ok\n", "")
        if normalized[3] == "push":
            return CommandResult(0, "1 file pushed\n", "")
        if normalized[3:] == (
            "shell",
            "run-as",
            smoke.MODEL_DEBUG_PACKAGE_NAME,
            "mkdir",
            "-p",
            smoke.PRIVATE_MODEL_DIR,
        ):
            return CommandResult(0, "ok\n", "")
        if normalized[3:] == (
            "shell",
            "run-as",
            smoke.MODEL_DEBUG_PACKAGE_NAME,
            "cp",
            "/data/local/tmp/goffy-modeldebug-router.litertlm",
            smoke.PRIVATE_ROUTER_MODEL_PATH,
        ):
            return CommandResult(1, "", "copy failed")
        if normalized[3:6] == ("shell", "rm", "-f"):
            return CommandResult(0, "removed\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        model=model,
        runner=runner,
        output_directory=tmp_path / "artifacts",
    )

    assert not report.ok
    assert report.steps[-1].name == "Seed private router model"
    assert "staged model cleanup attempted" in report.steps[-1].detail
    assert any(
        command[3:]
        == (
            "shell",
            "rm",
            "-f",
            "/data/local/tmp/goffy-modeldebug-router.litertlm",
        )
        for command in seen
    )


def test_write_report_artifact_persists_executed_report(tmp_path: Path) -> None:
    report = build_report(root=tmp_path)
    report = smoke.ModelDebugObservationReport(
        schema_version=report.schema_version,
        executed=True,
        ok=True,
        output_directory=str(tmp_path / "artifacts"),
        command=report.command,
        model_source=report.model_source,
        model_sha256=report.model_sha256,
        observation_elapsed_millis=123,
        steps=report.steps,
    )

    report_path = smoke.write_report_artifact(report)

    assert report_path == tmp_path / "artifacts" / "modeldebug-observation-report.json"
    assert report_path.is_file()
    assert '"observation_elapsed_millis": 123' in report_path.read_text(encoding="utf-8")


def disabled_runtime_xml() -> str:
    return ui_xml(
        [
            "GOFFY",
            "GOFFY LITE",
            "LOCAL MODEL",
            "LOCAL MODEL RUNTIME",
            "Local model is off; deterministic routing is authoritative.",
            "Enable setting",
            "TASK TIMELINE",
        ],
        edit_text=False,
    )


def enabled_runtime_xml() -> str:
    return ui_xml(
        [
            "GOFFY",
            "GOFFY LITE",
            "LOCAL MODEL",
            "OBSERVE ONLY",
            "LOCAL MODEL RUNTIME",
            READY_TEXT,
            "Disable setting",
            "TASK TIMELINE",
        ],
        edit_text=False,
    )


def enabled_runtime_with_command_xml() -> str:
    return ui_xml(
        [
            "GOFFY",
            "GOFFY LITE",
            "OBSERVE ONLY",
            READY_TEXT,
            "TASK TIMELINE",
            "No actions yet. Every GOFFY step will appear here.",
            "Send",
        ],
        edit_text=True,
    )


def enabled_runtime_with_typed_command_xml() -> str:
    return ui_xml(
        [
            "GOFFY",
            "GOFFY LITE",
            "OBSERVE ONLY",
            READY_TEXT,
            "TASK TIMELINE",
            "No actions yet. Every GOFFY step will appear here.",
            "Send",
        ],
        edit_text=True,
        edit_text_value="open settings",
    )


def terminal_observation_xml() -> str:
    return ui_xml(
        [
            "GOFFY",
            "GOFFY LITE",
            "OBSERVE ONLY",
            READY_TEXT,
            "TASK TIMELINE",
            "open settings",
            "FAILED",
            (
                "No safe deterministic route is available for this command yet. "
                "Model output did not match the strict routing JSON schema."
            ),
            "OBSERVE Received typed command input",
            "PLAN No deterministic route selected",
            "PREPARE Local model ready for observe-only fallback.",
            "ERROR Model output did not match the strict routing JSON schema.",
        ],
        edit_text=True,
    )


def ui_xml(texts: list[str], *, edit_text: bool, edit_text_value: str = "") -> str:
    nodes = []
    top = 10
    for index, text in enumerate(texts):
        nodes.append(
            node_xml(
                index=index,
                text=text,
                class_name="android.widget.TextView",
                top=top,
            )
        )
        top += 50
    if edit_text:
        nodes.append(
            node_xml(
                index=len(nodes),
                text=edit_text_value,
                class_name="android.widget.EditText",
                top=top,
            )
        )
    return f'<hierarchy rotation="0">{"".join(nodes)}</hierarchy>'


def node_xml(index: int, text: str, class_name: str, top: int) -> str:
    return (
        f'<node index="{index}" text="{text}" resource-id="" class="{class_name}" '
        f'package="{smoke.MODEL_DEBUG_PACKAGE_NAME}" content-desc="" checkable="false" '
        f'checked="false" clickable="false" enabled="true" focusable="false" '
        f'focused="false" scrollable="false" long-clickable="false" password="false" '
        f'selected="false" bounds="[10,{top}][700,{top + 40}]" drawing-order="{index}" hint="" />'
    )


def write_idle_cleanup_evidence(tmp_path: Path, *, model_sha256: str | None) -> Path:
    path = tmp_path / "idle-cleanup.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": IDLE_EVIDENCE_SCHEMA_VERSION,
                "ok": True,
                "waited_seconds": 60,
                "model_sha256": model_sha256,
                "provider_closed_after_idle": True,
                "process_running_after_idle": False,
                "total_pss_kb": None,
                "blockers": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    return path
