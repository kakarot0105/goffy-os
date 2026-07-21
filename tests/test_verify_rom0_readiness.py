from __future__ import annotations

import json
import struct
from pathlib import Path

from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION
from scripts.validate_rom_manual_gates import JSON_SCHEMA_VERSION as MANUAL_SCHEMA_VERSION
from scripts.validate_rom_manual_gates import ROLLBACK_REQUIRED_HEADINGS
from scripts.verify_rom0_readiness import (
    Rom0ReadinessStatus,
    build_readiness_report,
    render_markdown,
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
    assert "Externally signed GOFFY APK was not supplied" in section(report, "aosp_import").blockers


def test_rom0_readiness_accepts_complete_non_destructive_evidence(tmp_path: Path) -> None:
    probe = write_probe(tmp_path)
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

    assert report.ok
    assert report.status is Rom0ReadinessStatus.READY_FOR_HUMAN_REVIEW
    assert report.destructive_actions == "withheld"
    assert section(report, "aosp_import").evidence["apk_signature_schemes"] == "v2"
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


def section(report, name: str):
    return next(item for item in report.sections if item.name == name)


def write_probe(tmp_path: Path, *, unlocked: bool = True) -> Path:
    path = tmp_path / "probe.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": PROBE_SCHEMA_VERSION,
                "ok": True,
                "device": {"codename": "kansas", "product": "kansas_g_sys"},
                "boot": {
                    "flash_locked": "0" if unlocked else "1",
                    "vbmeta_device_state": "unlocked" if unlocked else "locked",
                },
                "treble": {"enabled": "true", "dynamic_partitions": "true"},
                "dsu": {"package_installed": "true"},
                "rom_path": "GSI_OR_DSU_FIRST",
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def write_manual_gates(tmp_path: Path, rollback_doc: Path) -> Path:
    path = tmp_path / "manual.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": MANUAL_SCHEMA_VERSION,
                "backup_confirmed": True,
                "oem_unlocking_enabled": True,
                "motorola_unlock_eligibility": "eligible",
                "destructive_approval": "not_requested",
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
            ]
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
