from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import scripts.rom_feasibility_probe as probe
from scripts.rom_feasibility_probe import RomPath, build_report, parse_vndk_isolated, render_json
from scripts.run_moto_g_device_smoke import CommandResult

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
    "ro.oem_unlock_supported": "",
    "sys.oem_unlock_allowed": "",
    "ro.treble.enabled": "true",
    "ro.apex.updatable": "true",
    "ro.carrier": "tracfone",
    "ro.vendor.build.security_patch": "2026-06-01",
}


def test_parse_vndk_isolated_reads_vendor_section() -> None:
    assert (
        parse_vndk_isolated(
            """
            [system]
            namespace.default.isolated = false
            [vendor]
            namespace.default.isolated = true
            """
        )
        == "true"
    )


def test_probe_reports_locked_bootloader_without_serial(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    report = build_report(root=tmp_path, runner=runner_for(LOCKED_PROPS))

    payload = render_json(report)

    assert not report.ok
    assert report.rom_path is RomPath.BLOCKED_LOCKED_BOOTLOADER
    assert report.device["codename"] == "kansas"
    assert report.platform["soc_model"] == "MT6835"
    assert report.treble["enabled"] == "true"
    assert "bootloader is currently locked" in report.blockers[0]
    assert SERIAL not in payload


def test_probe_reports_gsi_first_after_unlock(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    props = dict(LOCKED_PROPS)
    props["ro.boot.flash.locked"] = "0"
    props["ro.boot.vbmeta.device_state"] = "unlocked"

    report = build_report(root=tmp_path, runner=runner_for(props))

    assert report.ok
    assert report.rom_path is RomPath.GSI_OR_DSU_FIRST
    assert any("DSU/GSI" in step for step in report.next_steps)


def test_probe_does_not_mislabel_non_bootloader_blocker(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(probe, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    props = dict(LOCKED_PROPS)
    props["ro.boot.flash.locked"] = "0"
    props["ro.boot.vbmeta.device_state"] = "unlocked"
    props["ro.treble.enabled"] = "false"

    report = build_report(root=tmp_path, runner=runner_for(props))

    assert not report.ok
    assert report.rom_path is RomPath.UNKNOWN
    assert any("Treble support is not confirmed" in blocker for blocker in report.blockers)


def runner_for(properties: dict[str, str]):
    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == ("/opt/android/adb", "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[-2:] == ("shell", "cat"):
            return CommandResult(1, "", "missing path")
        if normalized[-3:] == (
            "shell",
            "cat",
            "/system/etc/ld.config.version_identifier.txt",
        ):
            return CommandResult(0, "[vendor]\nnamespace.default.isolated = true\n", "")
        if len(normalized) >= 5 and normalized[-2] == "getprop":
            return CommandResult(0, f"{properties.get(normalized[-1], '')}\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    return runner
