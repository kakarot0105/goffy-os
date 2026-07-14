from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import scripts.collect_moto_g_validation_bundle as collect
import scripts.verify_moto_g_validation_bundle as verify
from scripts.collect_moto_g_validation_bundle import collect_bundle
from scripts.guide_moto_g_validation import build_report
from tests.test_guide_moto_g_validation import passing_manual, smoke_record


def write_bundle(
    tmp_path: Path,
    *,
    passing: bool,
    timestamp_utc: str = "2026-07-14T12:34:56Z",
) -> Path:
    report = build_report(
        record=smoke_record(tmp_path, manual=passing_manual() if passing else None)
    )
    return collect_bundle(
        output_root=tmp_path / "bundles",
        timestamp_utc=timestamp_utc,
        report=report,
    ).output_directory


def manifest_path(bundle_dir: Path) -> Path:
    return bundle_dir / "manifest.json"


def read_manifest(bundle_dir: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path(bundle_dir).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def write_manifest(bundle_dir: Path, payload: dict[str, Any]) -> None:
    manifest_path(bundle_dir).write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def test_verify_passing_bundle_returns_success(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)

    result = verify.verify_bundle(bundle_dir)
    payload = json.loads(verify.render_json(result))
    rendered = verify.render_text(result)

    assert result.ok
    assert result.exit_code == 0
    assert payload["schemaVersion"] == verify.JSON_SCHEMA_VERSION
    assert payload["integrityOk"] is True
    assert payload["physicalSmokePassed"] is True
    assert "overall: passed" in rendered


def test_verify_incomplete_bundle_has_integrity_but_nonzero_exit(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=False)

    result = verify.verify_bundle(bundle_dir)
    payload = json.loads(verify.render_json(result))

    assert not result.ok
    assert result.integrity_ok
    assert result.exit_code == 1
    assert result.next_step_id == "manual-phone-smoke"
    assert payload["ok"] is False
    assert payload["integrityOk"] is True


def test_verify_detects_corrupted_artifact_hash(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    (bundle_dir / "guide.txt").write_text("tampered", encoding="utf-8")

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "artifact-guide.txt-size" in failed
    assert "artifact-guide.txt-sha256" in failed


def test_verify_rejects_boolean_artifact_size(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    payload = read_manifest(bundle_dir)
    for artifact in payload["artifactFiles"]:
        assert isinstance(artifact, dict)
        if artifact["relativePath"] == "guide.txt":
            artifact["sizeBytes"] = True
    write_manifest(bundle_dir, payload)

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "artifact-guide.txt-size" in failed


def test_verify_rejects_unsafe_manifest_artifact_path(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    payload = read_manifest(bundle_dir)
    artifacts = payload["artifactFiles"]
    assert isinstance(artifacts, list)
    first = artifacts[0]
    assert isinstance(first, dict)
    first["relativePath"] = "../outside.txt"
    write_manifest(bundle_dir, payload)

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "artifact-0-path" in failed


def test_verify_rejects_unexpected_artifact_before_hashing(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    payload = read_manifest(bundle_dir)
    artifacts = payload["artifactFiles"]
    assert isinstance(artifacts, list)
    first = artifacts[0]
    assert isinstance(first, dict)
    first["relativePath"] = "unexpected.txt"
    first["sizeBytes"] = 1
    first["sha256"] = "0" * 64
    (bundle_dir / "unexpected.txt").write_text("x", encoding="utf-8")
    write_manifest(bundle_dir, payload)

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "artifact-unexpected.txt-expected" in failed


def test_verify_rejects_oversized_artifact_even_when_hash_matches(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    oversized = "x" * (verify.MAX_ARTIFACT_BYTES + 1)
    guide_text = bundle_dir / "guide.txt"
    guide_text.write_text(oversized, encoding="utf-8")
    payload = read_manifest(bundle_dir)
    for artifact in payload["artifactFiles"]:
        assert isinstance(artifact, dict)
        if artifact["relativePath"] == "guide.txt":
            artifact["sizeBytes"] = guide_text.stat().st_size
            artifact["sha256"] = collect.sha256_file(guide_text)
    write_manifest(bundle_dir, payload)

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "artifact-guide.txt-bounded-size" in failed


def test_verify_rejects_missing_marker(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    (bundle_dir / collect.BUNDLE_MARKER).unlink()

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "metadata-marker" in failed


def test_verify_rejects_extra_on_disk_bundle_file(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    (bundle_dir / "extra.txt").write_text("unexpected", encoding="utf-8")

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "bundle-contents-only-expected-files" in failed


def test_verify_rejects_guide_smoke_mismatch(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    smoke_payload = json.loads((bundle_dir / "smoke.json").read_text(encoding="utf-8"))
    assert isinstance(smoke_payload, dict)
    smoke_payload["physicalSmokePassed"] = False
    (bundle_dir / "smoke.json").write_text(
        json.dumps(smoke_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    payload = read_manifest(bundle_dir)
    for artifact in payload["artifactFiles"]:
        assert isinstance(artifact, dict)
        if artifact["relativePath"] == "smoke.json":
            artifact["sizeBytes"] = (bundle_dir / "smoke.json").stat().st_size
            artifact["sha256"] = collect.sha256_file(bundle_dir / "smoke.json")
    write_manifest(bundle_dir, payload)

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "guide-smoke-record-match" in failed
    assert "smoke-physical-status-match" in failed


def test_verify_rejects_tampered_guide_text_even_when_manifest_hash_matches(
    tmp_path: Path,
) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    guide_text = bundle_dir / "guide.txt"
    guide_text.write_text("tampered", encoding="utf-8")
    payload = read_manifest(bundle_dir)
    for artifact in payload["artifactFiles"]:
        assert isinstance(artifact, dict)
        if artifact["relativePath"] == "guide.txt":
            artifact["sizeBytes"] = guide_text.stat().st_size
            artifact["sha256"] = collect.sha256_file(guide_text)
    write_manifest(bundle_dir, payload)

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "guide-text-match" in failed


def test_verify_rejects_tampered_smoke_text_even_when_manifest_hash_matches(
    tmp_path: Path,
) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    smoke_text = bundle_dir / "smoke.txt"
    smoke_text.write_text("tampered", encoding="utf-8")
    payload = read_manifest(bundle_dir)
    for artifact in payload["artifactFiles"]:
        assert isinstance(artifact, dict)
        if artifact["relativePath"] == "smoke.txt":
            artifact["sizeBytes"] = smoke_text.stat().st_size
            artifact["sha256"] = collect.sha256_file(smoke_text)
    write_manifest(bundle_dir, payload)

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "smoke-text-match" in failed


def test_verify_rejects_non_boolean_manifest_ok(tmp_path: Path) -> None:
    bundle_dir = write_bundle(tmp_path, passing=True)
    payload = read_manifest(bundle_dir)
    payload["ok"] = 1
    write_manifest(bundle_dir, payload)

    result = verify.verify_bundle(bundle_dir)
    failed = {check.check_id for check in result.checks if not check.ok}

    assert result.exit_code == 2
    assert "manifest-ok-shape" in failed
    assert "manifest-guide-status-match" in failed
    assert "smoke-physical-status-match" in failed


def test_cli_returns_expected_exit_codes(
    tmp_path: Path,
    capsys: Any,
) -> None:
    passing_bundle = write_bundle(tmp_path, passing=True, timestamp_utc="2026-07-14T12:00:00Z")
    incomplete_bundle = write_bundle(
        tmp_path,
        passing=False,
        timestamp_utc="2026-07-14T12:00:01Z",
    )
    corrupt_bundle = write_bundle(tmp_path, passing=True, timestamp_utc="2026-07-14T12:00:02Z")
    (corrupt_bundle / "manifest.json").write_text("{", encoding="utf-8")

    assert verify.main([str(passing_bundle), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert verify.main([str(incomplete_bundle), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["integrityOk"] is True

    assert verify.main([str(corrupt_bundle), "--json"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["integrityOk"] is False


def test_cli_bad_path_reports_bundle_directory(
    tmp_path: Path,
    capsys: Any,
) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(SystemExit):
        verify.main([str(missing)])

    assert "bundle directory must be an existing directory" in capsys.readouterr().err
