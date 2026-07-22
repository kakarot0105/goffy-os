from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.rom_feasibility_probe as rom_probe  # noqa: E402
from scripts.create_rom0_manual_action_packet import (  # noqa: E402
    PacketStatus,
    build_packet,
    load_fastboot_evidence,
    load_gsi_candidate_evidence,
)
from scripts.create_rom0_manual_action_packet import render_json as render_packet_json  # noqa: E402
from scripts.create_rom0_manual_action_packet import (  # noqa: E402
    render_markdown as render_packet_markdown,
)
from scripts.create_rom_manual_gates_template import load_stock_restore_evidence  # noqa: E402
from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402
from scripts.create_rom_unlock_eligibility_evidence import (  # noqa: E402
    load_unlock_eligibility_evidence,
)
from scripts.run_moto_g_device_smoke import (  # noqa: E402
    CommandRunner,
    default_command_runner,
)

JSON_SCHEMA_VERSION = "goffy.rom0-refresh-report.v1"
VALIDATION_DIR = Path(".goffy-validation")
PROBE_FILENAME = "rom-feasibility-current.json"
PACKET_MARKDOWN_FILENAME = "rom-0-manual-action-packet.md"
PACKET_JSON_FILENAME = "rom-0-manual-action-packet.json"
REFRESH_REPORT_FILENAME = "rom-0-refresh-report.json"
UNLOCK_EVIDENCE_FILENAME = "rom-unlock-eligibility-evidence.json"
STOCK_EVIDENCE_FILENAME = "rom-stock-restore-evidence.json"
GSI_EVIDENCE_FILENAME = "rom-gsi-candidate-evidence.json"
FASTBOOT_EVIDENCE_FILENAME = "rom-fastboot-evidence.json"


class EvidenceStatus(StrEnum):
    LOADED = "LOADED"
    MISSING = "MISSING"
    INVALID = "INVALID"


class RefreshStatus(StrEnum):
    READY_FOR_ROM0_READINESS_REVIEW = "READY_FOR_ROM0_READINESS_REVIEW"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class EvidenceInput:
    name: str
    path: str
    status: EvidenceStatus
    detail: str


@dataclass(frozen=True)
class Rom0RefreshReport:
    schema_version: str
    generated_at: str
    ok: bool
    status: RefreshStatus
    refresh_succeeded: bool
    rom_ready: bool
    destructive_actions: str
    probe_json: str
    packet_markdown: str
    packet_json: str
    refresh_report_json: str
    packet_status: str
    blocked_by: tuple[str, ...]
    evidence_inputs: tuple[EvidenceInput, ...]
    errors: tuple[str, ...]


EvidenceLoader = Callable[[Path], Mapping[str, Any]]


def refresh_rom0_action_packet(
    *,
    root: Path = ROOT,
    validation_dir: Path = VALIDATION_DIR,
    device_serial: str | None = None,
    timeout_seconds: int = 30,
    runner: CommandRunner = default_command_runner,
) -> Rom0RefreshReport:
    validate_validation_dir(validation_dir, root=root)
    probe_report = rom_probe.build_report(
        root=root,
        device_serial=device_serial,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    paths = output_paths(validation_dir)
    write_validation_file(
        paths["probe_json"],
        rom_probe.render_json(probe_report) + "\n",
        root=root,
    )

    unlock, unlock_input = load_optional_evidence(
        "unlock_eligibility",
        paths["unlock_evidence"],
        load_unlock_eligibility_evidence,
        root=root,
    )
    stock, stock_input = load_optional_evidence(
        "stock_restore",
        paths["stock_evidence"],
        load_stock_restore_evidence,
        root=root,
    )
    gsi_candidate, gsi_input = load_optional_evidence(
        "gsi_candidate",
        paths["gsi_evidence"],
        load_gsi_candidate_evidence,
        root=root,
    )
    fastboot_evidence, fastboot_input = load_optional_evidence(
        "fastboot_evidence",
        paths["fastboot_evidence"],
        load_fastboot_evidence,
        root=root,
    )
    packet = build_packet(
        asdict(probe_report),
        unlock_eligibility=unlock,
        stock_restore=stock,
        gsi_candidate=gsi_candidate,
        fastboot_evidence=fastboot_evidence,
    )
    write_validation_file(
        paths["packet_markdown"],
        render_packet_markdown(packet),
        root=root,
    )
    write_validation_file(
        paths["packet_json"],
        render_packet_json(packet),
        root=root,
    )

    evidence_inputs = (unlock_input, stock_input, gsi_input, fastboot_input)
    errors = tuple(
        f"{item.name}: {item.detail}"
        for item in evidence_inputs
        if item.status is EvidenceStatus.INVALID
    )
    if not probe_report.device:
        errors = (*errors, "ROM feasibility probe did not capture a connected device")
    rom_ready = packet.status is PacketStatus.READY_FOR_ROM0_READINESS_REVIEW
    refresh_succeeded = not errors
    report = Rom0RefreshReport(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=refresh_succeeded and rom_ready,
        status=refresh_status(refresh_succeeded=refresh_succeeded, rom_ready=rom_ready),
        refresh_succeeded=refresh_succeeded,
        rom_ready=rom_ready,
        destructive_actions=packet.destructive_actions,
        probe_json=display_path(paths["probe_json"]),
        packet_markdown=display_path(paths["packet_markdown"]),
        packet_json=display_path(paths["packet_json"]),
        refresh_report_json=display_path(paths["refresh_report"]),
        packet_status=str(packet.status),
        blocked_by=packet.blocked_by,
        evidence_inputs=evidence_inputs,
        errors=errors,
    )
    write_validation_file(
        paths["refresh_report"],
        render_json(report),
        root=root,
    )
    return report


def output_paths(validation_dir: Path) -> dict[str, Path]:
    return {
        "probe_json": validation_dir / PROBE_FILENAME,
        "packet_markdown": validation_dir / PACKET_MARKDOWN_FILENAME,
        "packet_json": validation_dir / PACKET_JSON_FILENAME,
        "refresh_report": validation_dir / REFRESH_REPORT_FILENAME,
        "unlock_evidence": validation_dir / UNLOCK_EVIDENCE_FILENAME,
        "stock_evidence": validation_dir / STOCK_EVIDENCE_FILENAME,
        "gsi_evidence": validation_dir / GSI_EVIDENCE_FILENAME,
        "fastboot_evidence": validation_dir / FASTBOOT_EVIDENCE_FILENAME,
    }


def load_optional_evidence(
    name: str,
    path: Path,
    loader: EvidenceLoader,
    *,
    root: Path,
) -> tuple[Mapping[str, Any] | None, EvidenceInput]:
    display = display_path(path)
    try:
        resolved = confined_existing_evidence_path(path, root=root)
    except ValueError as exc:
        return None, EvidenceInput(
            name=name,
            path=display,
            status=EvidenceStatus.INVALID,
            detail=str(exc),
        )
    if resolved is None:
        return None, EvidenceInput(
            name=name,
            path=display,
            status=EvidenceStatus.MISSING,
            detail="not present",
        )
    try:
        evidence = loader(resolved)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, EvidenceInput(
            name=name,
            path=display,
            status=EvidenceStatus.INVALID,
            detail=str(exc),
        )
    return evidence, EvidenceInput(
        name=name,
        path=display,
        status=EvidenceStatus.LOADED,
        detail="validated and consumed",
    )


def write_validation_file(path: Path, text: str, *, root: Path) -> None:
    write_output(path, text, root=root)


def validate_validation_dir(validation_dir: Path, *, root: Path) -> None:
    candidate, relative = validation_relative_path(validation_dir, root=root)
    reject_symlink_path(relative=relative, root=root)
    if candidate.exists() and not candidate.is_dir():
        raise ValueError("validation dir must be a directory under .goffy-validation")


def confined_existing_evidence_path(path: Path, *, root: Path) -> Path | None:
    candidate, relative = validation_relative_path(path, root=root)
    reject_symlink_path(relative=relative, root=root)
    if not candidate.exists():
        return None
    if not candidate.is_file():
        raise ValueError("evidence path must be a regular file under .goffy-validation")
    return candidate


def validation_relative_path(path: Path, *, root: Path) -> tuple[Path, Path]:
    repo_root = root.expanduser().resolve(strict=False)
    validation_root = repo_root / VALIDATION_DIR
    candidate = resolve_under_root(path, root=repo_root)
    try:
        relative = candidate.relative_to(validation_root)
    except ValueError as exc:
        raise ValueError("path must be under .goffy-validation") from exc
    if ".." in relative.parts:
        raise ValueError("path must not escape .goffy-validation")
    return candidate, relative


def reject_symlink_path(*, relative: Path, root: Path) -> None:
    validation_root = root.expanduser().resolve(strict=False) / VALIDATION_DIR
    if validation_root.is_symlink():
        raise ValueError("validation dir must not be a symlink")
    current = validation_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("validation path must not contain symlinks")


def resolve_under_root(path: Path, *, root: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else root / expanded


def display_path(path: Path) -> str:
    return path.as_posix()


def render_json(report: Rom0RefreshReport) -> str:
    return json.dumps(asdict(report), indent=2) + "\n"


def render_text(report: Rom0RefreshReport) -> str:
    lines = [
        "GOFFY ROM-0 refresh",
        f"schema: {report.schema_version}",
        f"overall: {report.status}",
        f"refresh succeeded: {str(report.refresh_succeeded).lower()}",
        f"packet status: {report.packet_status}",
        f"rom ready: {str(report.rom_ready).lower()}",
        "outputs:",
        f"- probe: {report.probe_json}",
        f"- packet markdown: {report.packet_markdown}",
        f"- packet json: {report.packet_json}",
        f"- refresh report: {report.refresh_report_json}",
        "evidence inputs:",
    ]
    lines.extend(f"- {item.name}: {item.status} ({item.detail})" for item in report.evidence_inputs)
    if report.blocked_by:
        lines.append("blocked by:")
        lines.extend(f"- {item}" for item in report.blocked_by)
    if report.errors:
        lines.append("errors:")
        lines.extend(f"- {item}" for item in report.errors)
    return "\n".join(lines)


def refresh_status(*, refresh_succeeded: bool, rom_ready: bool) -> RefreshStatus:
    if not refresh_succeeded:
        return RefreshStatus.ERROR
    if rom_ready:
        return RefreshStatus.READY_FOR_ROM0_READINESS_REVIEW
    return RefreshStatus.BLOCKED


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh read-only ROM-0 probe evidence and regenerate the manual action packet."
        ),
    )
    parser.add_argument("--device-serial", help="ADB serial when more than one device is attached.")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument(
        "--validation-dir",
        type=Path,
        default=VALIDATION_DIR,
        help="Output/evidence directory under .goffy-validation.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = refresh_rom0_action_packet(
            validation_dir=args.validation_dir,
            device_serial=args.device_serial,
            timeout_seconds=args.timeout_seconds,
        )
        print(render_json(report) if args.json else render_text(report))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
