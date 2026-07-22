from __future__ import annotations

import json
from pathlib import Path

import scripts.create_tflite_task_text_export_image_audit_evidence as audit
from scripts.run_tflite_task_text_model_maker_docker import IMAGE_AUDIT_SCHEMA_VERSION
from scripts.verify_tflite_task_text_training_environment import sha256_file

AUDITED_IMAGE = (
    "ghcr.io/goffy/task-text-export@sha256:"
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)


def test_trivy_report_writes_runner_compatible_audit_evidence(tmp_path: Path) -> None:
    scanner_report = write_json(
        tmp_path / "trivy.json",
        {
            "SchemaVersion": 2,
            "Metadata": {
                "RepoDigests": [AUDITED_IMAGE],
            },
            "Results": [
                {
                    "Target": "python",
                    "Vulnerabilities": [
                        {"VulnerabilityID": "CVE-low", "Severity": "LOW"},
                        {"VulnerabilityID": "CVE-negligible", "Severity": "NEGLIGIBLE"},
                    ],
                }
            ],
        },
    )
    output = tmp_path / "audit-evidence.json"

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
        output=output,
        write=True,
    )

    assert report.ok
    assert report.status == "READY"
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == IMAGE_AUDIT_SCHEMA_VERSION
    assert payload["image"] == AUDITED_IMAGE
    assert payload["ok"] is True
    assert payload["scanner"] == "trivy"
    assert payload["scanned_image_identities"] == [AUDITED_IMAGE]
    assert payload["scanner_report_sha256"] == sha256_file(scanner_report)
    assert payload["vulnerability_counts"] == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 1,
        "negligible": 1,
        "unknown": 0,
    }


def test_grype_report_blocks_high_findings_without_writing(tmp_path: Path) -> None:
    scanner_report = write_json(
        tmp_path / "grype.json",
        {
            "source": {
                "type": "image",
                "target": {
                    "userInput": AUDITED_IMAGE,
                    "manifestDigest": "sha256:"
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                },
            },
            "matches": [
                {"vulnerability": {"id": "CVE-high", "severity": "High"}},
                {"vulnerability": {"id": "CVE-medium", "severity": "Medium"}},
            ],
        },
    )
    output = tmp_path / "audit-evidence.json"

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
        scanner="grype",
        output=output,
        write=True,
    )

    assert not report.ok
    assert report.status == "BLOCKED"
    assert "image audit has 1 high findings" in report.blockers
    assert "image audit has 1 medium findings" in report.blockers
    assert "audit evidence was not written because the scan is blocked" in report.blockers
    assert not output.exists()


def test_report_rejects_mutable_image_tag(tmp_path: Path) -> None:
    scanner_report = write_json(
        tmp_path / "trivy.json",
        {"Metadata": {"RepoDigests": [AUDITED_IMAGE]}, "Results": []},
    )

    report = audit.build_report(
        image="python:3.9-slim",
        scanner_report=scanner_report,
    )

    assert not report.ok
    assert "image must be immutable and pinned by sha256 digest" in report.blockers


def test_report_rejects_unrecognized_scanner_json(tmp_path: Path) -> None:
    scanner_report = write_json(tmp_path / "unknown.json", {"vulnerabilities": []})

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
    )

    assert not report.ok
    assert "Trivy report must contain Results list" in report.blockers


def test_missing_severity_is_counted_unknown_and_warns(tmp_path: Path) -> None:
    scanner_report = write_json(
        tmp_path / "trivy.json",
        {
            "Metadata": {"RepoDigests": [AUDITED_IMAGE]},
            "Results": [{"Vulnerabilities": [{"VulnerabilityID": "CVE-no-severity"}]}],
        },
    )

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
    )

    assert not report.ok
    assert report.evidence is None
    assert any("severity is missing" in blocker for blocker in report.blockers)


def test_report_rejects_non_list_trivy_vulnerabilities(tmp_path: Path) -> None:
    scanner_report = write_json(
        tmp_path / "trivy.json",
        {
            "Metadata": {"RepoDigests": [AUDITED_IMAGE]},
            "Results": [{"Vulnerabilities": {}}],
        },
    )

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
    )

    assert not report.ok
    assert "Results[0].Vulnerabilities must be a list" in report.blockers


def test_report_rejects_non_object_grype_match(tmp_path: Path) -> None:
    scanner_report = write_json(
        tmp_path / "grype.json",
        {
            "source": {
                "type": "image",
                "target": {"manifestDigest": "sha256:" + "a" * 64},
            },
            "matches": ["not-an-object"],
        },
    )

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
        scanner="grype",
    )

    assert not report.ok
    assert "matches[0] must be an object" in report.blockers


def test_report_rejects_scanner_image_digest_mismatch(tmp_path: Path) -> None:
    scanner_report = write_json(
        tmp_path / "trivy.json",
        {
            "Metadata": {
                "RepoDigests": [
                    "ghcr.io/goffy/task-text-export@sha256:"
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                ]
            },
            "Results": [],
        },
    )

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
    )

    assert not report.ok
    assert "scanner report image identity does not match requested image digest" in report.blockers


def test_report_rejects_digest_substring_in_noncanonical_identity(tmp_path: Path) -> None:
    requested_digest = "sha256:" + "a" * 64
    scanner_report = write_json(
        tmp_path / "trivy.json",
        {
            "Metadata": {
                "RepoTags": [f"not-a-digest-{requested_digest}"],
                "RepoDigests": ["ghcr.io/goffy/task-text-export@sha256:" + "b" * 64],
            },
            "Results": [],
        },
    )

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
    )

    assert not report.ok
    assert "scanner report image identity does not match requested image digest" in report.blockers


def test_report_rejects_missing_scanner_image_identity(tmp_path: Path) -> None:
    scanner_report = write_json(tmp_path / "trivy.json", {"Results": []})

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
    )

    assert not report.ok
    assert "trivy report must include scanned image identity metadata" in report.blockers


def test_write_requires_output_path(tmp_path: Path) -> None:
    scanner_report = write_json(
        tmp_path / "trivy.json",
        {"Metadata": {"RepoDigests": [AUDITED_IMAGE]}, "Results": []},
    )

    report = audit.build_report(
        image=AUDITED_IMAGE,
        scanner_report=scanner_report,
        write=True,
    )

    assert not report.ok
    assert "output path is required when --write is used" in report.blockers


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path
