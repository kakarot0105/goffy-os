from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import scripts.collect_moto_g_validation_bundle as bundle
import scripts.record_moto_g_smoke as smoke
from scripts.collect_moto_g_validation_bundle import (
    BundleExistsError,
    bundle_name,
    collect_bundle,
    render_manifest,
    render_text,
)
from scripts.guide_moto_g_validation import GuideReport, build_report
from tests.test_guide_moto_g_validation import passing_manual, smoke_record


def test_bundle_name_is_stable_for_utc_timestamp() -> None:
    assert bundle_name("2026-07-14T12:34:56Z") == "moto-g-20260714T123456Z"


def test_collect_bundle_writes_hashed_artifacts(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path, manual=passing_manual()))

    result = collect_bundle(
        output_root=tmp_path / "bundles",
        timestamp_utc="2026-07-14T12:34:56Z",
        report=report,
    )
    payload = json.loads(render_manifest(result))
    rendered = render_text(result)

    assert result.ok
    assert result.next_step_id is None
    assert payload["schemaVersion"] == bundle.JSON_SCHEMA_VERSION
    assert payload["bundleName"] == "moto-g-20260714T123456Z"
    assert payload["localOnly"] is True
    assert payload["phoneMutation"] is False
    assert "passed" in rendered
    assert {file["relativePath"] for file in payload["artifactFiles"]} == {
        "guide.json",
        "guide.txt",
        "smoke.json",
        "smoke.txt",
    }
    assert payload["metadataFiles"] == [
        {"relativePath": "manifest.json", "role": "bundle manifest"},
        {"relativePath": bundle.BUNDLE_MARKER, "role": "force-overwrite safety marker"},
    ]
    for artifact in payload["artifactFiles"]:
        artifact_path = result.output_directory / artifact["relativePath"]
        assert artifact_path.is_file()
        assert artifact["sizeBytes"] == artifact_path.stat().st_size
        assert artifact["sha256"] == bundle.sha256_file(artifact_path)
    assert (result.output_directory / bundle.BUNDLE_MARKER).read_text(
        encoding="utf-8"
    ) == f"{bundle.JSON_SCHEMA_VERSION}\n"


def test_disk_manifest_matches_returned_bundle(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path, manual=passing_manual()))

    result = collect_bundle(
        output_root=tmp_path / "bundles",
        timestamp_utc="2026-07-14T12:34:56Z",
        report=report,
    )

    assert (result.output_directory / "manifest.json").read_text(
        encoding="utf-8"
    ) == render_manifest(result)


def test_collect_bundle_refuses_existing_output_without_force(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path))
    output_root = tmp_path / "bundles"

    collect_bundle(
        output_root=output_root,
        timestamp_utc="2026-07-14T12:34:56Z",
        report=report,
    )

    with pytest.raises(BundleExistsError):
        collect_bundle(
            output_root=output_root,
            timestamp_utc="2026-07-14T12:34:56Z",
            report=report,
        )


def test_force_replaces_existing_output(tmp_path: Path) -> None:
    first = build_report(record=smoke_record(tmp_path))
    second = build_report(record=smoke_record(tmp_path, manual=passing_manual()))
    output_root = tmp_path / "bundles"

    collect_bundle(
        output_root=output_root,
        timestamp_utc="2026-07-14T12:34:56Z",
        report=first,
    )
    result = collect_bundle(
        output_root=output_root,
        timestamp_utc="2026-07-14T12:34:56Z",
        report=second,
        force=True,
    )

    assert result.ok
    assert (
        json.loads((result.output_directory / "guide.json").read_text(encoding="utf-8"))["ok"]
        is True
    )


def test_force_refuses_to_delete_unmarked_directory(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path))
    output_root = tmp_path / "bundles"
    existing = output_root / "moto-g-20260714T123456Z"
    existing.mkdir(parents=True)
    (existing / "important.txt").write_text("do not remove", encoding="utf-8")

    with pytest.raises(BundleExistsError, match="unmarked directory"):
        collect_bundle(
            output_root=output_root,
            timestamp_utc="2026-07-14T12:34:56Z",
            report=report,
            force=True,
        )

    assert (existing / "important.txt").read_text(encoding="utf-8") == "do not remove"


def test_force_refuses_to_delete_symlinked_bundle_path(tmp_path: Path) -> None:
    report = build_report(record=smoke_record(tmp_path))
    output_root = tmp_path / "bundles"
    target = tmp_path / "target"
    target.mkdir()
    output_root.mkdir()
    (output_root / "moto-g-20260714T123456Z").symlink_to(target, target_is_directory=True)

    with pytest.raises(BundleExistsError, match="symlinked"):
        collect_bundle(
            output_root=output_root,
            timestamp_utc="2026-07-14T12:34:56Z",
            report=report,
            force=True,
        )


def test_cli_forwards_manual_flags_and_returns_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
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
        bundle.main(
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
    assert seen_manual == [passing_manual()]
    assert captured.err == ""


def test_cli_returns_nonzero_for_incomplete_physical_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
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
        bundle.main(
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
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["ok"] is False
    assert payload["nextStepId"] == "manual-phone-smoke"
    assert captured.err == ""


def test_cli_returns_two_for_existing_bundle_conflict(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
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
    monkeypatch.setattr(bundle, "utc_timestamp", lambda: "2026-07-14T12:34:56Z")
    output_root = tmp_path / "bundles"
    assert (
        bundle.main(
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
        bundle.main(
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
    assert captured.out == ""
    assert "already exists" in captured.err


def test_cli_rejects_unknown_manual_status(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        bundle.main(
            [
                "--repo-root",
                str(tmp_path),
                "--output-root",
                str(tmp_path / "bundles"),
                "--app-launched",
                "maybe",
            ]
        )


def test_manual_status_parser_is_used_by_cli() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        smoke.manual_status("unknown")
