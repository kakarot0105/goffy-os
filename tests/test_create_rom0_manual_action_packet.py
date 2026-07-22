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

    packet = build_packet(probe, unlock_eligibility=unlock, stock_restore=stock)
    actions = {action.action_id: action for action in packet.actions}

    assert packet.status is PacketStatus.READY_FOR_MANUAL_GATE_TEMPLATE
    assert packet.destructive_actions == "withheld"
    assert actions["record_unlock_eligibility"].status is ActionStatus.RECORDED
    assert actions["record_stock_restore"].status is ActionStatus.RECORDED
    assert actions["create_manual_gates"].status is ActionStatus.READY
    assert all(
        "--probe-json .goffy-validation/rom-feasibility-current.json" in command
        for command in actions["create_manual_gates"].safe_commands
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

    assert packet.status is PacketStatus.READY_FOR_MANUAL_GATE_TEMPLATE
    assert packet.blocked_by == ()
    assert packet.destructive_actions == "withheld"


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
