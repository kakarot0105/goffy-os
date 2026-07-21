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

JSON_SCHEMA_VERSION = "goffy.rom-planning-checklist.v1"
SUPPORTED_PROBE_SCHEMA = "goffy.rom-feasibility-probe.v1"
DEVICE_SERIAL_PLACEHOLDER = "<device-serial>"
GSI_IMAGE_PLACEHOLDER = "<gsi-system-raw.img>"
GSI_ARCHIVE_PLACEHOLDER = "<gsi-system-raw.gz>"


class DryRunStatus(StrEnum):
    BLOCKED_LOCKED_BOOTLOADER = "BLOCKED_LOCKED_BOOTLOADER"
    BLOCKED_RESTORE_NOT_READY = "BLOCKED_RESTORE_NOT_READY"
    READY_FOR_APPROVAL_GATED_DSU_STAGING = "READY_FOR_APPROVAL_GATED_DSU_STAGING"


@dataclass(frozen=True)
class SourceCandidate:
    name: str
    trust_level: str
    url: str
    use: str
    risk: str


@dataclass(frozen=True)
class GsiCandidate:
    name: str
    priority: int
    source: str
    license_note: str
    use: str
    risk: str


@dataclass(frozen=True)
class ChecklistStep:
    phase: str
    status: str
    action: str
    command: tuple[str, ...] = ()
    mutates_device: bool = False
    requires_user_approval: bool = False
    rationale: str = ""


@dataclass(frozen=True)
class RomDryRunChecklist:
    schema_version: str
    generated_at: str
    status: DryRunStatus
    device: dict[str, str]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    restore_sources: tuple[SourceCandidate, ...]
    gsi_candidates: tuple[GsiCandidate, ...]
    steps: tuple[ChecklistStep, ...]


RESTORE_SOURCES = (
    SourceCandidate(
        name="Motorola Software Fix Rescue",
        trust_level="official",
        url="https://en-us.support.motorola.com/app/softwarefix",
        use=(
            "Primary stock restore route. Use it to confirm Motorola can match and download "
            "the exact signed restore package for this phone before any bootloader work."
        ),
        risk="Windows PC flow; rescue restores factory defaults and removes personal data.",
    ),
    SourceCandidate(
        name="Motorola Rescue Software Update guide",
        trust_level="official",
        url="https://en-us.support.motorola.com/app/answers/detail/a_id/167770",
        use="Operational restore checklist for Motorola Software Fix.",
        risk="Requires IMEI matching and a large firmware download.",
    ),
    SourceCandidate(
        name="Lolinet Lenomola Kansas mirror",
        trust_level="unofficial mirror",
        url="https://mirrors.lolinet.com/firmware/lenomola/2025/kansas/official/RETUS/",
        use=(
            "Secondary evidence source for Kansas firmware names only. Do not treat as trusted "
            "unless the archive matches the device variant and is hash-recorded."
        ),
        risk="Mirror provenance is not equivalent to Motorola's official rescue flow.",
    ),
)

GSI_CANDIDATES = (
    GsiCandidate(
        name="Google Android 16 GSI via DSU Loader",
        priority=1,
        source="https://developer.android.com/topic/generic-system-image/releases",
        license_note=(
            "Use under Google's per-download GSI license terms; do not redistribute. "
            "Record the official SHA-256 before any boot attempt."
        ),
        use="First boot candidate because it is the official ARM64 Android GSI source.",
        risk=(
            "Validated by Google on Pixel devices, not specifically on Moto Kansas "
            "or MediaTek MT6835."
        ),
    ),
    GsiCandidate(
        name="TrebleDroid / ponces AOSP GSI",
        priority=2,
        source="https://github.com/ponces/treble_aosp",
        license_note="Apache-2.0 repo license; verify release artifact licenses before reuse.",
        use="Second candidate if the official Google GSI cannot exercise enough hardware.",
        risk=(
            "Community GSI; releases document known device-specific issues such as networking gaps."
        ),
    ),
    GsiCandidate(
        name="DSU Sideloader",
        priority=3,
        source="https://github.com/VegaBobo/DSU-Sideloader",
        license_note="Apache-2.0.",
        use="Helper app only if built-in DSU Loader is unavailable or too limited.",
        risk=(
            "Requires an unlocked bootloader, dynamic partitions, a local GSI file, "
            "and storage access."
        ),
    ),
)


def load_probe_json(path: Path) -> dict[str, Any]:
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("probe JSON must be an object")
    schema = payload.get("schema_version")
    if schema != SUPPORTED_PROBE_SCHEMA:
        raise ValueError(f"unsupported probe schema {schema!r}; expected {SUPPORTED_PROBE_SCHEMA}")
    return payload


def build_checklist(
    probe: Mapping[str, Any],
) -> RomDryRunChecklist:
    generated_at = datetime.now(UTC).isoformat()
    device = compact_device(probe)
    probe_blockers = tuple(str(item) for item in probe.get("blockers", ()) if str(item))
    probe_warnings = tuple(str(item) for item in probe.get("warnings", ()) if str(item))
    boot = mapping_value(probe.get("boot"))
    treble = mapping_value(probe.get("treble"))
    stock_restore = mapping_value(probe.get("stock_restore"))

    bootloader_locked = (
        boot.get("flash_locked") == "1" or boot.get("vbmeta_device_state") == "locked"
    )
    treble_ready = treble.get("enabled") == "true" and treble.get("dynamic_partitions") == "true"
    has_restore_evidence = has_stock_restore_evidence(stock_restore)

    blockers: list[str] = list(probe_blockers)
    warnings: list[str] = list(probe_warnings)
    steps: list[ChecklistStep] = [
        ChecklistStep(
            phase="observe",
            status="OK",
            action="Parse read-only ROM feasibility probe JSON.",
            rationale=(
                "The planning checklist must be derived from observed phone state, not guesses."
            ),
        )
    ]

    if bootloader_locked:
        status = DryRunStatus.BLOCKED_LOCKED_BOOTLOADER
        append_locked_bootloader_steps(steps)
    elif not has_restore_evidence:
        status = DryRunStatus.BLOCKED_RESTORE_NOT_READY
        blockers.append(
            "structured stock restore evidence is missing: source_url, archive_name, "
            "sha256, and rollback_doc"
        )
        append_restore_steps(steps)
    elif treble_ready:
        status = DryRunStatus.READY_FOR_APPROVAL_GATED_DSU_STAGING
        append_dsu_staging_steps(steps)
    else:
        status = DryRunStatus.BLOCKED_RESTORE_NOT_READY
        blockers.append("Treble and dynamic partitions are not both confirmed")
        append_restore_steps(steps)

    steps.append(
        ChecklistStep(
            phase="authorize",
            status="BLOCKED",
            action="Withhold all unlock, flash, erase, root, and boot-image patch commands.",
            requires_user_approval=True,
            rationale=(
                "Destructive ROM work requires explicit user approval after backup and rollback."
            ),
        )
    )

    return RomDryRunChecklist(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=generated_at,
        status=status,
        device=device,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        restore_sources=RESTORE_SOURCES,
        gsi_candidates=GSI_CANDIDATES,
        steps=tuple(steps),
    )


def compact_device(probe: Mapping[str, Any]) -> dict[str, str]:
    device = mapping_value(probe.get("device"))
    platform = mapping_value(probe.get("platform"))
    boot = mapping_value(probe.get("boot"))
    treble = mapping_value(probe.get("treble"))
    return {
        "model": device.get("model", ""),
        "codename": device.get("codename", ""),
        "product": device.get("product", ""),
        "carrier": device.get("carrier", ""),
        "soc": platform.get("soc_model", ""),
        "android_release": platform.get("android_release", ""),
        "sdk": platform.get("sdk", ""),
        "bootloader": boot.get("vbmeta_device_state", ""),
        "treble": treble.get("enabled", ""),
        "dynamic_partitions": treble.get("dynamic_partitions", ""),
    }


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def has_stock_restore_evidence(stock_restore: Mapping[str, str]) -> bool:
    return all(
        bool(stock_restore.get(key))
        for key in ("source_url", "archive_name", "sha256", "rollback_doc")
    )


def append_locked_bootloader_steps(steps: list[ChecklistStep]) -> None:
    steps.extend(
        (
            ChecklistStep(
                phase="restore",
                status="TODO_MANUAL",
                action=(
                    "Run Motorola Software Fix far enough to verify this unit has "
                    "a restore package."
                ),
                requires_user_approval=True,
                rationale="The official restore path must exist before any bootloader experiment.",
            ),
            ChecklistStep(
                phase="unlock eligibility",
                status="TODO_MANUAL",
                action=(
                    "Check Developer options for OEM unlocking, then use Motorola's official "
                    "bootloader eligibility flow for this exact unit."
                ),
                requires_user_approval=True,
                rationale=(
                    "Carrier-exclusive devices can be restricted even when the model is recent."
                ),
            ),
        )
    )


def append_restore_steps(steps: list[ChecklistStep]) -> None:
    steps.extend(
        (
            ChecklistStep(
                phase="restore",
                status="TODO_MANUAL",
                action="Download or locate the exact stock firmware package and record SHA-256.",
                requires_user_approval=True,
                rationale="Rollback must be possible before DSU/GSI or unlock work.",
            ),
            ChecklistStep(
                phase="restore",
                status="TODO_MANUAL",
                action="Document the restore procedure and the exact firmware build it returns.",
                requires_user_approval=True,
                rationale=(
                    "A mismatch between installed build and restore package can strand the device."
                ),
            ),
        )
    )


def append_dsu_staging_steps(steps: list[ChecklistStep]) -> None:
    steps.extend(
        (
            ChecklistStep(
                phase="prepare",
                status="TEMPLATE_ONLY",
                action="Compress an unsparsed GSI image for DSU.",
                command=("gzip", "-c", GSI_IMAGE_PLACEHOLDER, ">", GSI_ARCHIVE_PLACEHOLDER),
                rationale="Android's command-line DSU flow expects a gzip archive.",
            ),
            ChecklistStep(
                phase="prepare",
                status="TEMPLATE_ONLY",
                action="Copy the GSI archive to the phone downloads directory.",
                command=(
                    "adb",
                    "-s",
                    DEVICE_SERIAL_PLACEHOLDER,
                    "push",
                    GSI_ARCHIVE_PLACEHOLDER,
                    "/storage/emulated/0/Download/",
                ),
                mutates_device=True,
                requires_user_approval=True,
                rationale="This writes a temporary archive but does not flash partitions.",
            ),
            ChecklistStep(
                phase="dsu",
                status="TEMPLATE_ONLY",
                action="Launch Android DSU verification UI for the selected GSI.",
                command=(
                    "adb",
                    "-s",
                    DEVICE_SERIAL_PLACEHOLDER,
                    "shell",
                    "am",
                    "start-activity",
                    "-n",
                    "com.android.dynsystem/com.android.dynsystem.VerificationActivity",
                    "-a",
                    "android.os.image.action.START_INSTALL",
                    "-d",
                    "file:///storage/emulated/0/Download/" + GSI_ARCHIVE_PLACEHOLDER,
                    "--el",
                    "KEY_SYSTEM_SIZE",
                    "<system-image-byte-size>",
                    "--el",
                    "KEY_USERDATA_SIZE",
                    "8589934592",
                ),
                mutates_device=True,
                requires_user_approval=True,
                rationale=(
                    "This opens DSU install UI; the user must confirm or discard from Android UI."
                ),
            ),
        )
    )


def render_markdown(checklist: RomDryRunChecklist) -> str:
    lines = [
        "# GOFFY ROM-0 Planning Checklist",
        "",
        f"- Schema: `{checklist.schema_version}`",
        f"- Status: `{checklist.status}`",
        "- Destructive commands: withheld",
        "",
        "## Device",
    ]
    for key, value in checklist.device.items():
        lines.append(f"- {key}: `{value or 'unknown'}`")
    if checklist.blockers:
        lines.extend(("", "## Blockers"))
        lines.extend(f"- {blocker}" for blocker in checklist.blockers)
    if checklist.warnings:
        lines.extend(("", "## Warnings"))
        lines.extend(f"- {warning}" for warning in checklist.warnings)

    lines.extend(("", "## Restore Sources"))
    for source in checklist.restore_sources:
        lines.append(f"- {source.name} ({source.trust_level}): {source.url}")
        lines.append(f"  Use: {source.use}")
        lines.append(f"  Risk: {source.risk}")

    lines.extend(("", "## GSI Candidates"))
    for candidate in sorted(checklist.gsi_candidates, key=lambda item: item.priority):
        lines.append(f"- {candidate.priority}. {candidate.name}: {candidate.source}")
        lines.append(f"  License: {candidate.license_note}")
        lines.append(f"  Use: {candidate.use}")
        lines.append(f"  Risk: {candidate.risk}")

    lines.extend(("", "## Checklist"))
    for step in checklist.steps:
        lines.append(f"- [{step.status}] {step.phase}: {step.action}")
        if step.command:
            lines.append(f"  Command template: `{format_command(step.command)}`")
        if step.mutates_device:
            lines.append("  Mutates device: yes, requires explicit approval")
        if step.rationale:
            lines.append(f"  Rationale: {step.rationale}")
    lines.append("")
    return "\n".join(lines)


def format_command(command: Sequence[str]) -> str:
    return " ".join(command)


def render_json(checklist: RomDryRunChecklist) -> str:
    return json.dumps(asdict(checklist), indent=2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a ROM-0 planning checklist from a GOFFY ROM probe JSON.",
    )
    parser.add_argument("probe_json", type=Path, help="Probe JSON path, or '-' for stdin.")
    parser.add_argument(
        "--json", action="store_true", help="Emit structured JSON instead of Markdown."
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        probe = load_probe_json(args.probe_json)
        checklist = build_checklist(probe)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(render_json(checklist) if args.json else render_markdown(checklist))
    return 0 if checklist.status is DryRunStatus.READY_FOR_APPROVAL_GATED_DSU_STAGING else 1


if __name__ == "__main__":
    raise SystemExit(main())
