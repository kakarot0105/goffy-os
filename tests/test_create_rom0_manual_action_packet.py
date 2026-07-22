from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch
from scripts.create_rom0_manual_action_packet import (
    ALLOWED_COMMAND_PREFIXES,
    FORBIDDEN_DESTRUCTIVE_TERMS,
    JSON_SCHEMA_VERSION,
    ActionStatus,
    PacketStatus,
    build_packet,
    load_gsi_candidate_evidence,
    load_probe_json,
    main,
    render_json,
    render_markdown,
)

LOCKED_PROBE = {
    "schema_version": "goffy.rom-feasibility-probe.v1",
    "ok": False,
    "generated_at": "2026-07-21T00:00:00+00:00",
    "device": {
        "model": "moto g - 2025",
        "codename": "kansas",
        "product": "kansas_g_sys",
        "carrier": "tracfone",
        "hardware_sku": "XT2513V",
    },
    "properties": {
        "ro.build.fingerprint": (
            "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys"
        )
    },
    "boot": {
        "flash_locked": "1",
        "vbmeta_device_state": "locked",
        "verified_boot_state": "green",
    },
    "platform": {"soc_model": "MT6835", "android_release": "16", "sdk": "36"},
    "treble": {"enabled": "true", "dynamic_partitions": "true"},
    "dsu": {"package_present": "true", "start_install_resolves": "true"},
    "blockers": ["bootloader is currently locked; do not flash, root, or boot custom images yet"],
}


def test_locked_probe_packet_withholds_destructive_authority() -> None:
    packet = build_packet(LOCKED_PROBE)
    markdown = render_markdown(packet)
    payload = render_json(packet)

    assert packet.schema_version == JSON_SCHEMA_VERSION
    assert packet.status is PacketStatus.BLOCKED_MANUAL_EVIDENCE
    assert packet.destructive_actions == "withheld"
    assert packet.device["codename"] == "kansas"
    assert packet.device["hardware_sku"] == "XT2513V"
    assert packet.device["build_fingerprint"].startswith("motorola/kansas_g_sys/kansas")
    assert "hardware_sku: `XT2513V`" in markdown
    assert "dsu_package_installed: `true`" in markdown
    assert "build_fingerprint: `motorola/kansas_g_sys/kansas" in markdown
    assert "Motorola Software Fix" in markdown
    assert "create_rom_unlock_eligibility_evidence.py" in markdown
    assert "create_rom_stock_restore_evidence.py" in markdown
    assert "create_rom_gsi_candidate_evidence.py" in markdown
    assert "verify_rom0_readiness.py" in markdown
    forbidden_terms = (
        *FORBIDDEN_DESTRUCTIVE_TERMS,
        "fastboot reboot bootloader",
        "fastboot reboot fastboot",
        "fastboot boot",
        "adb reboot bootloader",
        "adb reboot fastboot",
    )
    for term in forbidden_terms:
        assert term not in markdown.lower()
        assert term not in payload.lower()
    for action in packet.actions:
        for command in action.safe_commands:
            assert command.startswith(ALLOWED_COMMAND_PREFIXES)


def test_packet_records_safe_evidence_without_approving_unlock() -> None:
    probe = dict(LOCKED_PROBE)
    probe["ok"] = True
    probe["blockers"] = []
    probe["boot"] = {"flash_locked": "0", "vbmeta_device_state": "unlocked"}
    unlock = {
        "source_url": "https://en-us.support.motorola.com/app/answers/detail/a_id/89973",
        "oem_unlocking_visible": True,
        "oem_unlocking_enabled": True,
        "motorola_unlock_eligibility": "eligible",
        "operator_note_code": "checked_no_identifiers_stored",
    }
    stock = {
        "source_url": "https://en-us.support.motorola.com/app/softwarefix",
        "archive_name": "kansas-stock.zip",
        "sha256": "a" * 64,
        "rollback_doc": "docs/setup/kansas-stock-rollback.md",
    }
    gsi_candidate = gsi_candidate_summary()

    packet = build_packet(
        probe,
        unlock_eligibility=unlock,
        stock_restore=stock,
        gsi_candidate=gsi_candidate,
    )
    actions = {action.action_id: action for action in packet.actions}

    assert packet.status is PacketStatus.READY_FOR_ROM0_READINESS_REVIEW
    assert packet.destructive_actions == "withheld"
    assert actions["record_unlock_eligibility"].status is ActionStatus.RECORDED
    assert actions["record_stock_restore"].status is ActionStatus.RECORDED
    assert actions["record_gsi_candidate"].status is ActionStatus.RECORDED
    assert actions["create_manual_gates"].status is ActionStatus.READY
    assert actions["summarize_rom0_readiness"].status is ActionStatus.READY
    assert all(
        "--probe-json .goffy-validation/rom-feasibility-current.json" in command
        for command in actions["create_manual_gates"].safe_commands
    )
    assert any(
        "--gsi-candidate-evidence-json .goffy-validation/rom-gsi-candidate-evidence.json" in command
        for command in actions["summarize_rom0_readiness"].safe_commands
    )
    assert "does not approve bootloader unlocking" in render_markdown(packet)


def test_locked_probe_with_evidence_is_ready_for_manual_template_only() -> None:
    unlock = {
        "source_url": "https://en-us.support.motorola.com/app/answers/detail/a_id/89973",
        "oem_unlocking_visible": True,
        "oem_unlocking_enabled": True,
        "motorola_unlock_eligibility": "eligible",
        "operator_note_code": "checked_no_identifiers_stored",
    }
    stock = {
        "source_url": "https://en-us.support.motorola.com/app/softwarefix",
        "archive_name": "kansas-stock.zip",
        "sha256": "a" * 64,
        "rollback_doc": "docs/setup/kansas-stock-rollback.md",
    }

    packet = build_packet(LOCKED_PROBE, unlock_eligibility=unlock, stock_restore=stock)
    actions = {action.action_id: action for action in packet.actions}

    assert packet.status is PacketStatus.READY_FOR_MANUAL_GATE_TEMPLATE
    assert "ROM probe does not show an unlocked bootloader" in packet.blocked_by
    assert "official Google ARM64 GSI evidence is missing" in packet.blocked_by
    assert packet.destructive_actions == "withheld"
    assert actions["record_gsi_candidate"].status is ActionStatus.REQUIRED
    assert actions["summarize_rom0_readiness"].status is ActionStatus.BLOCKED


def test_locked_probe_with_all_evidence_does_not_report_readiness_review() -> None:
    unlock = {
        "source_url": "https://en-us.support.motorola.com/app/answers/detail/a_id/89973",
        "oem_unlocking_visible": True,
        "oem_unlocking_enabled": True,
        "motorola_unlock_eligibility": "eligible",
        "operator_note_code": "checked_no_identifiers_stored",
    }
    stock = {
        "source_url": "https://en-us.support.motorola.com/app/softwarefix",
        "archive_name": "kansas-stock.zip",
        "sha256": "a" * 64,
        "rollback_doc": "docs/setup/kansas-stock-rollback.md",
    }

    packet = build_packet(
        LOCKED_PROBE,
        unlock_eligibility=unlock,
        stock_restore=stock,
        gsi_candidate=gsi_candidate_summary(),
    )
    actions = {action.action_id: action for action in packet.actions}

    assert packet.status is PacketStatus.READY_FOR_MANUAL_GATE_TEMPLATE
    assert "ROM probe does not show an unlocked bootloader" in packet.blocked_by
    assert "official Google ARM64 GSI evidence is missing" not in packet.blocked_by
    assert actions["record_gsi_candidate"].status is ActionStatus.RECORDED
    assert actions["summarize_rom0_readiness"].status is ActionStatus.BLOCKED
    assert (
        "ROM probe does not show an unlocked bootloader"
        in actions["summarize_rom0_readiness"].blockers
    )


def test_load_probe_json_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "probe.json"
    path.write_text(json.dumps({"schema_version": "unexpected"}), encoding="utf-8")

    try:
        load_probe_json(path)
    except ValueError as exc:
        assert "unsupported ROM probe schema" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_packet_accepts_legacy_dsu_package_installed_probe_field() -> None:
    probe = {
        **LOCKED_PROBE,
        "dsu": {"package_installed": "true"},
    }

    packet = build_packet(probe)

    assert packet.device["dsu_package_installed"] == "true"


def test_load_gsi_candidate_evidence_rejects_invalid_evidence(tmp_path: Path) -> None:
    path = tmp_path / "rom-gsi-candidate-evidence.json"
    path.write_text(json.dumps({"schema_version": "unexpected"}), encoding="utf-8")

    try:
        load_gsi_candidate_evidence(path)
    except ValueError as exc:
        assert "ROM GSI candidate evidence schema_version mismatch" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_loads_gsi_candidate_evidence(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps(LOCKED_PROBE), encoding="utf-8")
    output = tmp_path / ".goffy-validation" / "rom-0-manual-action-packet.json"
    gsi_candidate = write_gsi_candidate_evidence(tmp_path)

    def temp_write(path: Path, text: str) -> None:
        from scripts.create_rom_stock_restore_evidence import write_output

        write_output(path, text, root=tmp_path)

    monkeypatch.setattr("scripts.create_rom0_manual_action_packet.write_output", temp_write)

    assert (
        main(
            [
                str(probe),
                "--gsi-candidate-evidence",
                str(gsi_candidate),
                "--json",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    actions = {action["action_id"]: action for action in payload["actions"]}
    assert actions["record_gsi_candidate"]["status"] == "RECORDED"


def test_cli_writes_only_under_validation_dir(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps(LOCKED_PROBE), encoding="utf-8")
    allowed = tmp_path / ".goffy-validation" / "rom-0-manual-action-packet.md"
    blocked = tmp_path / "ROM_PACKET.md"

    def temp_write(path: Path, text: str) -> None:
        from scripts.create_rom_stock_restore_evidence import write_output

        write_output(path, text, root=tmp_path)

    monkeypatch.setattr("scripts.create_rom0_manual_action_packet.write_output", temp_write)

    assert main([str(probe), "--output", str(allowed)]) == 0
    assert allowed.read_text(encoding="utf-8").startswith("# GOFFY ROM-0 Manual Action Packet")
    assert main([str(probe), "--output", str(blocked)]) == 1
    assert not blocked.exists()


def write_gsi_candidate_evidence(tmp_path: Path) -> Path:
    path = tmp_path / "rom-gsi-candidate-evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "goffy.rom-gsi-candidate-evidence.v1",
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
                    "artifact_name": "aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip",
                    "byte_count": 123456789,
                    "sha256": "2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea",
                    "expected_sha256": (
                        "2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea"
                    ),
                },
                "source": {
                    "source_url": "https://developer.android.com/topic/generic-system-image/releases",
                    "download_url": (
                        "https://dl.google.com/developers/android/baklava/images/gsi/"
                        "aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip"
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


def gsi_candidate_summary() -> dict[str, str]:
    return {
        "status": "ARTIFACT_CHECKSUM_VERIFIED",
        "candidate_name": "Official Google Android 16 ARM64 GSI",
        "android_release": "16",
        "architecture": "arm64",
        "artifact_name": "aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip",
        "sha256": "2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea",
        "source_url": "https://developer.android.com/topic/generic-system-image/releases",
        "authorization": "NON_AUTHORIZING_EVIDENCE",
    }
