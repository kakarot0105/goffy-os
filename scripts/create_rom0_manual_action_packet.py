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

from scripts.create_rom_manual_gates_template import load_stock_restore_evidence  # noqa: E402
from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402
from scripts.create_rom_unlock_eligibility_evidence import (  # noqa: E402
    load_unlock_eligibility_evidence,
)
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.rom0-manual-action-packet.v1"
DEVICE_SERIAL_PLACEHOLDER = "<device-serial>"
STOCK_ARCHIVE_PLACEHOLDER = "/absolute/path/outside/repo/<exact-kansas-stock-archive.zip>"
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
    ".venv/bin/python scripts/create_rom_unlock_eligibility_evidence.py ",
    ".venv/bin/python scripts/create_rom_manual_gates_template.py ",
    ".venv/bin/python scripts/validate_rom_manual_gates.py ",
    ".venv/bin/python scripts/verify_rom0_readiness.py ",
)


class PacketStatus(StrEnum):
    BLOCKED_MANUAL_EVIDENCE = "BLOCKED_MANUAL_EVIDENCE"
    READY_FOR_MANUAL_GATE_TEMPLATE = "READY_FOR_MANUAL_GATE_TEMPLATE"


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
) -> Rom0ManualActionPacket:
    device = compact_device(probe)
    unlock_ready = unlock_evidence_ready(unlock_eligibility)
    stock_ready = stock_restore is not None

    blocked_by = blocked_reasons(
        unlock_ready=unlock_ready,
        stock_ready=stock_ready,
    )
    actions = (
        read_only_probe_action(),
        stock_restore_action(stock_restore),
        unlock_eligibility_action(unlock_eligibility),
        manual_gate_template_action(unlock_ready=unlock_ready, stock_ready=stock_ready),
        readiness_report_action(unlock_ready=unlock_ready, stock_ready=stock_ready),
    )
    packet = Rom0ManualActionPacket(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        status=PacketStatus.READY_FOR_MANUAL_GATE_TEMPLATE
        if unlock_ready and stock_ready
        else PacketStatus.BLOCKED_MANUAL_EVIDENCE,
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


def unlock_eligibility_action(unlock_eligibility: Mapping[str, Any] | None) -> ManualAction:
    if unlock_evidence_ready(unlock_eligibility):
        return ManualAction(
            action_id="record_unlock_eligibility",
            title="Record OEM/Motorola unlock eligibility",
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
        title="Record OEM/Motorola unlock eligibility",
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


def readiness_report_action(*, unlock_ready: bool, stock_ready: bool) -> ManualAction:
    ready = unlock_ready and stock_ready
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
            "--signing-plan-json .goffy-validation/rom-signing/release-signing-plan.json "
            "--apk-verification-json .goffy-validation/rom-signing/release-apk-verification.json "
            "--signed-apk .goffy-validation/rom-signing/GoffyOS-signed.apk "
            "--aosp-root /path/to/aosp "
            "--evidence-root .",
        ),
        blockers=()
        if ready
        else ("manual gates cannot be summarized until restore and unlock evidence exist",),
    )


def unlock_evidence_ready(unlock_eligibility: Mapping[str, Any] | None) -> bool:
    if unlock_eligibility is None:
        return False
    return (
        unlock_eligibility.get("oem_unlocking_visible") is True
        and unlock_eligibility.get("oem_unlocking_enabled") is True
        and unlock_eligibility.get("motorola_unlock_eligibility") == "eligible"
    )


def blocked_reasons(*, unlock_ready: bool, stock_ready: bool) -> tuple[str, ...]:
    reasons: list[str] = []
    if not unlock_ready:
        reasons.append("manual OEM/Motorola unlock eligibility evidence is missing or not eligible")
    if not stock_ready:
        reasons.append("exact stock restore evidence is missing")
    return tuple(reasons)


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
        packet = build_packet(
            load_probe_json(args.probe_json),
            unlock_eligibility=unlock,
            stock_restore=stock,
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
