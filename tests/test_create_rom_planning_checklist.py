from __future__ import annotations

import json
from pathlib import Path

from scripts.create_rom_planning_checklist import (
    DEVICE_SERIAL_PLACEHOLDER,
    JSON_SCHEMA_VERSION,
    DryRunStatus,
    build_checklist,
    load_probe_json,
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
    },
    "boot": {
        "flash_locked": "1",
        "vbmeta_device_state": "locked",
        "verified_boot_state": "green",
    },
    "platform": {"soc_model": "MT6835", "android_release": "16", "sdk": "36"},
    "treble": {"enabled": "true", "dynamic_partitions": "true"},
    "blockers": ["bootloader is currently locked; do not flash, root, or boot custom images yet"],
    "warnings": ["VNDK isolation could not be confirmed from system config"],
}


def test_locked_probe_blocks_destructive_rom_steps() -> None:
    checklist = build_checklist(LOCKED_PROBE)
    markdown = render_markdown(checklist)
    payload = render_json(checklist)

    assert checklist.status is DryRunStatus.BLOCKED_LOCKED_BOOTLOADER
    assert checklist.schema_version == JSON_SCHEMA_VERSION
    assert any("bootloader is currently locked" in blocker for blocker in checklist.blockers)
    assert "fastboot flashing unlock" not in markdown
    assert "fastboot flash" not in markdown
    assert DEVICE_SERIAL_PLACEHOLDER not in payload
    assert "Motorola Software Fix Rescue" in markdown
    assert "Google Android 16 GSI" in markdown
    assert "Reuse Prior Art" in markdown
    assert "INSPECT_ONLY_DO_NOT_IMPORT" in markdown


def test_unlocked_probe_still_blocks_until_stock_restore_evidence_exists() -> None:
    probe = dict(LOCKED_PROBE)
    probe["ok"] = True
    probe["blockers"] = []
    probe["boot"] = {"flash_locked": "0", "vbmeta_device_state": "unlocked"}

    checklist = build_checklist(probe)

    assert checklist.status is DryRunStatus.BLOCKED_RESTORE_NOT_READY
    assert any("structured stock restore evidence" in blocker for blocker in checklist.blockers)
    assert not any(step.phase == "dsu" for step in checklist.steps)


def test_structured_restore_evidence_emits_only_template_dsu_commands() -> None:
    probe = dict(LOCKED_PROBE)
    probe["ok"] = True
    probe["blockers"] = []
    probe["boot"] = {"flash_locked": "0", "vbmeta_device_state": "unlocked"}
    probe["stock_restore"] = {
        "source_url": "https://en-us.support.motorola.com/app/softwarefix",
        "archive_name": "kansas-stock.zip",
        "sha256": "a" * 64,
        "rollback_doc": "docs/setup/kansas-rollback.md",
    }

    checklist = build_checklist(probe)
    markdown = render_markdown(checklist)

    assert checklist.status is DryRunStatus.READY_FOR_APPROVAL_GATED_DSU_STAGING
    assert "TEMPLATE_ONLY" in markdown
    assert "com.android.dynsystem/com.android.dynsystem.VerificationActivity" in markdown
    assert "fastboot flash" not in markdown
    assert DEVICE_SERIAL_PLACEHOLDER in markdown


def test_reuse_prior_art_blocks_unsafe_kansas_tree_import() -> None:
    checklist = build_checklist(LOCKED_PROBE)
    payload = json.loads(render_json(checklist))

    candidates = {candidate["name"]: candidate for candidate in payload["reuse_candidates"]}
    kansas_tree = candidates["councilcj/android_device_motorola_kansas"]
    kernel_source = candidates["MotorolaMobilityLLC/kernel-mtk"]

    assert kansas_tree["decision"] == "INSPECT_ONLY_DO_NOT_IMPORT"
    assert "no LICENSE file" in kansas_tree["license_note"]
    assert "anti-rollback" in kansas_tree["risk"]
    assert kernel_source["decision"] == "BLOCKED_UNTIL_EXACT_KANSAS_BUILD_MATCH"
    assert "MMI-W1VKS36H.9-12-1" in kernel_source["risk"]
    assert "W1VKS36H.9-12-9-8-2" in kernel_source["next_check"]


def test_reuse_prior_art_records_concrete_lineage_repos() -> None:
    checklist = build_checklist(LOCKED_PROBE)
    payload = json.loads(render_json(checklist))
    candidate_names = {candidate["name"] for candidate in payload["reuse_candidates"]}

    assert "LineageOS/android_device_motorola_fogo" in candidate_names
    assert "LineageOS/android_device_motorola_pnangn" in candidate_names
    assert "LineageOS Motorola device trees for related devices" not in candidate_names


def test_load_probe_json_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "probe.json"
    path.write_text(json.dumps({"schema_version": "other"}), encoding="utf-8")

    try:
        load_probe_json(path)
    except ValueError as exc:
        assert "unsupported probe schema" in str(exc)
    else:
        raise AssertionError("expected ValueError")
