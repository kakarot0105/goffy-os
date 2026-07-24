from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from scripts.create_rom_stock_restore_evidence import (
    create_stock_restore_evidence,
)
from scripts.create_rom_stock_restore_evidence import (
    render_json as render_stock_restore_json,
)
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION
from scripts.verify_rom_stock_rollback_bundle import (
    JSON_SCHEMA_VERSION,
    StockRollbackBundleStatus,
    main,
    render_json,
    render_text,
    verify_stock_rollback_bundle,
)

BUILD_FINGERPRINT = (
    "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys"
)
TARGET_DEVICE = {
    "model": "moto g - 2025",
    "codename": "kansas",
    "product": "kansas_g_sys",
    "hardware_sku": "XT2513V",
    "build_fingerprint": BUILD_FINGERPRINT,
    "carrier": "tracfone",
}
ARCHIVE_NAME = "XT2513V_KANSAS_stock.zip"
ARCHIVE_CONTENT = b"goffy verified stock rollback archive"
ARCHIVE_SHA256 = hashlib.sha256(ARCHIVE_CONTENT).hexdigest()
SOURCE_URL = "https://en-us.support.motorola.com/app/softwarefix"
ROLLBACK_DOC = "docs/setup/kansas-stock-rollback.md"


def write_probe(root: Path, *, target_device: dict[str, str] | None = None) -> Path:
    target = target_device or TARGET_DEVICE
    path = root / ".goffy-validation" / "rom-feasibility-current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": PROBE_SCHEMA_VERSION,
                "device": {
                    "model": target["model"],
                    "codename": target["codename"],
                    "product": target["product"],
                    "hardware_sku": target["hardware_sku"],
                    "carrier": target["carrier"],
                },
                "properties": {"ro.build.fingerprint": target["build_fingerprint"]},
            }
        ),
        encoding="utf-8",
    )
    return path


def write_rollback_doc(
    root: Path,
    *,
    sha256: str = ARCHIVE_SHA256,
    source_url: str = SOURCE_URL,
    target_device: dict[str, str] | None = None,
) -> Path:
    target = target_device or TARGET_DEVICE
    path = root / ROLLBACK_DOC
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            (
                "# Kansas Stock Rollback",
                "",
                "## Device Baseline",
                target["model"],
                target["codename"],
                target["product"],
                target["hardware_sku"],
                target["build_fingerprint"],
                target["carrier"],
                "",
                "## Stock Restore Source",
                source_url,
                ARCHIVE_NAME,
                "",
                "## SHA-256 Evidence",
                sha256,
                "",
                "## Rollback Procedure",
                "Use Motorola Software Fix manually after approval.",
                "",
                "## Data Wipe Expectations",
                "Stock restore and unlock may wipe local data.",
                "",
                "## Approval Record",
                "Destructive approval: not granted.",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def write_stock_restore_evidence(root: Path, archive: Path) -> Path:
    evidence = create_stock_restore_evidence(
        archive_path=archive,
        source_url=SOURCE_URL,
        rollback_doc=ROLLBACK_DOC,
        root=root,
    )
    path = root / ".goffy-validation" / "rom-stock-restore-evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_stock_restore_json(evidence), encoding="utf-8")
    return path


def write_bundle_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "repo"
    root.mkdir()
    archive = tmp_path / "downloads" / ARCHIVE_NAME
    archive.parent.mkdir()
    archive.write_bytes(ARCHIVE_CONTENT)
    probe = write_probe(root)
    write_rollback_doc(root)
    evidence = write_stock_restore_evidence(root, archive)
    return root, archive, probe, evidence


def test_stock_rollback_bundle_accepts_matching_evidence_doc_probe_and_archive(
    tmp_path: Path,
) -> None:
    root, archive, probe, evidence = write_bundle_inputs(tmp_path)

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=archive,
        root=root,
    )
    payload = json.loads(render_json(report))

    assert report.schema_version == JSON_SCHEMA_VERSION
    assert report.ok is True
    assert report.status is StockRollbackBundleStatus.READY_FOR_MANUAL_REVIEW
    assert report.stock_restore["archive_name"] == ARCHIVE_NAME
    assert report.stock_restore["sha256"] == ARCHIVE_SHA256
    assert report.archive_check.requested is True
    assert report.archive_check.filename_matches_evidence is True
    assert report.archive_check.sha256_matches_evidence is True
    assert report.safety.restore_invoked is False
    assert report.safety.device_mutation == "NONE"
    assert str(archive.parent) not in render_json(report)
    assert payload["safety"]["destructive_actions"] == "WITHHELD"


def test_stock_rollback_bundle_accepts_evidence_doc_and_probe_without_rehash_warning(
    tmp_path: Path,
) -> None:
    root, _archive, probe, evidence = write_bundle_inputs(tmp_path)

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        root=root,
    )

    assert report.ok is True
    assert report.archive_check.requested is False
    assert report.warnings == (
        "local archive rehash was not requested; relying on stock evidence SHA-256",
    )


def test_stock_rollback_bundle_blocks_mismatched_rollback_doc_sha(tmp_path: Path) -> None:
    root, archive, probe, evidence = write_bundle_inputs(tmp_path)
    write_rollback_doc(root, sha256="b" * 64)

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=archive,
        root=root,
    )

    assert report.ok is False
    assert "stock_restore.rollback_doc must include the exact SHA-256" in report.blockers


def test_stock_rollback_bundle_blocks_mismatched_rollback_doc_source(tmp_path: Path) -> None:
    root, archive, probe, evidence = write_bundle_inputs(tmp_path)
    write_rollback_doc(root, source_url="https://example.invalid/not-motorola")

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=archive,
        root=root,
    )

    assert report.ok is False
    assert "rollback doc must include the Motorola Software Fix URL" in report.blockers


def test_stock_rollback_bundle_blocks_mismatched_local_archive(tmp_path: Path) -> None:
    root, _archive, probe, evidence = write_bundle_inputs(tmp_path)
    mismatched = tmp_path / "downloads" / ARCHIVE_NAME
    mismatched.write_bytes(b"wrong firmware")

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=mismatched,
        root=root,
    )

    assert report.ok is False
    assert "archive SHA-256 must match stock restore evidence sha256" in report.blockers


def test_stock_rollback_bundle_blocks_archive_inside_repo(tmp_path: Path) -> None:
    root, _archive, probe, _evidence = write_bundle_inputs(tmp_path)
    repo_archive = root / "downloads" / ARCHIVE_NAME
    repo_archive.parent.mkdir()
    repo_archive.write_bytes(ARCHIVE_CONTENT)
    evidence = write_stock_restore_evidence(root, repo_archive)

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=repo_archive,
        root=root,
    )

    assert report.ok is False
    assert "archive path must be outside the repo to avoid committing firmware" in report.blockers


def test_stock_rollback_bundle_blocks_probe_target_mismatch(tmp_path: Path) -> None:
    root, archive, _probe, evidence = write_bundle_inputs(tmp_path)
    probe = write_probe(root)
    payload = json.loads(probe.read_text(encoding="utf-8"))
    payload["device"]["product"] = "wrong_product"
    probe.write_text(json.dumps(payload), encoding="utf-8")

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=archive,
        root=root,
    )

    assert report.ok is False
    assert "stock_restore.rollback_doc must include target_device.product" in report.blockers


def test_stock_rollback_bundle_blocks_self_consistent_wrong_target(tmp_path: Path) -> None:
    root, archive, _probe, evidence = write_bundle_inputs(tmp_path)
    wrong_target = {
        "model": "wrong phone",
        "codename": "wrong",
        "product": "wrong_product",
        "hardware_sku": "WRONGSKU",
        "build_fingerprint": "motorola/wrong_product/wrong:16/build:user/release-keys",
        "carrier": "wrong",
    }
    probe = write_probe(root, target_device=wrong_target)
    write_rollback_doc(root, target_device=wrong_target)

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=archive,
        root=root,
    )

    assert report.ok is False
    assert "probe_json target_device.codename must match kansas" in report.blockers
    assert "probe_json target_device.product must match kansas_g_sys" in report.blockers
    assert "probe_json target_device.build_fingerprint must contain kansas_g_sys" in report.blockers


def test_stock_rollback_bundle_redacts_archive_hash_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, archive, probe, evidence = write_bundle_inputs(tmp_path)

    def fail_sha256(path: Path) -> str:
        raise OSError(13, f"cannot read {path}")

    monkeypatch.setattr("scripts.verify_rom_stock_rollback_bundle.sha256_file", fail_sha256)

    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=archive,
        root=root,
    )
    text = render_json(report)

    assert report.ok is False
    assert "archive: local file operation failed: errno 13" in report.blockers
    assert str(archive.parent) not in text


def test_stock_rollback_bundle_cli_outputs_redacted_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, archive, probe, evidence = write_bundle_inputs(tmp_path)

    exit_code = main(
        [
            "--stock-restore-evidence",
            str(evidence),
            "--probe-json",
            str(probe),
            "--archive",
            str(archive),
            "--json",
        ],
        root=root,
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["archive_check"]["archive_name"] == ARCHIVE_NAME
    assert str(archive.parent) not in output


def test_stock_rollback_bundle_text_mentions_no_restore_invocation(tmp_path: Path) -> None:
    root, archive, probe, evidence = write_bundle_inputs(tmp_path)
    report = verify_stock_rollback_bundle(
        stock_restore_evidence=evidence,
        probe_json=probe,
        archive_path=archive,
        root=root,
    )
    text = render_text(report)

    assert "restore invoked: false" in text
    assert "device mutation: NONE" in text
