from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from scripts.create_rom_gsi_candidate_evidence import (
    JSON_SCHEMA_VERSION as GSI_CANDIDATE_SCHEMA_VERSION,
)
from scripts.create_rom_release_signing_plan import JSON_SCHEMA_VERSION as SIGNING_SCHEMA_VERSION
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION
from scripts.validate_rom_manual_gates import JSON_SCHEMA_VERSION as MANUAL_SCHEMA_VERSION
from scripts.validate_rom_manual_gates import ROLLBACK_REQUIRED_HEADINGS
from scripts.verify_rom0_readiness import (
    ReadinessSection,
    Rom0ReadinessReport,
    Rom0ReadinessStatus,
    build_readiness_report,
    main,
    render_markdown,
    validate_gsi_candidate_evidence,
    validate_release_apk_verification_evidence,
    validate_release_signing_plan_evidence,
)
from scripts.verify_rom_release_apk import JSON_SCHEMA_VERSION as APK_VERIFICATION_SCHEMA_VERSION

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
GSI_ARTIFACT_NAME = "aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip"
GSI_SHA256 = "2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea"
GSI_DOWNLOAD_URL = (
    f"https://dl.google.com/developers/android/baklava/images/gsi/{GSI_ARTIFACT_NAME}"
)


def test_rom0_readiness_blocks_without_external_evidence() -> None:
    report = build_readiness_report(
        probe_json=None,
        manual_gates_json=None,
        signed_apk=None,
    )

    assert not report.ok
    assert report.status is Rom0ReadinessStatus.BLOCKED
    assert section(report, "rom_descriptors").ok
    assert "ROM feasibility probe JSON was not supplied" in section(report, "rom_probe").blockers
    assert (
        "ROM-0 manual gate evidence JSON was not supplied"
        in section(report, "manual_gates").blockers
    )
    assert (
        "ROM GSI candidate evidence JSON was not supplied"
        in section(report, "gsi_candidate").blockers
    )
    assert (
        "ROM release signing plan JSON was not supplied"
        in section(report, "release_signing_plan").blockers
    )
    assert (
        "ROM release APK verification JSON was not supplied"
        in section(report, "release_apk_verification").blockers
    )
    assert "Externally signed GOFFY APK was not supplied" in section(report, "aosp_import").blockers


def test_rom0_readiness_accepts_complete_non_destructive_evidence(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)
    apk = write_signed_apk(tmp_path)
    signing_plan = write_signing_plan(tmp_path, apk)
    apk_verification = write_apk_verification(tmp_path, apk)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        gsi_candidate_evidence_json=gsi_candidate,
        signed_apk=apk,
        signing_plan_json=signing_plan,
        apk_verification_json=apk_verification,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert report.ok
    assert report.status is Rom0ReadinessStatus.READY_FOR_HUMAN_REVIEW
    assert report.destructive_actions == "withheld"
    assert evidence(report, "gsi_candidate")["authorization"] == "NON_AUTHORIZING_EVIDENCE"
    assert evidence(report, "release_signing_plan")["keystore"] == "external"
    assert evidence(report, "release_apk_verification")["apk_signature_schemes"] == "v2"
    assert evidence(report, "aosp_import")["apk_signature_schemes"] == "v2"
    assert "does not authorize unlock" in render_markdown(report)


def test_rom0_readiness_surfaces_locked_probe_blocker(tmp_path: Path) -> None:
    probe = write_probe(tmp_path, unlocked=False)
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert not report.ok
    assert "ROM probe does not show an unlocked bootloader" in section(report, "rom_probe").blockers


def test_rom0_readiness_preserves_probe_warnings(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    payload = json.loads(probe.read_text(encoding="utf-8"))
    payload["warnings"] = [
        "OEM unlock support properties are unavailable",
        "VNDK isolation could not be confirmed from system config",
        "ROM probe did not confirm DSU package availability",
    ]
    payload["dsu"] = {"package_present": "false"}
    probe.write_text(json.dumps(payload), encoding="utf-8")
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    warnings = section(report, "rom_probe").warnings

    assert "OEM unlock support properties are unavailable" in warnings
    assert "VNDK isolation could not be confirmed from system config" in warnings
    assert warnings.count("ROM probe did not confirm DSU package availability") == 1


def test_rom0_readiness_surfaces_manual_gate_blockers(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    manual = tmp_path / "manual.json"
    manual.write_text(json.dumps({"schema_version": MANUAL_SCHEMA_VERSION}), encoding="utf-8")
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert not report.ok
    assert "backup_confirmed must be true" in section(report, "manual_gates").blockers


def test_rom0_readiness_blocks_incomplete_probe_target_identity(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    payload = json.loads(probe.read_text(encoding="utf-8"))
    del payload["device"]["hardware_sku"]
    probe.write_text(json.dumps(payload), encoding="utf-8")
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert not report.ok
    assert (
        "ROM probe target_device.hardware_sku is missing"
        in section(
            report,
            "rom_probe",
        ).blockers
    )


def test_rom0_readiness_accepts_legacy_dsu_package_installed_probe_field(
    tmp_path: Path,
) -> None:
    probe = write_probe(tmp_path)
    payload = json.loads(probe.read_text(encoding="utf-8"))
    payload["dsu"] = {"package_installed": "true"}
    probe.write_text(json.dumps(payload), encoding="utf-8")
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert (
        "ROM probe did not confirm DSU package availability"
        not in section(
            report,
            "rom_probe",
        ).warnings
    )


def test_rom0_readiness_warns_when_current_dsu_probe_field_is_false(
    tmp_path: Path,
) -> None:
    probe = write_probe(tmp_path)
    payload = json.loads(probe.read_text(encoding="utf-8"))
    payload["dsu"] = {"package_present": "false"}
    probe.write_text(json.dumps(payload), encoding="utf-8")
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert (
        "ROM probe did not confirm DSU package availability"
        in section(
            report,
            "rom_probe",
        ).warnings
    )


def test_rom0_readiness_blocks_manual_gate_target_mismatch(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(
        tmp_path,
        rollback_doc,
        target_device={**TARGET_DEVICE, "hardware_sku": "XT2513-OTHER"},
    )
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert not report.ok
    assert (
        "target_device.hardware_sku must match ROM probe"
        in section(
            report,
            "manual_gates",
        ).blockers
    )


def test_rom0_readiness_blocks_unsupported_stock_restore_keys(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    payload = json.loads(manual.read_text(encoding="utf-8"))
    payload["stock_restore"]["local_archive_path"] = "/Users/example/Downloads/kansas-stock.zip"
    manual.write_text(json.dumps(payload), encoding="utf-8")
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert not report.ok
    assert (
        "stock_restore contains unsupported keys: ['local_archive_path']"
        in section(
            report,
            "manual_gates",
        ).blockers
    )


def test_rom0_readiness_blocks_unofficial_stock_restore_source(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    payload = json.loads(manual.read_text(encoding="utf-8"))
    payload["stock_restore"]["source_url"] = "https://example.invalid/firmware.zip"
    manual.write_text(json.dumps(payload), encoding="utf-8")
    apk = write_signed_apk(tmp_path)

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert not report.ok
    assert (
        "stock_restore.source_url must be the Motorola Software Fix URL"
        in section(
            report,
            "manual_gates",
        ).blockers
    )


def test_rom0_readiness_accepts_valid_gsi_candidate_evidence(tmp_path: Path) -> None:
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)

    result = validate_gsi_candidate_evidence(gsi_candidate)

    assert result.ok
    assert result.evidence
    assert result.evidence["artifact_name"] == GSI_ARTIFACT_NAME
    assert result.evidence["sha256"] == GSI_SHA256


def test_rom0_readiness_rejects_forged_gsi_authorization(tmp_path: Path) -> None:
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)
    payload = json.loads(gsi_candidate.read_text(encoding="utf-8"))
    payload["safety"]["authorization"] = "APPROVED_FLASH"
    gsi_candidate.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_gsi_candidate_evidence(gsi_candidate)

    assert not result.ok
    assert "GSI safety authorization must be NON_AUTHORIZING_EVIDENCE" in result.blockers


def test_rom0_readiness_rejects_extra_gsi_local_path(tmp_path: Path) -> None:
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)
    payload = json.loads(gsi_candidate.read_text(encoding="utf-8"))
    payload["artifact"]["local_path"] = "/Users/example/Downloads/gsi.zip"
    gsi_candidate.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_gsi_candidate_evidence(gsi_candidate)

    assert not result.ok
    assert "GSI artifact contains unsupported keys: ['local_path']" in result.blockers


def test_rom0_readiness_rejects_gsi_metadata_mismatch(tmp_path: Path) -> None:
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)
    payload = json.loads(gsi_candidate.read_text(encoding="utf-8"))
    payload["candidate"]["architecture"] = "arm64+gms"
    gsi_candidate.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_gsi_candidate_evidence(gsi_candidate)

    assert not result.ok
    assert "GSI artifact architecture must match GSI candidate architecture" in result.blockers


def test_rom0_readiness_rejects_unofficial_gsi_download_url(tmp_path: Path) -> None:
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)
    payload = json.loads(gsi_candidate.read_text(encoding="utf-8"))
    payload["source"]["download_url"] = (
        f"https://dl.google.com/developers/android/other/images/gsi/{GSI_ARTIFACT_NAME}"
    )
    gsi_candidate.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_gsi_candidate_evidence(gsi_candidate)

    assert not result.ok
    assert "download URL must be under the official Android GSI downloads path" in result.blockers


def test_rom0_readiness_rejects_forged_gsi_action_name(tmp_path: Path) -> None:
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)
    payload = json.loads(gsi_candidate.read_text(encoding="utf-8"))
    payload["candidate"]["name"] = "Approved Flash GSI"
    gsi_candidate.write_text(json.dumps(payload), encoding="utf-8")

    result = validate_gsi_candidate_evidence(gsi_candidate)

    assert not result.ok
    assert (
        "GSI candidate name must not contain approval or device-action wording" in result.blockers
    )


def test_rom0_readiness_cli_wires_gsi_candidate_evidence_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe = write_probe(tmp_path)
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)
    apk = write_signed_apk(tmp_path)
    signing_plan = write_signing_plan(tmp_path, apk)
    apk_verification = write_apk_verification(tmp_path, apk)
    base_args = [
        "--probe-json",
        str(probe),
        "--manual-gates-json",
        str(manual),
        "--signing-plan-json",
        str(signing_plan),
        "--apk-verification-json",
        str(apk_verification),
        "--signed-apk",
        str(apk),
        "--aosp-root",
        str(tmp_path / "aosp"),
        "--evidence-root",
        str(tmp_path),
        "--json",
    ]

    blocked_exit = main(base_args)
    blocked_payload = json.loads(capsys.readouterr().out)
    ready_exit = main(
        [
            *base_args,
            "--gsi-candidate-evidence-json",
            str(gsi_candidate),
        ]
    )
    ready_payload = json.loads(capsys.readouterr().out)

    blocked_gsi = section_payload(blocked_payload, "gsi_candidate")
    ready_gsi = section_payload(ready_payload, "gsi_candidate")
    blocked_gsi_blockers = blocked_gsi["blockers"]

    assert blocked_exit == 1
    assert blocked_gsi["ok"] is False
    assert isinstance(blocked_gsi_blockers, list)
    assert "ROM GSI candidate evidence JSON was not supplied" in blocked_gsi_blockers
    assert ready_exit == 0
    assert ready_gsi["ok"] is True


def test_rom0_readiness_surfaces_signing_plan_blockers(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
    rollback_doc = write_rollback_doc(tmp_path)
    manual = write_manual_gates(tmp_path, rollback_doc)
    apk = write_signed_apk(tmp_path)
    signing_plan = tmp_path / "release-signing-plan.json"
    signing_plan.write_text(
        json.dumps(
            {
                "schema_version": SIGNING_SCHEMA_VERSION,
                "ok": False,
                "status": "BLOCKED_SIGNING_PREREQUISITES",
                "signed_apk": str(apk),
                "unsigned_apk": {"sha256": ""},
                "apksigner": "",
                "keystore": "",
                "key_alias": "goffy-release",
                "blockers": ["release keystore file is missing"],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    report = build_readiness_report(
        probe_json=probe,
        manual_gates_json=manual,
        signed_apk=apk,
        signing_plan_json=signing_plan,
        aosp_root=tmp_path / "aosp",
        evidence_root=tmp_path,
    )

    assert not report.ok
    assert (
        "release keystore file is missing"
        in section(
            report,
            "release_signing_plan",
        ).blockers
    )


def test_rom0_readiness_rejects_forged_repo_keystore_in_ready_plan(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_keystore = repo_root / "release.jks"
    repo_keystore.parent.mkdir()
    repo_keystore.write_bytes(b"not a real keystore")
    apk = write_signed_apk(tmp_path)
    signing_plan = write_signing_plan(tmp_path, apk, keystore=repo_keystore)

    result = validate_release_signing_plan_evidence(
        signing_plan,
        signed_apk=apk,
        root=repo_root,
    )

    assert not result.ok
    assert "release keystore must not live inside the GOFFY repo" in result.blockers
    assert result.evidence
    assert result.evidence["keystore"] == "invalid"


def test_rom0_readiness_rejects_apk_verification_path_mismatch(tmp_path: Path) -> None:
    apk = write_signed_apk(tmp_path)
    other_apk = tmp_path / "OtherGoffyOS-signed.apk"
    other_apk.write_bytes(apk.read_bytes())
    apk_verification = write_apk_verification(tmp_path, other_apk)

    result = validate_release_apk_verification_evidence(
        apk_verification,
        signed_apk=apk,
    )

    assert not result.ok
    assert "ROM release APK verification APK path does not match supplied APK" in result.blockers


def section(report: Rom0ReadinessReport, name: str) -> ReadinessSection:
    return next(item for item in report.sections if item.name == name)


def evidence(report: Rom0ReadinessReport, name: str) -> dict[str, str]:
    values = section(report, name).evidence
    assert values is not None
    return values


def section_payload(payload: dict[str, object], name: str) -> dict[str, object]:
    sections = payload["sections"]
    assert isinstance(sections, list)
    for item in sections:
        assert isinstance(item, dict)
        if item.get("name") == name:
            return item
    raise AssertionError(f"missing section {name}")


def write_probe(tmp_path: Path, *, unlocked: bool = True) -> Path:
    path = tmp_path / "probe.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": PROBE_SCHEMA_VERSION,
                "ok": True,
                "device": {
                    "model": TARGET_DEVICE["model"],
                    "codename": TARGET_DEVICE["codename"],
                    "product": TARGET_DEVICE["product"],
                    "hardware_sku": TARGET_DEVICE["hardware_sku"],
                    "carrier": TARGET_DEVICE["carrier"],
                },
                "boot": {
                    "flash_locked": "0" if unlocked else "1",
                    "vbmeta_device_state": "unlocked" if unlocked else "locked",
                },
                "treble": {"enabled": "true", "dynamic_partitions": "true"},
                "dsu": {"package_present": "true"},
                "properties": {"ro.build.fingerprint": BUILD_FINGERPRINT},
                "rom_path": "GSI_OR_DSU_FIRST",
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def write_manual_gates(
    tmp_path: Path,
    rollback_doc: Path,
    *,
    target_device: dict[str, str] | None = None,
) -> Path:
    path = tmp_path / "manual.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": MANUAL_SCHEMA_VERSION,
                "backup_confirmed": True,
                "oem_unlocking_enabled": True,
                "motorola_unlock_eligibility": "eligible",
                "destructive_approval": "not_requested",
                "target_device": target_device or TARGET_DEVICE,
                "stock_restore": {
                    "source_url": "https://en-us.support.motorola.com/app/softwarefix",
                    "archive_name": "kansas-stock.zip",
                    "sha256": "a" * 64,
                    "rollback_doc": rollback_doc.relative_to(tmp_path).as_posix(),
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def write_rollback_doc(tmp_path: Path) -> Path:
    path = tmp_path / "docs" / "setup" / "kansas-rollback.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "# Kansas Rollback",
                *ROLLBACK_REQUIRED_HEADINGS,
                "kansas-stock.zip",
                "a" * 64,
                TARGET_DEVICE["model"],
                TARGET_DEVICE["codename"],
                TARGET_DEVICE["product"],
                TARGET_DEVICE["hardware_sku"],
                TARGET_DEVICE["build_fingerprint"],
                TARGET_DEVICE["carrier"],
            ]
        ),
        encoding="utf-8",
    )
    return path


def write_gsi_candidate_evidence(tmp_path: Path) -> Path:
    path = tmp_path / "rom-gsi-candidate-evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": GSI_CANDIDATE_SCHEMA_VERSION,
                "generated_at": "2026-07-22T00:00:00+00:00",
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
                    "artifact_name": GSI_ARTIFACT_NAME,
                    "byte_count": 123456789,
                    "sha256": GSI_SHA256,
                    "expected_sha256": GSI_SHA256,
                },
                "source": {
                    "source_url": "https://developer.android.com/topic/generic-system-image/releases",
                    "download_url": GSI_DOWNLOAD_URL,
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


def write_signed_apk(tmp_path: Path) -> Path:
    apk = tmp_path / "GoffyOS-signed.apk"
    payload = b"signed apk placeholder"
    pair = struct.pack("<Q", 4) + struct.pack("<I", 0x7109871A)
    block_size = len(pair) + 24
    signing_block = (
        struct.pack("<Q", block_size) + pair + struct.pack("<Q", block_size) + b"APK Sig Block 42"
    )
    central_directory_offset = len(payload) + len(signing_block)
    eocd = b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, 0, 0, 0, central_directory_offset, 0)
    apk.write_bytes(payload + signing_block + eocd)
    return apk


def write_signing_plan(
    tmp_path: Path,
    signed_apk: Path,
    *,
    keystore: Path | None = None,
    apksigner: Path | None = None,
) -> Path:
    effective_keystore = keystore or tmp_path / "secrets" / "goffy-release.jks"
    effective_keystore.parent.mkdir(parents=True, exist_ok=True)
    effective_keystore.write_bytes(b"not a real keystore")
    effective_apksigner = apksigner or write_apksigner(tmp_path)
    path = tmp_path / "release-signing-plan.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": SIGNING_SCHEMA_VERSION,
                "ok": True,
                "status": "READY_TO_SIGN",
                "unsigned_apk": {
                    "path": str(tmp_path / "app-release-unsigned.apk"),
                    "exists": True,
                    "sha256": "b" * 64,
                    "byte_count": 123,
                },
                "signed_apk": str(signed_apk),
                "apksigner": str(effective_apksigner),
                "keystore": str(effective_keystore),
                "key_alias": "goffy-release",
                "blockers": [],
                "warnings": [],
                "commands": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def write_apk_verification(tmp_path: Path, apk: Path) -> Path:
    path = tmp_path / "release-apk-verification.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": APK_VERIFICATION_SCHEMA_VERSION,
                "ok": True,
                "status": "VERIFIED",
                "destructive_actions": "withheld",
                "apk": {
                    "path": str(apk),
                    "exists": True,
                    "sha256": "c" * 64,
                    "byte_count": 123,
                    "signature_schemes": ["v2"],
                },
                "blockers": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def write_apksigner(tmp_path: Path) -> Path:
    tool = tmp_path / "sdk" / "build-tools" / "36.0.0" / "apksigner"
    tool.parent.mkdir(parents=True, exist_ok=True)
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    return tool
