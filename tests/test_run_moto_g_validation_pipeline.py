from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import scripts.collect_moto_g_validation_bundle as collect
import scripts.record_moto_g_smoke as smoke
import scripts.run_moto_g_validation_pipeline as pipeline
from scripts.guide_moto_g_validation import GuideReport, build_report
from tests.test_guide_moto_g_validation import passing_manual, smoke_record


def test_pipeline_collects_and_verifies_passing_bundle(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path, manual=passing_manual()))

    result = pipeline.run_pipeline(
        output_root=tmp_path / "bundles",
        timestamp_utc="2026-07-14T12:34:56Z",
        report=report,
    )
    payload = json.loads(pipeline.render_json(result))
    rendered = pipeline.render_text(result)

    assert result.ok
    assert result.exit_code == 0
    assert result.bundle is not None
    assert result.bundle.output_directory.is_dir()
    assert payload["schemaVersion"] == pipeline.JSON_SCHEMA_VERSION
    assert payload["verification"]["integrityOk"] is True
    assert "overall: passed" in rendered


def test_pipeline_reports_integrity_valid_incomplete_bundle(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path))

    result = pipeline.run_pipeline(
        output_root=tmp_path / "bundles",
        timestamp_utc="2026-07-14T12:34:56Z",
        report=report,
    )
    payload = json.loads(pipeline.render_json(result))

    assert not result.ok
    assert result.integrity_ok
    assert result.exit_code == 1
    assert result.next_step_id == "manual-phone-smoke"
    assert payload["physicalSmokePassed"] is False
    assert payload["verification"]["integrityOk"] is True


def test_pipeline_conflict_returns_integrity_failure_without_verification(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path))
    output_root = tmp_path / "bundles"

    pipeline.run_pipeline(
        output_root=output_root,
        timestamp_utc="2026-07-14T12:34:56Z",
        report=report,
    )
    result = pipeline.run_pipeline(
        output_root=output_root,
        timestamp_utc="2026-07-14T12:34:56Z",
        report=report,
    )
    payload = json.loads(pipeline.render_json(result))

    assert result.exit_code == 2
    assert result.verification is None
    assert result.error_code == "collection_conflict"
    assert payload["verificationAttempted"] is False
    assert payload["integrityOk"] is None
    assert payload["physicalSmokePassed"] is None
    assert payload["verification"] is None
    assert "already exists" in (result.error or "")
    assert str(output_root) not in payload["error"]


def test_pipeline_force_replaces_previously_marked_bundle(tmp_path: Path) -> None:
    first = build_report(record=smoke_record(tmp_path))
    second = build_report(record=smoke_record(tmp_path, manual=passing_manual()))
    output_root = tmp_path / "bundles"

    pipeline.run_pipeline(
        output_root=output_root,
        timestamp_utc="2026-07-14T12:34:56Z",
        report=first,
    )
    result = pipeline.run_pipeline(
        output_root=output_root,
        timestamp_utc="2026-07-14T12:34:56Z",
        report=second,
        force=True,
    )

    assert result.ok
    assert result.exit_code == 0


def test_cli_forwards_manual_flags_and_keeps_success_stderr_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
) -> None:
    seen_manual: list[smoke.ManualSmokeEvidence | None] = []

    def fake_build_report(
        *,
        root: Path,
        manual: smoke.ManualSmokeEvidence | None = None,
        record: smoke.SmokeRecord | None = None,
    ) -> GuideReport:
        seen_manual.append(manual)
        return build_report(record=smoke_record(root, manual=manual or smoke.ManualSmokeEvidence()))

    monkeypatch.setattr(
        "scripts.collect_moto_g_validation_bundle.guide.build_report", fake_build_report
    )

    assert (
        pipeline.main(
            [
                "--repo-root",
                str(tmp_path),
                "--output-root",
                str(tmp_path / "bundles"),
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
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["ok"] is True
    assert payload["verificationAttempted"] is True
    assert seen_manual == [passing_manual()]
    assert captured.err == ""


def test_cli_returns_one_for_incomplete_physical_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
) -> None:
    def fake_build_report(
        *,
        root: Path,
        manual: smoke.ManualSmokeEvidence | None = None,
        record: smoke.SmokeRecord | None = None,
    ) -> GuideReport:
        return build_report(record=smoke_record(root, manual=manual or smoke.ManualSmokeEvidence()))

    monkeypatch.setattr(
        "scripts.collect_moto_g_validation_bundle.guide.build_report", fake_build_report
    )

    assert (
        pipeline.main(
            [
                "--repo-root",
                str(tmp_path),
                "--output-root",
                str(tmp_path / "bundles"),
                "--json",
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["integrityOk"] is True
    assert payload["nextStepId"] == "manual-phone-smoke"


def test_cli_returns_two_for_existing_bundle_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
) -> None:
    def fake_build_report(
        *,
        root: Path,
        manual: smoke.ManualSmokeEvidence | None = None,
        record: smoke.SmokeRecord | None = None,
    ) -> GuideReport:
        return build_report(record=smoke_record(root, manual=manual or smoke.ManualSmokeEvidence()))

    monkeypatch.setattr(
        "scripts.collect_moto_g_validation_bundle.guide.build_report", fake_build_report
    )
    monkeypatch.setattr(collect, "utc_timestamp", lambda: "2026-07-14T12:34:56Z")
    output_root = tmp_path / "bundles"

    assert (
        pipeline.main(
            [
                "--repo-root",
                str(tmp_path),
                "--output-root",
                str(output_root),
                "--json",
            ]
        )
        == 1
    )
    capsys.readouterr()

    assert (
        pipeline.main(
            [
                "--repo-root",
                str(tmp_path),
                "--output-root",
                str(output_root),
                "--json",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["verificationAttempted"] is False
    assert payload["integrityOk"] is None
    assert payload["physicalSmokePassed"] is None
    assert payload["errorCode"] == "collection_conflict"
    assert str(output_root) not in payload["error"]
    assert captured.err == ""


def test_cli_returns_two_for_unsafe_force_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: Any,
) -> None:
    monkeypatch.setattr(collect, "utc_timestamp", lambda: "2026-07-14T12:34:56Z")
    output_root = tmp_path / "bundles"
    existing = output_root / "moto-g-20260714T123456Z"
    existing.mkdir(parents=True)
    (existing / "not-a-goffy-bundle.txt").write_text("stop", encoding="utf-8")

    assert (
        pipeline.main(
            [
                "--repo-root",
                str(tmp_path),
                "--output-root",
                str(output_root),
                "--json",
                "--force",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["verificationAttempted"] is False
    assert payload["errorCode"] == "collection_conflict"
    assert str(output_root) not in payload["error"]
