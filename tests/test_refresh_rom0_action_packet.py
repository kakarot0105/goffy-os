from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.refresh_rom0_action_packet as refresh
import scripts.rom_feasibility_probe as probe
from pytest import MonkeyPatch
from scripts.create_rom0_manual_action_packet import PacketStatus
from scripts.refresh_rom0_action_packet import (
    EvidenceStatus,
    RefreshStatus,
    refresh_rom0_action_packet,
)
from scripts.run_moto_g_device_smoke import CommandResult, CommandRunner

SERIAL = "ZY32LBQLMQ"
ADB_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL} device usb:2-1.2 product:kansas_g_sys model:moto_g___2025 device:kansas\n"
)

LOCKED_PROPS = {
    "ro.product.model": "moto g - 2025",
    "ro.product.device": "kansas",
    "ro.product.name": "kansas_g_sys",
    "ro.product.manufacturer": "motorola",
    "ro.product.brand": "motorola",
    "ro.product.board": "kansas",
    "ro.hardware": "mt6835",
    "ro.board.platform": "mt6835",
    "ro.soc.manufacturer": "Mediatek",
    "ro.soc.model": "MT6835",
    "ro.build.version.release": "16",
    "ro.build.version.sdk": "36",
    "ro.build.version.incremental": "ebe4e3-2b6752",
    "ro.build.version.security_patch": "2026-06-01",
    "ro.build.fingerprint": (
        "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys"
    ),
    "ro.boot.hardware": "mt6835",
    "ro.boot.slot_suffix": "_b",
    "ro.boot.flash.locked": "1",
    "ro.boot.vbmeta.device_state": "locked",
    "ro.boot.verifiedbootstate": "green",
    "ro.boot.dynamic_partitions": "true",
    "ro.boot.product.hardware.sku": "dn",
    "ro.boot.hardware.sku": "XT2513V",
    "ro.oem_unlock_supported": "",
    "sys.oem_unlock_allowed": "",
    "ro.treble.enabled": "true",
    "ro.apex.updatable": "true",
    "ro.carrier": "tracfone",
    "ro.vendor.build.security_patch": "2026-06-01",
}


def test_refresh_writes_probe_packet_and_summary_without_mutation(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(LOCKED_PROPS))

    validation = tmp_path / ".goffy-validation"
    probe_json = validation / "rom-feasibility-current.json"
    packet_md = validation / "rom-0-manual-action-packet.md"
    packet_json = validation / "rom-0-manual-action-packet.json"
    guide_md = validation / "rom-bootloader-visibility-guide.md"
    guide_json = validation / "rom-bootloader-visibility-guide.json"
    operator_md = validation / "rom-0-operator-checklist.md"
    operator_json = validation / "rom-0-operator-checklist.json"
    summary_json = validation / "rom-0-refresh-report.json"
    packet_payload = json.loads(packet_json.read_text(encoding="utf-8"))
    evidence = {item.name: item for item in report.evidence_inputs}
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            probe_json,
            packet_md,
            packet_json,
            guide_md,
            guide_json,
            operator_md,
            operator_json,
            summary_json,
        )
    ).lower()

    assert report.schema_version == "goffy.rom0-refresh-report.v3"
    assert not report.ok
    assert report.status is RefreshStatus.BLOCKED
    assert report.refresh_succeeded
    assert not report.rom_ready
    assert report.packet_status == PacketStatus.BLOCKED_MANUAL_EVIDENCE
    assert report.bootloader_visibility_status == "HOST_EVIDENCE_MISSING"
    assert report.operator_checklist_status == "BLOCKED_EVIDENCE"
    assert "ROM probe does not show an unlocked bootloader" in report.blocked_by
    assert evidence["unlock_eligibility"].status is EvidenceStatus.MISSING
    assert evidence["stock_restore"].status is EvidenceStatus.MISSING
    assert evidence["gsi_candidate"].status is EvidenceStatus.MISSING
    assert evidence["fastboot_evidence"].status is EvidenceStatus.MISSING
    assert evidence["bootloader_visibility_guide"].status is EvidenceStatus.LOADED
    assert evidence["operator_checklist"].status is EvidenceStatus.LOADED
    assert probe_json.is_file()
    assert packet_md.is_file()
    assert packet_json.is_file()
    assert guide_md.is_file()
    assert guide_json.is_file()
    assert operator_md.is_file()
    assert operator_json.is_file()
    assert summary_json.is_file()
    assert packet_payload["destructive_actions"] == "withheld"
    assert SERIAL.lower() not in combined
    assert "fastboot flash" not in combined
    assert "fastboot erase" not in combined
    assert "adb reboot bootloader" not in combined
    assert "create_rom_fastboot_evidence.py" in combined


def test_refresh_consumes_valid_existing_evidence(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    write_unlock_evidence(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)
    write_fastboot_evidence(tmp_path, manual_visible=True)

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(LOCKED_PROPS))
    evidence = {item.name: item for item in report.evidence_inputs}

    assert not report.ok
    assert report.status is RefreshStatus.BLOCKED
    assert report.refresh_succeeded
    assert not report.rom_ready
    assert report.packet_status == PacketStatus.READY_FOR_MANUAL_GATE_TEMPLATE
    assert report.bootloader_visibility_status == "MANUAL_BOOTLOADER_VISIBLE"
    assert report.operator_checklist_status == "BLOCKED_EVIDENCE"
    assert evidence["unlock_eligibility"].status is EvidenceStatus.LOADED
    assert evidence["stock_restore"].status is EvidenceStatus.LOADED
    assert evidence["gsi_candidate"].status is EvidenceStatus.LOADED
    assert evidence["fastboot_evidence"].status is EvidenceStatus.LOADED
    assert evidence["bootloader_visibility_guide"].status is EvidenceStatus.LOADED
    assert evidence["operator_checklist"].status is EvidenceStatus.LOADED
    assert "ROM probe does not show an unlocked bootloader" in report.blocked_by


def test_refresh_blocks_host_only_fastboot_even_with_other_ready_evidence(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    props = dict(LOCKED_PROPS)
    props["ro.boot.flash.locked"] = "0"
    props["ro.boot.vbmeta.device_state"] = "unlocked"
    write_unlock_evidence(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)
    write_fastboot_evidence(tmp_path)

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(props))
    evidence = {item.name: item for item in report.evidence_inputs}

    assert not report.ok
    assert report.status is RefreshStatus.BLOCKED
    assert report.refresh_succeeded
    assert not report.rom_ready
    assert report.packet_status == PacketStatus.READY_FOR_MANUAL_GATE_TEMPLATE
    assert report.bootloader_visibility_status == "READY_FOR_MANUAL_BOOTLOADER_CHECK"
    assert report.operator_checklist_status == "BLOCKED_EVIDENCE"
    assert evidence["fastboot_evidence"].status is EvidenceStatus.LOADED
    assert evidence["bootloader_visibility_guide"].status is EvidenceStatus.LOADED
    assert evidence["operator_checklist"].status is EvidenceStatus.LOADED
    assert "manual bootloader-mode fastboot visibility evidence is missing" in report.blocked_by


def test_refresh_reports_ready_only_when_probe_and_evidence_are_ready(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    props = dict(LOCKED_PROPS)
    props["ro.boot.flash.locked"] = "0"
    props["ro.boot.vbmeta.device_state"] = "unlocked"
    write_unlock_evidence(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)
    write_fastboot_evidence(tmp_path, manual_visible=True)

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(props))

    assert report.ok
    assert report.status is RefreshStatus.READY_FOR_ROM0_READINESS_REVIEW
    assert report.refresh_succeeded
    assert report.rom_ready
    assert report.bootloader_visibility_status == "MANUAL_BOOTLOADER_VISIBLE"
    assert report.operator_checklist_status == "READY_FOR_ROM0_READINESS_REVIEW"
    assert report.blocked_by == ()


def test_refresh_fails_closed_and_redacts_when_guide_generation_fails(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    props = dict(LOCKED_PROPS)
    props["ro.boot.flash.locked"] = "0"
    props["ro.boot.vbmeta.device_state"] = "unlocked"
    write_unlock_evidence(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)
    write_fastboot_evidence(tmp_path, manual_visible=True)
    original_write = refresh.write_validation_file

    def failing_write(path: Path, text: str, *, root: Path) -> None:
        if path.name == "rom-bootloader-visibility-guide.json":
            raise OSError(f"cannot write {path.resolve()}")
        original_write(path, text, root=root)

    monkeypatch.setattr(refresh, "write_validation_file", failing_write)

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(props))
    evidence = {item.name: item for item in report.evidence_inputs}
    payload = refresh.render_json(report)

    assert not report.ok
    assert report.status is RefreshStatus.ERROR
    assert not report.refresh_succeeded
    assert not report.rom_ready
    assert report.packet_status == PacketStatus.READY_FOR_ROM0_READINESS_REVIEW
    assert report.bootloader_visibility_status == "INVALID"
    assert report.operator_checklist_status == "BLOCKED_EVIDENCE"
    assert evidence["bootloader_visibility_guide"].status is EvidenceStatus.INVALID
    assert evidence["operator_checklist"].status is EvidenceStatus.LOADED
    assert "<path>" in evidence["bootloader_visibility_guide"].detail
    assert str(tmp_path) not in payload


def test_refresh_fails_closed_and_redacts_when_operator_checklist_generation_fails(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    props = dict(LOCKED_PROPS)
    props["ro.boot.flash.locked"] = "0"
    props["ro.boot.vbmeta.device_state"] = "unlocked"
    write_unlock_evidence(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)
    write_fastboot_evidence(tmp_path, manual_visible=True)
    original_write = refresh.write_validation_file

    def failing_write(path: Path, text: str, *, root: Path) -> None:
        if path.name == "rom-0-operator-checklist.json":
            raise OSError(f"cannot write {path.resolve()}")
        original_write(path, text, root=root)

    monkeypatch.setattr(refresh, "write_validation_file", failing_write)

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(props))
    evidence = {item.name: item for item in report.evidence_inputs}
    payload = refresh.render_json(report)

    assert not report.ok
    assert report.status is RefreshStatus.ERROR
    assert not report.refresh_succeeded
    assert not report.rom_ready
    assert report.packet_status == PacketStatus.READY_FOR_ROM0_READINESS_REVIEW
    assert report.operator_checklist_status == "INVALID"
    assert evidence["operator_checklist"].status is EvidenceStatus.INVALID
    assert "<path>" in evidence["operator_checklist"].detail
    assert str(tmp_path) not in payload


def test_refresh_removes_partial_operator_checklist_when_markdown_write_fails(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    props = dict(LOCKED_PROPS)
    props["ro.boot.flash.locked"] = "0"
    props["ro.boot.vbmeta.device_state"] = "unlocked"
    write_unlock_evidence(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)
    write_fastboot_evidence(tmp_path, manual_visible=True)
    original_write = refresh.write_validation_file

    def failing_write(path: Path, text: str, *, root: Path) -> None:
        if path.name == "rom-0-operator-checklist.md":
            raise OSError(f"cannot write {path.resolve()}")
        original_write(path, text, root=root)

    monkeypatch.setattr(refresh, "write_validation_file", failing_write)

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(props))
    validation = tmp_path / ".goffy-validation"
    evidence = {item.name: item for item in report.evidence_inputs}
    payload = refresh.render_json(report)

    assert not report.ok
    assert report.status is RefreshStatus.ERROR
    assert not report.refresh_succeeded
    assert not report.rom_ready
    assert report.operator_checklist_status == "INVALID"
    assert evidence["operator_checklist"].status is EvidenceStatus.INVALID
    assert not (validation / "rom-0-operator-checklist.json").exists()
    assert not (validation / "rom-0-operator-checklist.md").exists()
    assert "<path>" in evidence["operator_checklist"].detail
    assert str(tmp_path) not in payload


def test_refresh_report_write_failure_does_not_leave_operator_outputs(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    props = dict(LOCKED_PROPS)
    props["ro.boot.flash.locked"] = "0"
    props["ro.boot.vbmeta.device_state"] = "unlocked"
    write_unlock_evidence(tmp_path)
    write_stock_evidence(tmp_path)
    write_gsi_evidence(tmp_path)
    write_fastboot_evidence(tmp_path, manual_visible=True)
    validation = tmp_path / ".goffy-validation"
    stale_json = validation / "rom-0-operator-checklist.json"
    stale_md = validation / "rom-0-operator-checklist.md"
    stale_json.write_text('{"ok": true}', encoding="utf-8")
    stale_md.write_text("# stale ready checklist\n", encoding="utf-8")
    original_write = refresh.write_validation_file

    def failing_write(path: Path, text: str, *, root: Path) -> None:
        if path.name == "rom-0-refresh-report.json":
            raise OSError(f"cannot write {path.resolve()}")
        original_write(path, text, root=root)

    monkeypatch.setattr(refresh, "write_validation_file", failing_write)

    with pytest.raises(OSError, match="cannot write"):
        refresh_rom0_action_packet(root=tmp_path, runner=runner_for(props))

    assert not stale_json.exists()
    assert not stale_md.exists()


def test_refresh_main_redacts_top_level_errors(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def failing_refresh(**_kwargs: object) -> object:
        raise OSError(
            f"cannot write {tmp_path / '.goffy-validation' / 'rom-0-refresh-report.json'}"
        )

    monkeypatch.setattr(refresh, "refresh_rom0_action_packet", failing_refresh)

    assert refresh.main([]) == 1
    captured = capsys.readouterr()
    assert "<path>" in captured.err
    assert str(tmp_path) not in captured.err


def test_refresh_fails_closed_for_invalid_existing_evidence(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    validation = tmp_path / ".goffy-validation"
    validation.mkdir()
    (validation / "rom-gsi-candidate-evidence.json").write_text(
        json.dumps({"schema_version": "unexpected"}),
        encoding="utf-8",
    )

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(LOCKED_PROPS))
    evidence = {item.name: item for item in report.evidence_inputs}

    assert not report.ok
    assert report.status is RefreshStatus.ERROR
    assert not report.refresh_succeeded
    assert evidence["gsi_candidate"].status is EvidenceStatus.INVALID
    assert "gsi_candidate:" in report.errors[0]
    assert "official Google ARM64 GSI evidence is missing" in report.blocked_by


def test_refresh_fails_closed_for_invalid_fastboot_evidence(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    validation = tmp_path / ".goffy-validation"
    validation.mkdir()
    (validation / "rom-fastboot-evidence.json").write_text(
        json.dumps({"schema_version": "unexpected"}),
        encoding="utf-8",
    )

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(LOCKED_PROPS))
    evidence = {item.name: item for item in report.evidence_inputs}

    assert not report.ok
    assert report.status is RefreshStatus.ERROR
    assert not report.refresh_succeeded
    assert evidence["fastboot_evidence"].status is EvidenceStatus.INVALID
    assert evidence["bootloader_visibility_guide"].status is EvidenceStatus.LOADED
    assert evidence["operator_checklist"].status is EvidenceStatus.LOADED
    assert report.bootloader_visibility_status == "FASTBOOT_EVIDENCE_INVALID"
    assert report.operator_checklist_status == "BLOCKED_EVIDENCE"
    assert any(error.startswith("fastboot_evidence:") for error in report.errors)
    assert "manual bootloader-mode fastboot visibility evidence is missing" in report.blocked_by


def test_refresh_rejects_symlinked_evidence_outside_validation_dir(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    validation = tmp_path / ".goffy-validation"
    validation.mkdir()
    outside = tmp_path / "outside-unlock.json"
    write_unlock_evidence_payload(outside)
    (validation / "rom-unlock-eligibility-evidence.json").symlink_to(outside)

    report = refresh_rom0_action_packet(root=tmp_path, runner=runner_for(LOCKED_PROPS))
    evidence = {item.name: item for item in report.evidence_inputs}

    assert not report.ok
    assert report.status is RefreshStatus.ERROR
    assert not report.refresh_succeeded
    assert evidence["unlock_eligibility"].status is EvidenceStatus.INVALID
    assert "symlink" in evidence["unlock_eligibility"].detail


def test_refresh_rejects_validation_dir_outside_validation_root(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))

    with pytest.raises(ValueError, match="path must be under .goffy-validation"):
        refresh_rom0_action_packet(
            root=tmp_path,
            validation_dir=tmp_path / "outside-validation",
            runner=runner_for(LOCKED_PROPS),
        )


def write_unlock_evidence(root: Path) -> None:
    validation = root / ".goffy-validation"
    validation.mkdir(exist_ok=True)
    write_unlock_evidence_payload(validation / "rom-unlock-eligibility-evidence.json")


def write_unlock_evidence_payload(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "goffy.rom-unlock-eligibility-evidence.v1",
                "generated_at": "2026-07-22T00:00:00+00:00",
                "unlock_eligibility": {
                    "source_url": "https://en-us.support.motorola.com/app/answers/detail/a_id/89973",
                    "oem_unlocking_visible": True,
                    "oem_unlocking_enabled": True,
                    "motorola_unlock_eligibility": "eligible",
                    "operator_note_code": "checked_no_identifiers_stored",
                },
            }
        ),
        encoding="utf-8",
    )


def write_stock_evidence(root: Path) -> None:
    validation = root / ".goffy-validation"
    validation.mkdir(exist_ok=True)
    (validation / "rom-stock-restore-evidence.json").write_text(
        json.dumps(
            {
                "schema_version": "goffy.rom-stock-restore-evidence.v1",
                "generated_at": "2026-07-22T00:00:00+00:00",
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


def write_gsi_evidence(root: Path) -> None:
    validation = root / ".goffy-validation"
    validation.mkdir(exist_ok=True)
    (validation / "rom-gsi-candidate-evidence.json").write_text(
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


def write_fastboot_evidence(root: Path, *, manual_visible: bool = False) -> None:
    validation = root / ".goffy-validation"
    validation.mkdir(exist_ok=True)
    commands = [
        {
            "label": "fastboot --version",
            "exit_code": 0,
            "timed_out": False,
            "stdout": "fastboot version 37.0.0-14910828\nInstalled as <path>",
            "stderr": "",
        }
    ]
    if manual_visible:
        commands.append(
            {
                "label": "fastboot devices",
                "exit_code": 0,
                "timed_out": False,
                "stdout": "<device-serial>\tfastboot",
                "stderr": "",
            }
        )
    (validation / "rom-fastboot-evidence.json").write_text(
        json.dumps(
            {
                "schema_version": "goffy.rom-fastboot-evidence.v1",
                "generated_at": "2026-07-22T00:00:00+00:00",
                "ok": True,
                "status": "MANUAL_BOOTLOADER_VISIBLE" if manual_visible else "HOST_READY",
                "destructive_actions": "withheld",
                "host": {
                    "fastboot": "available",
                    "fastboot_path": "<android-sdk>/platform-tools/fastboot",
                    "fastboot_version": "37.0.0-14910828",
                },
                "manual_bootloader_check": {
                    "requested": manual_visible,
                    "bootloader_device_visible": manual_visible,
                    "bootloader_device_count": 1 if manual_visible else 0,
                    "serials_redacted": True,
                },
                "commands": commands,
                "blockers": [],
                "warnings": []
                if manual_visible
                else ["manual bootloader visibility was not checked; do not reboot automatically"],
            }
        ),
        encoding="utf-8",
    )


def runner_for(properties: dict[str, str]) -> CommandRunner:
    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[-3:] == (
            "shell",
            "cat",
            "/system/etc/ld.config.version_identifier.txt",
        ):
            return CommandResult(0, "[vendor]\nnamespace.default.isolated = true\n", "")
        if normalized[-4:] == ("shell", "pm", "path", "com.android.dynsystem"):
            return CommandResult(
                0,
                (
                    "package:/system/priv-app/DynamicSystemInstallationService/"
                    "DynamicSystemInstallationService.apk\n"
                ),
                "",
            )
        if normalized[-9:] == (
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            "android.os.image.action.START_INSTALL",
            "-d",
            "file:///storage/emulated/0/Download/goffy-dsu-placeholder.gz",
        ):
            return CommandResult(
                0,
                (
                    "priority=0 preferredOrder=0 match=0x208000 specificIndex=-1 "
                    "isDefault=true\n"
                    "com.android.dynsystem/.VerificationActivity\n"
                ),
                "",
            )
        if len(normalized) >= 5 and normalized[-2] == "getprop":
            return CommandResult(0, f"{properties.get(normalized[-1], '')}\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    return runner
