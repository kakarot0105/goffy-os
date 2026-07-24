from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.create_rom_dsu_preflight_evidence import (
    JSON_SCHEMA_VERSION,
    DsuPreflightStatus,
    create_dsu_preflight_evidence,
    load_dsu_preflight_evidence,
    main,
    render_json,
)
from scripts.create_rom_gsi_candidate_evidence import (
    JSON_SCHEMA_VERSION as GSI_SCHEMA_VERSION,
)
from scripts.create_rom_stock_restore_evidence import (
    JSON_SCHEMA_VERSION as STOCK_SCHEMA_VERSION,
)

BUILD_FINGERPRINT = (
    "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys"
)
GSI_SHA256 = "2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea"
GSI_ARTIFACT = f"aosp_arm64-exp-BP4A.251205.006-14401865-{GSI_SHA256[:8]}.zip"


def test_dsu_preflight_ready_for_manual_review_with_locked_bootloader(tmp_path: Path) -> None:
    write_probe(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)

    evidence = create_dsu_preflight_evidence(root=tmp_path)
    payload = json.loads(render_json(evidence))

    assert evidence.schema_version == JSON_SCHEMA_VERSION
    assert evidence.ok is True
    assert evidence.status is DsuPreflightStatus.READY_FOR_MANUAL_DSU_REVIEW
    assert payload["destructive_actions"] == "withheld"
    assert payload["probe"]["bootloader_state"] == "locked"
    assert payload["probe"]["dsu_package_present"] == "true"
    assert payload["probe"]["dsu_start_install_resolves"] == "true"
    assert payload["target_device"]["codename"] == "kansas"
    assert payload["evidence_inputs"] == [
        {"name": "stock_restore", "status": "LOADED", "detail": "validated and consumed"},
        {"name": "gsi_candidate", "status": "LOADED", "detail": "validated and consumed"},
    ]
    assert payload["safety"] == {
        "execution_authority": "LOCAL_FILE_VALIDATION_ONLY",
        "device_mutation": "NONE",
        "install_authority": "WITHHELD",
        "destructive_actions": "WITHHELD",
        "external_installers_imported": False,
    }
    assert "DSU preflight does not prove" in payload["warnings"][0]


def test_dsu_preflight_blocks_without_stock_and_gsi_evidence(tmp_path: Path) -> None:
    write_probe(tmp_path)

    evidence = create_dsu_preflight_evidence(root=tmp_path)

    assert evidence.ok is False
    assert evidence.status is DsuPreflightStatus.BLOCKED_EVIDENCE
    assert "exact stock restore evidence is missing" in evidence.blockers
    assert "official Google ARM64 GSI evidence is missing" in evidence.blockers
    assert [item.status.value for item in evidence.evidence_inputs] == ["MISSING", "MISSING"]


def test_dsu_preflight_blocks_when_dsu_probe_support_is_missing(tmp_path: Path) -> None:
    write_probe(tmp_path, dsu_package_present="false", start_install_resolves="false")
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)

    evidence = create_dsu_preflight_evidence(root=tmp_path)

    assert evidence.ok is False
    assert "Android Dynamic System package is not visible" in evidence.blockers
    assert "Android DSU start install activity is not resolvable" in evidence.blockers


def test_load_dsu_preflight_evidence_accepts_ready_non_authorizing_artifact(
    tmp_path: Path,
) -> None:
    write_probe(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)
    evidence = create_dsu_preflight_evidence(root=tmp_path)
    path = tmp_path / ".goffy-validation" / "rom-dsu-preflight-evidence.json"
    path.write_text(render_json(evidence), encoding="utf-8")

    loaded = load_dsu_preflight_evidence(path)

    assert loaded["status"] == "READY_FOR_MANUAL_DSU_REVIEW"
    assert loaded["install_authority"] == "WITHHELD"
    assert loaded["destructive_actions"] == "withheld"


def test_load_dsu_preflight_evidence_rejects_blocked_artifact(tmp_path: Path) -> None:
    write_probe(tmp_path)
    evidence = create_dsu_preflight_evidence(root=tmp_path)
    path = tmp_path / ".goffy-validation" / "rom-dsu-preflight-evidence.json"
    path.write_text(render_json(evidence), encoding="utf-8")

    with pytest.raises(ValueError, match="DSU preflight is not ready"):
        load_dsu_preflight_evidence(path)


def test_dsu_preflight_rejects_sensitive_probe_keys(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    payload = json.loads(probe.read_text(encoding="utf-8"))
    payload["device"]["serial"] = "ZY32-private"
    probe.write_text(json.dumps(payload), encoding="utf-8")

    try:
        create_dsu_preflight_evidence(root=tmp_path)
    except ValueError as exc:
        assert "sensitive key is not allowed in ROM probe evidence" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_dsu_preflight_rejects_evidence_paths_outside_validation_dir(tmp_path: Path) -> None:
    write_probe(tmp_path)
    outside = tmp_path / "rom-stock-restore-evidence.json"
    outside.write_text("{}", encoding="utf-8")

    try:
        create_dsu_preflight_evidence(root=tmp_path, stock_restore_evidence=outside)
    except ValueError as exc:
        assert "evidence path must be under .goffy-validation" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_dsu_preflight_cli_writes_validation_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_probe(tmp_path)
    output = tmp_path / ".goffy-validation" / "rom-dsu-preflight-evidence.json"

    exit_code = main(["--output", str(output)], root=tmp_path)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.is_file()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == JSON_SCHEMA_VERSION
    assert payload["status"] == "BLOCKED_EVIDENCE"
    assert "wrote DSU preflight evidence" in captured.out


def write_probe(
    root: Path,
    *,
    dsu_package_present: str = "true",
    start_install_resolves: str = "true",
) -> Path:
    validation = root / ".goffy-validation"
    validation.mkdir(parents=True, exist_ok=True)
    path = validation / "rom-feasibility-current.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "goffy.rom-feasibility-probe.v1",
                "ok": False,
                "generated_at": "2026-07-23T00:00:00+00:00",
                "device": {
                    "model": "moto g - 2025",
                    "codename": "kansas",
                    "product": "kansas_g_sys",
                    "hardware_sku": "XT2513V",
                    "carrier": "tracfone",
                },
                "boot": {
                    "flash_locked": "1",
                    "vbmeta_device_state": "locked",
                    "verified_boot_state": "green",
                },
                "platform": {"android_release": "16", "sdk": "36"},
                "treble": {"enabled": "true", "dynamic_partitions": "true"},
                "dsu": {
                    "package_present": dsu_package_present,
                    "start_install_resolves": start_install_resolves,
                    "start_install_activity": "com.android.dynsystem/.VerificationActivity",
                },
                "properties": {"ro.build.fingerprint": BUILD_FINGERPRINT},
                "blockers": [
                    "bootloader is currently locked; do not flash, root, or boot custom images yet"
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def write_stock_evidence(root: Path) -> Path:
    path = root / ".goffy-validation" / "rom-stock-restore-evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": STOCK_SCHEMA_VERSION,
                "generated_at": "2026-07-23T00:00:00+00:00",
                "stock_restore": {
                    "source_url": "https://en-us.support.motorola.com/app/softwarefix",
                    "archive_name": "kansas-stock.zip",
                    "sha256": "a" * 64,
                    "rollback_doc": "docs/setup/kansas-stock-rollback.md",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def write_gsi_evidence(root: Path) -> Path:
    path = root / ".goffy-validation" / "rom-gsi-candidate-evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": GSI_SCHEMA_VERSION,
                "generated_at": "2026-07-23T00:00:00+00:00",
                "ok": True,
                "status": "ARTIFACT_CHECKSUM_VERIFIED",
                "candidate": {
                    "name": "Official Google Android 16 ARM64 GSI",
                    "android_release": "16",
                    "architecture": "arm64",
                    "image_kind": "archive",
                    "license_note_code": "official_google_gsi_terms",
                },
                "artifact": {
                    "artifact_name": GSI_ARTIFACT,
                    "byte_count": 123,
                    "sha256": GSI_SHA256,
                    "expected_sha256": GSI_SHA256,
                },
                "source": {
                    "source_url": "https://developer.android.com/topic/generic-system-image/releases",
                    "download_url": (
                        "https://dl.google.com/developers/android/baklava/images/gsi/"
                        f"{GSI_ARTIFACT}"
                    ),
                },
                "safety": {
                    "execution_authority": "OFFLINE_HASH_ONLY",
                    "device_mutation": "NONE",
                    "authorization": "NON_AUTHORIZING_EVIDENCE",
                    "destructive_actions": "WITHHELD",
                    "local_path_redacted": True,
                },
            }
        ),
        encoding="utf-8",
    )
    return path
