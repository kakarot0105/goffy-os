from __future__ import annotations

import json
from pathlib import Path

from scripts.run_moto_g_modeldebug_observation_smoke import (
    DEFAULT_COMMAND,
)
from scripts.run_moto_g_modeldebug_observation_smoke import (
    JSON_SCHEMA_VERSION as OBSERVATION_SCHEMA_VERSION,
)
from scripts.verify_modeldebug_acceptance import (
    IDLE_EVIDENCE_SCHEMA_VERSION,
    JSON_SCHEMA_VERSION,
    build_acceptance_report,
    main,
)

MODEL_SHA = "b1baab462f6be49d70eada79d715c2c52cd9ece0cad00bddf6a2c097d23498e9"


def test_modeldebug_acceptance_accepts_repeated_fast_runs_and_idle_cleanup(
    tmp_path: Path,
) -> None:
    reports = [write_observation_report(tmp_path, index, elapsed=8_000) for index in range(3)]
    idle = write_idle_evidence(tmp_path)

    report = build_acceptance_report(reports=reports, idle_evidence_json=idle)

    assert report.schema_version == JSON_SCHEMA_VERSION
    assert report.ok
    assert report.status == "ACCEPTED"
    assert len(report.accepted_runs) == 3
    assert report.idle_cleanup.provider_closed_after_idle is True


def test_modeldebug_acceptance_blocks_too_few_reports_and_missing_idle(
    tmp_path: Path,
) -> None:
    report_path = write_observation_report(tmp_path, 0, elapsed=8_000)

    report = build_acceptance_report(reports=[report_path], idle_evidence_json=None)

    assert not report.ok
    assert "at least 3 executed modelDebug observation reports are required" in report.blockers
    assert "idle cleanup evidence JSON was not supplied" in report.blockers


def test_modeldebug_acceptance_blocks_slow_observation(tmp_path: Path) -> None:
    reports = [write_observation_report(tmp_path, index, elapsed=8_000) for index in range(2)]
    reports.append(write_observation_report(tmp_path, 2, elapsed=37_581))
    idle = write_idle_evidence(tmp_path)

    report = build_acceptance_report(reports=reports, idle_evidence_json=idle)

    assert not report.ok
    assert any("observation took 37581 ms" in blocker for blocker in report.blockers)


def test_modeldebug_acceptance_blocks_idle_process_with_high_pss(tmp_path: Path) -> None:
    reports = [write_observation_report(tmp_path, index, elapsed=8_000) for index in range(3)]
    idle = write_idle_evidence(
        tmp_path,
        process_running_after_idle=True,
        total_pss_kb=128_000,
    )

    report = build_acceptance_report(reports=reports, idle_evidence_json=idle)

    assert not report.ok
    assert any("idle cleanup TOTAL PSS" in blocker for blocker in report.blockers)


def test_modeldebug_acceptance_blocks_logcat_crash_marker(tmp_path: Path) -> None:
    reports = [write_observation_report(tmp_path, index, elapsed=8_000) for index in range(3)]
    (tmp_path / "run-1" / "modeldebug-logcat.txt").write_text(
        "FATAL EXCEPTION: main\n",
        encoding="utf-8",
    )
    idle = write_idle_evidence(tmp_path)

    report = build_acceptance_report(reports=reports, idle_evidence_json=idle)

    assert not report.ok
    assert any(
        "modeldebug-logcat.txt contains `FATAL EXCEPTION`" in item for item in report.blockers
    )


def test_modeldebug_acceptance_blocks_missing_engine_scope_marker(
    tmp_path: Path,
) -> None:
    reports = [write_observation_report(tmp_path, index, elapsed=8_000) for index in range(3)]
    (tmp_path / "run-1" / "modeldebug-logcat.txt").write_text(
        "GOFFY log line\n",
        encoding="utf-8",
    )
    idle = write_idle_evidence(tmp_path)

    report = build_acceptance_report(reports=reports, idle_evidence_json=idle)

    assert not report.ok
    assert any(
        "modeldebug-logcat.txt is missing `observation_engine_scope_closed`" in item
        for item in report.blockers
    )


def test_modeldebug_acceptance_cli_reports_blocked_json(
    tmp_path: Path,
    capsys,
) -> None:
    report_path = write_observation_report(tmp_path, 0, elapsed=8_000)

    exit_code = main(["--json", str(report_path)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["status"] == "BLOCKED"
    assert "idle cleanup evidence JSON was not supplied" in payload["blockers"]


def write_observation_report(tmp_path: Path, index: int, *, elapsed: int) -> Path:
    output_dir = tmp_path / f"run-{index}"
    output_dir.mkdir()
    (output_dir / "final-ui.xml").write_text(
        "FAILED\nNo safe deterministic route is available\n",
        encoding="utf-8",
    )
    (output_dir / "battery-after.txt").write_text(
        "level: 100\nAC powered: true\n", encoding="utf-8"
    )
    (output_dir / "meminfo-after.txt").write_text("TOTAL PSS: 156192\n", encoding="utf-8")
    (output_dir / "modeldebug-logcat.txt").write_text(
        "GOFFY log line\nobservation_engine_scope_closed\n",
        encoding="utf-8",
    )
    report = tmp_path / f"modeldebug-observation-report-{index}.json"
    report.write_text(
        json.dumps(
            {
                "schema_version": OBSERVATION_SCHEMA_VERSION,
                "executed": True,
                "ok": True,
                "output_directory": str(output_dir),
                "command": DEFAULT_COMMAND,
                "model_source": str(tmp_path / "qwen3_0_6b_mixed_int4.litertlm"),
                "model_sha256": MODEL_SHA,
                "observation_elapsed_millis": elapsed,
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


def write_idle_evidence(
    tmp_path: Path,
    *,
    process_running_after_idle: bool = False,
    total_pss_kb: int | None = None,
) -> Path:
    path = tmp_path / "idle-cleanup.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": IDLE_EVIDENCE_SCHEMA_VERSION,
                "ok": True,
                "waited_seconds": 60,
                "model_sha256": MODEL_SHA,
                "provider_closed_after_idle": True,
                "process_running_after_idle": process_running_after_idle,
                "total_pss_kb": total_pss_kb,
                "blockers": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    return path
