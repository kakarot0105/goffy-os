from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.collect_modeldebug_idle_cleanup_evidence as idle
from scripts.run_moto_g_device_smoke import CommandResult
from scripts.run_moto_g_modeldebug_observation_smoke import MODEL_DEBUG_PACKAGE_NAME
from scripts.verify_modeldebug_acceptance import build_acceptance_report

SERIAL = "ZY32LBQLMQ"
ADB_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL} device usb:2-1.2 product:kansas_g_sys model:moto_g___2025 device:kansas\n"
)
MODEL_SHA = "b1baab462f6be49d70eada79d715c2c52cd9ece0cad00bddf6a2c097d23498e9"


def test_plan_mode_does_not_execute_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = idle.build_evidence(
        root=tmp_path,
        model_sha256=MODEL_SHA,
        runner=runner,
    )

    assert not report.ok
    assert not report.executed
    assert seen == []
    assert "not executed; rerun with --execute to collect evidence" in report.blockers


def test_execute_collects_idle_evidence_when_process_exited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    observation_report = write_observation_report(tmp_path)
    slept: list[int] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[3:] == ("shell", "pidof", MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=observation_report,
        runner=runner,
        sleep=slept.append,
    )

    assert report.ok
    assert report.executed
    assert slept == [60]
    assert report.provider_closed_after_idle is True
    assert report.process_running_after_idle is False
    assert report.total_pss_kb is None


def test_execute_blocks_slow_observation_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    observation_report = write_observation_report(tmp_path, elapsed_millis=22_000)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        _ = (command, cwd, timeout)
        raise AssertionError("slow observation preflight should not run ADB probes")

    report = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=observation_report,
        runner=runner,
        sleep=lambda _: None,
    )

    assert not report.ok
    assert not report.executed
    assert any("observation took 22000 ms" in blocker for blocker in report.blockers)


def test_execute_can_collect_idle_diagnostics_for_slow_observation_with_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    observation_report = write_observation_report(tmp_path, elapsed_millis=22_000)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[3:] == ("shell", "pidof", MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=observation_report,
        runner=runner,
        sleep=lambda _: None,
        max_observation_millis=30_000,
    )

    assert report.ok
    assert report.executed
    assert report.provider_closed_after_idle is True


def test_execute_blocks_missing_teardown_marker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    observation_report = write_observation_report(tmp_path, include_marker=False)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        _ = (command, cwd, timeout)
        raise AssertionError("preflight failure should not run ADB probes")

    report = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=observation_report,
        runner=runner,
        sleep=lambda _: None,
    )

    assert not report.ok
    assert not report.executed
    assert any("modeldebug-logcat.txt is missing" in blocker for blocker in report.blockers)


def test_execute_blocks_forged_observation_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    output_dir = tmp_path / "forged"
    output_dir.mkdir()
    (output_dir / "modeldebug-logcat.txt").write_text(
        "I/GoffyLocalModel: observation_engine_scope_closed\n",
        encoding="utf-8",
    )
    forged_report = tmp_path / "forged-report.json"
    forged_report.write_text(
        json.dumps(
            {
                "model_sha256": MODEL_SHA,
                "output_directory": str(output_dir),
            }
        ),
        encoding="utf-8",
    )

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        _ = (command, cwd, timeout)
        raise AssertionError("invalid report should not run ADB probes")

    report = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=forged_report,
        runner=runner,
        sleep=lambda _: None,
    )

    assert not report.ok
    assert not report.executed
    assert any("schema_version mismatch" in blocker for blocker in report.blockers)


def test_execute_blocks_running_process_with_high_idle_pss(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    observation_report = write_observation_report(tmp_path)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[3:] == ("shell", "pidof", MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(0, "4242\n", "")
        if normalized[3:] == ("shell", "dumpsys", "meminfo", MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(0, "TOTAL PSS: 128000\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=observation_report,
        runner=runner,
        sleep=lambda _: None,
        max_idle_pss_kb=64_000,
    )

    assert not report.ok
    assert report.process_running_after_idle is True
    assert report.total_pss_kb == 128_000
    assert "idle cleanup TOTAL PSS exceeds 64000 KB" in report.blockers


def test_execute_accepts_running_process_below_idle_pss_when_provider_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    observation_report = write_observation_report(tmp_path)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[3:] == ("shell", "pidof", MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(0, "4242\n", "")
        if normalized[3:] == ("shell", "dumpsys", "meminfo", MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(0, "TOTAL PSS: 32000\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=observation_report,
        runner=runner,
        sleep=lambda _: None,
        max_idle_pss_kb=64_000,
    )

    assert report.ok
    assert report.process_running_after_idle is True
    assert report.provider_closed_after_idle is True
    assert "modelDebug process remained running below idle PSS budget" in report.warnings


def test_execute_blocks_failed_pidof_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    observation_report = write_observation_report(tmp_path)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[3:] == ("shell", "pidof", MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(1, "", "device offline")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    report = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=observation_report,
        runner=runner,
        sleep=lambda _: None,
    )

    assert not report.ok
    assert report.executed
    assert report.provider_closed_after_idle is False
    assert "modelDebug process status probe failed" in report.blockers


def test_execute_cli_returns_nonzero_for_preflight_failure(tmp_path: Path) -> None:
    exit_code = idle.main(
        [
            "--execute",
            "--model-sha256",
            "invalid",
            "--output",
            str(tmp_path / "idle-cleanup.json"),
        ]
    )

    assert exit_code == 1


def test_evidence_output_is_accepted_by_production_verifier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(idle, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    observation_report = write_observation_report(tmp_path)

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[3:] == ("shell", "pidof", MODEL_DEBUG_PACKAGE_NAME):
            return CommandResult(1, "", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    evidence = idle.build_evidence(
        root=tmp_path,
        execute=True,
        observation_report=observation_report,
        runner=runner,
        sleep=lambda _: None,
    )
    idle_path = idle.write_report(evidence, tmp_path / "idle-cleanup.json")

    acceptance = build_acceptance_report(
        reports=[observation_report],
        idle_evidence_json=idle_path,
        min_runs=1,
    )

    assert evidence.ok
    assert acceptance.ok


def write_observation_report(
    tmp_path: Path,
    *,
    include_marker: bool = True,
    elapsed_millis: int = 8_000,
) -> Path:
    output_dir = tmp_path / "run-1"
    output_dir.mkdir()
    (output_dir / "final-ui.xml").write_text(
        "FAILED\nNo safe deterministic route is available\n",
        encoding="utf-8",
    )
    (output_dir / "battery-after.txt").write_text("level: 100\n", encoding="utf-8")
    (output_dir / "meminfo-after.txt").write_text("TOTAL PSS: 123456\n", encoding="utf-8")
    marker = "observation_engine_scope_closed" if include_marker else "other line"
    (output_dir / "modeldebug-logcat.txt").write_text(
        f"I/GoffyLocalModel: {marker}\n",
        encoding="utf-8",
    )
    report = tmp_path / "modeldebug-observation-report.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": "goffy.moto-g-modeldebug-observation-smoke.v1",
                "executed": True,
                "ok": True,
                "output_directory": str(output_dir),
                "command": "open settings",
                "model_source": "qwen3_0_6b_mixed_int4.litertlm",
                "model_sha256": MODEL_SHA,
                "observation_elapsed_millis": elapsed_millis,
                "steps": [
                    {"name": "Verify Moto G target", "status": "OK"},
                    {"name": "Unsupported command observation smoke", "status": "OK"},
                    {"name": "Dump UI", "status": "OK"},
                    {"name": "Capture battery snapshot", "status": "OK"},
                    {"name": "Capture memory snapshot", "status": "OK"},
                    {"name": "Capture bounded modelDebug logcat", "status": "OK"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return report
