from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_gsi_candidate_evidence import OFFICIAL_GSI_RELEASES_URL  # noqa: E402
from scripts.create_rom_manual_gates_template import load_stock_restore_evidence  # noqa: E402
from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402
from scripts.create_rom_unlock_eligibility_evidence import (  # noqa: E402
    load_unlock_eligibility_evidence,
    unlock_evidence_probe_blockers,
)
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION  # noqa: E402
from scripts.verify_rom0_readiness import (  # noqa: E402
    EXPECTED_CODENAME,
    EXPECTED_PRODUCT,
    TARGET_DEVICE_EVIDENCE_KEYS,
    validate_fastboot_evidence,
    validate_gsi_candidate_evidence,
)

JSON_SCHEMA_VERSION = "goffy.rom0-manual-action-packet.v1"
DEVICE_SERIAL_PLACEHOLDER = "<device-serial>"
STOCK_ARCHIVE_PLACEHOLDER = "/absolute/path/outside/repo/<exact-kansas-stock-archive.zip>"
GSI_ARCHIVE_PLACEHOLDER = (
    "/absolute/path/outside/repo/aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip"
)
GSI_ARCHIVE_NAME = "aosp_arm64-exp-BP4A.251205.006-14401865-2171cf0e.zip"
GSI_DOWNLOAD_URL = f"https://dl.google.com/developers/android/baklava/images/gsi/{GSI_ARCHIVE_NAME}"
GSI_SHA256 = "2171cf0ea849f8eaa399f4bad2165fab80b0fd9e98d37723a705dca6c41e49ea"
MOTOROLA_SOFTWARE_FIX_URL = "https://en-us.support.motorola.com/app/softwarefix"
MOTOROLA_BOOTLOADER_SUPPORT_URL = "https://en-us.support.motorola.com/app/answers/detail/a_id/89973"

FORBIDDEN_DESTRUCTIVE_TERMS = (
    "fastboot flashing unlock",
    "fastboot oem unlock",
    "fastboot flash",
    "fastboot erase",
    "fastboot wipe",
    "fastboot reboot bootloader",
    "fastboot reboot fastboot",
    "fastboot boot",
    "adb reboot bootloader",
    "adb reboot fastboot",
)
ALLOWED_COMMAND_PREFIXES = (
    ".venv/bin/python scripts/rom_feasibility_probe.py ",
    ".venv/bin/python scripts/create_rom_stock_restore_evidence.py ",
    ".venv/bin/python scripts/create_rom_gsi_candidate_evidence.py ",
    ".venv/bin/python scripts/create_rom_bootloader_visibility_guide.py",
    ".venv/bin/python scripts/create_rom_fastboot_evidence.py",
    ".venv/bin/python scripts/create_rom_unlock_eligibility_evidence.py ",
    ".venv/bin/python scripts/create_rom_manual_gates_template.py ",
    ".venv/bin/python scripts/validate_rom_manual_gates.py ",
    ".venv/bin/python scripts/verify_rom0_readiness.py ",
)


class PacketStatus(StrEnum):
    BLOCKED_MANUAL_EVIDENCE = "BLOCKED_MANUAL_EVIDENCE"
    READY_FOR_MANUAL_GATE_TEMPLATE = "READY_FOR_MANUAL_GATE_TEMPLATE"
    READY_FOR_ROM0_READINESS_REVIEW = "READY_FOR_ROM0_READINESS_REVIEW"


class ActionStatus(StrEnum):
    READY = "READY"
    REQUIRED = "REQUIRED"
    RECORDED = "RECORDED"
    BLOCKED = "BLOCKED"


class ActionKind(StrEnum):
    LOCAL_READ_ONLY = "LOCAL_READ_ONLY"
    HUMAN_ONLY = "HUMAN_ONLY"
    TEMPLATE_ONLY = "TEMPLATE_ONLY"


@dataclass(frozen=True)
class ManualAction:
    action_id: str
    title: str
    kind: ActionKind
    status: ActionStatus
    summary: str
    instructions: tuple[str, ...]
    safe_commands: tuple[str, ...] = ()
    evidence_output: str = ""
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rom0ManualActionPacket:
    schema_version: str
    generated_at: str
    status: PacketStatus
    destructive_actions: str
    device: dict[str, str]
    blocked_by: tuple[str, ...]
    actions: tuple[ManualAction, ...]
    reuse_decision: str


def load_probe_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ROM probe JSON must be an object")
    schema = payload.get("schema_version")
    if schema != PROBE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported ROM probe schema {schema!r}; expected {PROBE_SCHEMA_VERSION}"
        )
    return payload


def build_packet(
    probe: Mapping[str, Any],
    *,
    unlock_eligibility: Mapping[str, Any] | None = None,
    stock_restore: Mapping[str, str] | None = None,
    gsi_candidate: Mapping[str, str] | None = None,
    fastboot_evidence: Mapping[str, str] | None = None,
) -> Rom0ManualActionPacket:
    device = compact_device(probe)
    probe_generated_at = str(probe.get("generated_at", ""))
    probe_blockers = probe_readiness_blockers(probe)
    unlock_ready = unlock_evidence_ready(
        unlock_eligibility,
        target_device=device,
        probe_generated_at=probe_generated_at,
    )
    stock_ready = stock_restore is not None
    gsi_ready = gsi_evidence_ready(gsi_candidate)
    fastboot_ready = fastboot_evidence_ready(fastboot_evidence)

    blocked_by = blocked_reasons(
        probe_blockers=probe_blockers,
        unlock_ready=unlock_ready,
        stock_ready=stock_ready,
        gsi_ready=gsi_ready,
        fastboot_ready=fastboot_ready,
    )
    actions = (
        read_only_probe_action(),
        fastboot_evidence_action(fastboot_evidence),
        stock_restore_action(stock_restore),
        gsi_candidate_action(gsi_candidate),
        unlock_eligibility_action(
            unlock_eligibility,
            target_device=device,
            probe_generated_at=probe_generated_at,
        ),
        manual_gate_template_action(unlock_ready=unlock_ready, stock_ready=stock_ready),
        readiness_report_action(
            probe_blockers=probe_blockers,
            unlock_ready=unlock_ready,
            stock_ready=stock_ready,
            gsi_ready=gsi_ready,
            fastboot_ready=fastboot_ready,
        ),
    )
    ready_for_manual_gates = unlock_ready and stock_ready
    ready_for_readiness = (
        not probe_blockers and ready_for_manual_gates and gsi_ready and fastboot_ready
    )
    packet = Rom0ManualActionPacket(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        status=packet_status(
            ready_for_manual_gates=ready_for_manual_gates,
            ready_for_readiness=ready_for_readiness,
        ),
        destructive_actions="withheld",
        device=device,
        blocked_by=blocked_by,
        actions=actions,
        reuse_decision=(
            "Do not import generic bootloader-unlock scripts or ROM flashing guides; "
            "reuse GOFFY's typed evidence validators and official Motorola/Android "
            "manual gates until exact-device safety is proven."
        ),
    )
    assert_no_destructive_authority(packet)
    return packet


def read_only_probe_action() -> ManualAction:
    return ManualAction(
        action_id="refresh_read_only_probe",
        title="Refresh the read-only ROM feasibility probe",
        kind=ActionKind.LOCAL_READ_ONLY,
        status=ActionStatus.READY,
        summary=(
            "Collect current locked/Treble/DSU state without rebooting or writing to the phone."
        ),
        instructions=(
            "Keep USB debugging visible and authorized.",
            "Run the probe again whenever the phone build, slot, or OEM-unlock state changes.",
            "The command redacts the device serial in rendered evidence.",
        ),
        safe_commands=(
            ".venv/bin/python scripts/rom_feasibility_probe.py "
            f"--device-serial {DEVICE_SERIAL_PLACEHOLDER} --json "
            "> .goffy-validation/rom-feasibility-current.json",
        ),
        evidence_output=".goffy-validation/rom-feasibility-current.json",
    )


def fastboot_evidence_action(fastboot_evidence: Mapping[str, str] | None) -> ManualAction:
    if fastboot_evidence_present(fastboot_evidence):
        if fastboot_evidence is None:
            raise ValueError("fastboot evidence presence predicate returned an invalid state")
        manual_visible = fastboot_evidence.get("bootloader_device_visible") == "true"
        return ManualAction(
            action_id="record_fastboot_evidence",
            title="Record read-only fastboot evidence",
            kind=ActionKind.LOCAL_READ_ONLY,
            status=ActionStatus.RECORDED,
            summary=(
                "Trusted host fastboot evidence exists"
                + (
                    " with manual bootloader visibility."
                    if manual_visible
                    else "; manual bootloader visibility is still pending."
                )
            ),
            instructions=(
                "Keep this as evidence only; it does not approve unlock, flash, erase, or boot.",
                "If the phone later enters bootloader mode manually, rerun the helper with "
                "--manual-bootloader-check.",
            ),
            evidence_output=".goffy-validation/rom-fastboot-evidence.json",
        )
    return ManualAction(
        action_id="record_fastboot_evidence",
        title="Record read-only fastboot evidence",
        kind=ActionKind.LOCAL_READ_ONLY,
        status=ActionStatus.REQUIRED,
        summary=("ROM-0 readiness now requires redacted host fastboot evidence before review."),
        instructions=(
            "Generate the bootloader visibility guide before touching the phone boot menu.",
            "Run the host readiness command first; it only checks the trusted SDK fastboot.",
            "Do not reboot the phone from ADB or fastboot.",
            "Only after the human manually enters bootloader mode, run the optional "
            "visibility check.",
            "Both commands write redacted evidence and never unlock, flash, erase, wipe, "
            "boot, or reboot.",
        ),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_bootloader_visibility_guide.py",
            ".venv/bin/python scripts/create_rom_fastboot_evidence.py",
            ".venv/bin/python scripts/create_rom_fastboot_evidence.py --manual-bootloader-check",
        ),
        evidence_output=".goffy-validation/rom-fastboot-evidence.json",
        blockers=("redacted read-only fastboot evidence is missing",),
    )


def stock_restore_action(stock_restore: Mapping[str, str] | None) -> ManualAction:
    if stock_restore is not None:
        return ManualAction(
            action_id="record_stock_restore",
            title="Record exact stock restore evidence",
            kind=ActionKind.HUMAN_ONLY,
            status=ActionStatus.RECORDED,
            summary="A redacted stock restore archive name and SHA-256 are already available.",
            instructions=(
                "Keep the stock archive outside the repo.",
                "Keep the rollback document synchronized with the exact archive name and SHA-256.",
            ),
            evidence_output=".goffy-validation/rom-stock-restore-evidence.json",
        )
    return ManualAction(
        action_id="record_stock_restore",
        title="Record exact stock restore evidence",
        kind=ActionKind.HUMAN_ONLY,
        status=ActionStatus.REQUIRED,
        summary="ROM-0 still needs a recoverable stock package before any unlock or boot work.",
        instructions=(
            "Use Motorola Software Fix on a supported computer to identify the "
            "exact restore package.",
            "Do not store IMEI, serial number, account identifiers, or the "
            "firmware archive in the repo.",
            "Create docs/setup/kansas-stock-rollback.md from the template before "
            "recording evidence.",
            "Record only source URL, archive filename, local SHA-256, and rollback-doc path.",
        ),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_stock_restore_evidence.py "
            f"--archive {STOCK_ARCHIVE_PLACEHOLDER} "
            f"--source-url {MOTOROLA_SOFTWARE_FIX_URL} "
            "--rollback-doc docs/setup/kansas-stock-rollback.md "
            "--output .goffy-validation/rom-stock-restore-evidence.json",
        ),
        evidence_output=".goffy-validation/rom-stock-restore-evidence.json",
        blockers=("exact stock restore archive and SHA-256 are missing",),
    )


def gsi_candidate_action(gsi_candidate: Mapping[str, str] | None) -> ManualAction:
    if gsi_evidence_ready(gsi_candidate):
        return ManualAction(
            action_id="record_gsi_candidate",
            title="Record official GSI candidate evidence",
            kind=ActionKind.HUMAN_ONLY,
            status=ActionStatus.RECORDED,
            summary="A non-authorizing official Google GSI checksum evidence record exists.",
            instructions=(
                "Keep the downloaded GSI archive outside the repo.",
                "Do not treat candidate evidence as approval to use DSU or modify the phone.",
                "Recreate evidence if Google publishes a newer selected GSI candidate.",
            ),
            evidence_output=".goffy-validation/rom-gsi-candidate-evidence.json",
        )
    return ManualAction(
        action_id="record_gsi_candidate",
        title="Record official GSI candidate evidence",
        kind=ActionKind.HUMAN_ONLY,
        status=ActionStatus.REQUIRED,
        summary=(
            "ROM-0 needs official Google ARM64 GSI checksum evidence before readiness review."
        ),
        instructions=(
            "Open the official Android GSI releases page and review the license terms yourself.",
            "Download the Android 16 ARM64 archive only after you personally accept those terms.",
            "Keep the downloaded GSI archive outside the GOFFY repo.",
            "Record only filename, official source URL, official download URL, size, and SHA-256.",
            "This evidence still does not authorize DSU, unlock, flash, erase, root, or reboot.",
        ),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_gsi_candidate_evidence.py "
            f"--artifact {GSI_ARCHIVE_PLACEHOLDER} "
            f"--source-url {OFFICIAL_GSI_RELEASES_URL} "
            f"--download-url {GSI_DOWNLOAD_URL} "
            f"--expected-sha256 {GSI_SHA256} "
            '--candidate-name "Official Google Android 16 ARM64 GSI" '
            "--android-release 16 "
            "--architecture arm64 "
            "--output .goffy-validation/rom-gsi-candidate-evidence.json",
        ),
        evidence_output=".goffy-validation/rom-gsi-candidate-evidence.json",
        blockers=("official Google ARM64 GSI evidence is missing",),
    )


def unlock_eligibility_action(
    unlock_eligibility: Mapping[str, Any] | None,
    *,
    target_device: Mapping[str, str],
    probe_generated_at: str,
) -> ManualAction:
    if unlock_evidence_ready(
        unlock_eligibility,
        target_device=target_device,
        probe_generated_at=probe_generated_at,
    ):
        return ManualAction(
            action_id="record_unlock_eligibility",
            title="Record OEM or Motorola unlock eligibility",
            kind=ActionKind.HUMAN_ONLY,
            status=ActionStatus.RECORDED,
            summary="Redacted OEM toggle and Motorola eligibility evidence is available.",
            instructions=(
                "Do not store unlock data, IMEI, serial number, account data, or tokens.",
                "This evidence still does not approve bootloader unlocking.",
            ),
            evidence_output=".goffy-validation/rom-unlock-eligibility-evidence.json",
        )
    return ManualAction(
        action_id="record_unlock_eligibility",
        title="Record OEM or Motorola unlock eligibility",
        kind=ActionKind.HUMAN_ONLY,
        status=ActionStatus.REQUIRED,
        summary="The exact phone must prove OEM unlocking and Motorola eligibility manually.",
        instructions=(
            "Check Settings > Developer options > OEM unlocking on the phone.",
            "Use Motorola's official bootloader support flow to determine eligibility.",
            "Do not paste or save raw unlock data, IMEI, serial number, account data, or tokens.",
            "Record only visible/enabled booleans plus eligible/not_eligible/unknown.",
        ),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_unlock_eligibility_evidence.py "
            "--oem-unlocking-visible yes "
            "--oem-unlocking-enabled yes "
            "--probe-json .goffy-validation/rom-feasibility-current.json "
            "--motorola-eligibility eligible "
            "--operator-note-code checked_no_identifiers_stored "
            "--output .goffy-validation/rom-unlock-eligibility-evidence.json",
        ),
        evidence_output=".goffy-validation/rom-unlock-eligibility-evidence.json",
        blockers=("manual OEM unlock toggle and Motorola eligibility evidence are missing",),
    )


def manual_gate_template_action(*, unlock_ready: bool, stock_ready: bool) -> ManualAction:
    ready = unlock_ready and stock_ready
    return ManualAction(
        action_id="create_manual_gates",
        title="Create ROM-0 manual-gates JSON",
        kind=ActionKind.TEMPLATE_ONLY,
        status=ActionStatus.READY if ready else ActionStatus.BLOCKED,
        summary=(
            "Merge redacted restore/unlock evidence into the fail-closed manual-gates template."
        ),
        instructions=(
            "Set backup_confirmed only after the user confirms a complete data backup.",
            "Leave destructive_approval as not_requested until the user explicitly "
            "approves that step.",
            "Keep the target_device values seeded from the read-only ROM probe.",
            "Validate the generated JSON before treating it as review-ready.",
        ),
        safe_commands=(
            ".venv/bin/python scripts/create_rom_manual_gates_template.py "
            "--probe-json .goffy-validation/rom-feasibility-current.json "
            "--unlock-eligibility-evidence .goffy-validation/rom-unlock-eligibility-evidence.json "
            "--stock-restore-evidence .goffy-validation/rom-stock-restore-evidence.json "
            "--output .goffy-validation/rom-0-manual-gates.json",
            ".venv/bin/python scripts/validate_rom_manual_gates.py "
            ".goffy-validation/rom-0-manual-gates.json "
            "--probe-json .goffy-validation/rom-feasibility-current.json",
        ),
        evidence_output=".goffy-validation/rom-0-manual-gates.json",
        blockers=()
        if ready
        else ("stock restore and unlock eligibility evidence must both exist first",),
    )


def readiness_report_action(
    *,
    probe_blockers: tuple[str, ...],
    unlock_ready: bool,
    stock_ready: bool,
    gsi_ready: bool,
    fastboot_ready: bool,
) -> ManualAction:
    blockers = readiness_report_blockers(
        probe_blockers=probe_blockers,
        unlock_ready=unlock_ready,
        stock_ready=stock_ready,
        gsi_ready=gsi_ready,
        fastboot_ready=fastboot_ready,
    )
    ready = not blockers
    return ManualAction(
        action_id="summarize_rom0_readiness",
        title="Summarize ROM-0 readiness without mutation",
        kind=ActionKind.LOCAL_READ_ONLY,
        status=ActionStatus.READY if ready else ActionStatus.BLOCKED,
        summary="Render one blocked/ready-for-review report from the saved evidence.",
        instructions=(
            "A passing report means human review is ready; it does not authorize unlock or flash.",
            "Keep signed APK and AOSP import evidence separate from unlock eligibility evidence.",
        ),
        safe_commands=(
            ".venv/bin/python scripts/verify_rom0_readiness.py "
            "--probe-json .goffy-validation/rom-feasibility-current.json "
            "--manual-gates-json .goffy-validation/rom-0-manual-gates.json "
            "--fastboot-evidence-json .goffy-validation/rom-fastboot-evidence.json "
            "--gsi-candidate-evidence-json .goffy-validation/rom-gsi-candidate-evidence.json "
            "--signing-plan-json .goffy-validation/rom-signing/release-signing-plan.json "
            "--apk-verification-json .goffy-validation/rom-signing/release-apk-verification.json "
            "--signed-apk .goffy-validation/rom-signing/GoffyOS-signed.apk "
            "--aosp-root /path/to/aosp "
            "--evidence-root .",
        ),
        blockers=blockers,
    )


def unlock_evidence_ready(
    unlock_eligibility: Mapping[str, Any] | None,
    *,
    target_device: Mapping[str, str] | None = None,
    probe_generated_at: str = "",
) -> bool:
    if unlock_eligibility is None:
        return False
    base_ready = (
        unlock_eligibility.get("oem_unlocking_visible") is True
        and unlock_eligibility.get("oem_unlocking_enabled") is True
        and unlock_eligibility.get("motorola_unlock_eligibility") == "eligible"
    )
    if not base_ready:
        return False
    if target_device is None:
        return True
    return not unlock_evidence_probe_blockers(
        unlock_eligibility,
        target_device=target_device,
        probe_generated_at=probe_generated_at,
    )


def gsi_evidence_ready(gsi_candidate: Mapping[str, str] | None) -> bool:
    if gsi_candidate is None:
        return False
    return (
        gsi_candidate.get("status") == "ARTIFACT_CHECKSUM_VERIFIED"
        and gsi_candidate.get("authorization") == "NON_AUTHORIZING_EVIDENCE"
        and bool(gsi_candidate.get("artifact_name"))
        and bool(gsi_candidate.get("sha256"))
        and bool(gsi_candidate.get("source_url"))
    )


def fastboot_evidence_ready(fastboot_evidence: Mapping[str, str] | None) -> bool:
    if fastboot_evidence is None:
        return False
    return (
        fastboot_evidence.get("status") == "MANUAL_BOOTLOADER_VISIBLE"
        and bool(fastboot_evidence.get("fastboot_version"))
        and fastboot_evidence.get("manual_bootloader_check_requested") == "true"
        and fastboot_evidence.get("bootloader_device_visible") == "true"
        and int_value(fastboot_evidence.get("bootloader_device_count", "")) > 0
    )


def fastboot_evidence_present(fastboot_evidence: Mapping[str, str] | None) -> bool:
    if fastboot_evidence is None:
        return False
    return fastboot_evidence.get("status") in {"HOST_READY", "MANUAL_BOOTLOADER_VISIBLE"} and bool(
        fastboot_evidence.get("fastboot_version")
    )


def int_value(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def probe_readiness_blockers(probe: Mapping[str, Any]) -> tuple[str, ...]:
    blockers = list(string_items(probe.get("blockers")))
    device = mapping_value(probe.get("device"))
    boot = mapping_value(probe.get("boot"))
    treble = mapping_value(probe.get("treble"))
    properties = mapping_value(probe.get("properties"))
    if probe.get("ok") is not True and not blockers:
        append_unique(blockers, "ROM feasibility probe is not OK")
    if device.get("codename") != EXPECTED_CODENAME:
        append_unique(blockers, "ROM probe codename does not match kansas")
    if device.get("product") != EXPECTED_PRODUCT:
        append_unique(blockers, "ROM probe product does not match kansas_g_sys")
    if boot.get("flash_locked") != "0" or boot.get("vbmeta_device_state") != "unlocked":
        append_unique(blockers, "ROM probe does not show an unlocked bootloader")
    if treble.get("enabled") != "true":
        append_unique(blockers, "ROM probe does not show Treble enabled")
    if treble.get("dynamic_partitions") != "true":
        append_unique(blockers, "ROM probe does not show dynamic partitions")

    target_device = {
        "model": device.get("model", ""),
        "codename": device.get("codename", ""),
        "product": device.get("product", ""),
        "hardware_sku": device.get("hardware_sku", ""),
        "build_fingerprint": properties.get("ro.build.fingerprint", ""),
        "carrier": device.get("carrier", ""),
    }
    for key in TARGET_DEVICE_EVIDENCE_KEYS:
        if not target_device[key]:
            append_unique(blockers, f"ROM probe target_device.{key} is missing")
    return tuple(blockers)


def blocked_reasons(
    *,
    probe_blockers: tuple[str, ...],
    unlock_ready: bool,
    stock_ready: bool,
    gsi_ready: bool,
    fastboot_ready: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    reasons.extend(probe_blockers)
    if not unlock_ready:
        reasons.append(
            "manual OEM or Motorola unlock eligibility evidence is missing or not eligible"
        )
    if not stock_ready:
        reasons.append("exact stock restore evidence is missing")
    if not gsi_ready:
        reasons.append("official Google ARM64 GSI evidence is missing")
    if not fastboot_ready:
        reasons.append("manual bootloader-mode fastboot visibility evidence is missing")
    return tuple(reasons)


def readiness_report_blockers(
    *,
    probe_blockers: tuple[str, ...],
    unlock_ready: bool,
    stock_ready: bool,
    gsi_ready: bool,
    fastboot_ready: bool,
) -> tuple[str, ...]:
    blockers: list[str] = []
    blockers.extend(probe_blockers)
    if not unlock_ready or not stock_ready or not gsi_ready or not fastboot_ready:
        blockers.append(
            "readiness cannot be summarized until restore, unlock, fastboot, and GSI evidence exist"
        )
    return tuple(blockers)


def append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def packet_status(
    *,
    ready_for_manual_gates: bool,
    ready_for_readiness: bool,
) -> PacketStatus:
    if ready_for_readiness:
        return PacketStatus.READY_FOR_ROM0_READINESS_REVIEW
    if ready_for_manual_gates:
        return PacketStatus.READY_FOR_MANUAL_GATE_TEMPLATE
    return PacketStatus.BLOCKED_MANUAL_EVIDENCE


def load_gsi_candidate_evidence(path: Path) -> dict[str, str]:
    section = validate_gsi_candidate_evidence(path)
    if not section.ok:
        raise ValueError("; ".join(section.blockers))
    if section.evidence is None:
        raise ValueError("GSI candidate evidence did not include accepted evidence")
    return section.evidence


def load_fastboot_evidence(path: Path) -> dict[str, str]:
    section = validate_fastboot_evidence(path)
    if not section.ok:
        raise ValueError("; ".join(section.blockers))
    if section.evidence is None:
        raise ValueError("fastboot evidence did not include accepted evidence")
    return section.evidence


def compact_device(probe: Mapping[str, Any]) -> dict[str, str]:
    device = mapping_value(probe.get("device"))
    platform = mapping_value(probe.get("platform"))
    boot = mapping_value(probe.get("boot"))
    treble = mapping_value(probe.get("treble"))
    dsu = mapping_value(probe.get("dsu"))
    properties = mapping_value(probe.get("properties"))
    return {
        "model": device.get("model", ""),
        "codename": device.get("codename", ""),
        "product": device.get("product", ""),
        "carrier": device.get("carrier", ""),
        "hardware_sku": device.get("hardware_sku", ""),
        "build_fingerprint": properties.get("ro.build.fingerprint", ""),
        "soc_model": platform.get("soc_model", ""),
        "android_release": platform.get("android_release", ""),
        "flash_locked": boot.get("flash_locked", ""),
        "vbmeta_device_state": boot.get("vbmeta_device_state", ""),
        "treble_enabled": treble.get("enabled", ""),
        "dynamic_partitions": treble.get("dynamic_partitions", ""),
        "dsu_package_installed": dsu_package_present(dsu),
    }


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def dsu_package_present(dsu: Mapping[str, str]) -> str:
    return dsu.get("package_present") or dsu.get("package_installed", "")


def assert_no_destructive_authority(packet: Rom0ManualActionPacket) -> None:
    rendered = json.dumps(asdict(packet)).lower()
    forbidden = [term for term in FORBIDDEN_DESTRUCTIVE_TERMS if term in rendered]
    if forbidden:
        raise ValueError(
            f"manual action packet contains destructive command authority: {forbidden}"
        )
    unsupported_commands = [
        command
        for action in packet.actions
        for command in action.safe_commands
        if not command_allowed(command)
    ]
    if unsupported_commands:
        raise ValueError(
            f"manual action packet contains unsupported command(s): {unsupported_commands}"
        )


def command_allowed(command: str) -> bool:
    return command.startswith(ALLOWED_COMMAND_PREFIXES)


def render_json(packet: Rom0ManualActionPacket) -> str:
    return json.dumps(asdict(packet), indent=2) + "\n"


def render_markdown(packet: Rom0ManualActionPacket) -> str:
    lines = [
        "# GOFFY ROM-0 Manual Action Packet",
        "",
        f"- Status: `{packet.status}`",
        f"- Destructive actions: `{packet.destructive_actions}`",
        f"- Reuse decision: {packet.reuse_decision}",
        "",
        "## Device Snapshot",
    ]
    for key, value in packet.device.items():
        lines.append(f"- {key}: `{value or 'missing'}`")
    if packet.blocked_by:
        lines.extend(("", "## Blocking Evidence"))
        lines.extend(f"- {item}" for item in packet.blocked_by)
    lines.extend(("", "## Actions"))
    for action in packet.actions:
        lines.extend(
            (
                "",
                f"### {action.title}",
                f"- ID: `{action.action_id}`",
                f"- Kind: `{action.kind}`",
                f"- Status: `{action.status}`",
                f"- Summary: {action.summary}",
            )
        )
        lines.append("- Instructions:")
        lines.extend(f"  - {item}" for item in action.instructions)
        if action.safe_commands:
            lines.append("- Safe commands:")
            lines.extend(f"  - `{command}`" for command in action.safe_commands)
        if action.evidence_output:
            lines.append(f"- Evidence output: `{action.evidence_output}`")
        if action.blockers:
            lines.append("- Blockers:")
            lines.extend(f"  - {item}" for item in action.blockers)
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a non-destructive GOFFY ROM-0 manual action packet from saved evidence."
        ),
    )
    parser.add_argument("probe_json", type=Path)
    parser.add_argument("--unlock-eligibility-evidence", type=Path)
    parser.add_argument("--stock-restore-evidence", type=Path)
    parser.add_argument("--fastboot-evidence", type=Path)
    parser.add_argument("--gsi-candidate-evidence", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path under .goffy-validation; stdout is used when omitted.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        unlock = (
            load_unlock_eligibility_evidence(args.unlock_eligibility_evidence)
            if args.unlock_eligibility_evidence
            else None
        )
        stock = (
            load_stock_restore_evidence(args.stock_restore_evidence)
            if args.stock_restore_evidence
            else None
        )
        gsi_candidate = (
            load_gsi_candidate_evidence(args.gsi_candidate_evidence)
            if args.gsi_candidate_evidence
            else None
        )
        fastboot_evidence = (
            load_fastboot_evidence(args.fastboot_evidence) if args.fastboot_evidence else None
        )
        packet = build_packet(
            load_probe_json(args.probe_json),
            unlock_eligibility=unlock,
            stock_restore=stock,
            gsi_candidate=gsi_candidate,
            fastboot_evidence=fastboot_evidence,
        )
        text = render_json(packet) if args.json else render_markdown(packet)
        if args.output is None:
            print(text, end="")
        else:
            write_output(args.output, text)
            print(f"wrote ROM-0 manual action packet to {args.output}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
