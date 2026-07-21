from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_aosp_product_import import (  # noqa: E402
    AospProductImportError,
    create_aosp_product_import_report,
)
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION  # noqa: E402
from scripts.validate_rom_manual_gates import (  # noqa: E402
    load_manual_gates,
    validate_manual_gates,
)
from scripts.validate_rom_product_overlay import validate_rom_product_overlay  # noqa: E402
from scripts.validate_rom_system_app import validate_rom_system_app  # noqa: E402

READINESS_SCHEMA_VERSION = "goffy.rom0-readiness.v1"
DEFAULT_AOSP_ROOT = Path("<aosp-root>")
EXPECTED_CODENAME = "kansas"
EXPECTED_PRODUCT = "kansas_g_sys"


class Rom0ReadinessStatus(StrEnum):
    BLOCKED = "BLOCKED"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


@dataclass(frozen=True)
class ReadinessSection:
    name: str
    ok: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    evidence: dict[str, str] | None = None


@dataclass(frozen=True)
class Rom0ReadinessReport:
    schema_version: str
    generated_at: str
    ok: bool
    status: Rom0ReadinessStatus
    destructive_actions: str
    sections: tuple[ReadinessSection, ...]
    next_steps: tuple[str, ...]


def build_readiness_report(
    *,
    probe_json: Path | None,
    manual_gates_json: Path | None,
    signed_apk: Path | None,
    aosp_root: Path = DEFAULT_AOSP_ROOT,
    root: Path = ROOT,
    evidence_root: Path = ROOT,
) -> Rom0ReadinessReport:
    sections = (
        validate_rom_descriptors(root=root),
        validate_probe_evidence(probe_json),
        validate_manual_gate_evidence(manual_gates_json, evidence_root=evidence_root),
        validate_aosp_import_evidence(signed_apk=signed_apk, aosp_root=aosp_root, root=root),
    )
    ok = all(section.ok for section in sections)
    return Rom0ReadinessReport(
        schema_version=READINESS_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=ok,
        status=Rom0ReadinessStatus.READY_FOR_HUMAN_REVIEW if ok else Rom0ReadinessStatus.BLOCKED,
        destructive_actions="withheld",
        sections=sections,
        next_steps=next_steps(sections),
    )


def validate_rom_descriptors(*, root: Path) -> ReadinessSection:
    blockers = [
        *(f"system-app: {finding}" for finding in validate_rom_system_app(root=root)),
        *(f"product-overlay: {finding}" for finding in validate_rom_product_overlay(root=root)),
    ]
    return ReadinessSection(
        name="rom_descriptors",
        ok=not blockers,
        blockers=tuple(blockers),
        evidence={"system_app": "validated", "product_overlay": "validated"}
        if not blockers
        else {},
    )


def validate_probe_evidence(path: Path | None) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="rom_probe",
            ok=False,
            blockers=("ROM feasibility probe JSON was not supplied",),
        )
    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="rom_probe", ok=False, blockers=(str(exc),))

    blockers: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != PROBE_SCHEMA_VERSION:
        blockers.append("ROM feasibility probe schema_version mismatch")
    if payload.get("ok") is not True:
        blockers.extend(
            string_items(payload.get("blockers")) or ["ROM feasibility probe is not OK"]
        )
    device = mapping_value(payload.get("device"))
    boot = mapping_value(payload.get("boot"))
    treble = mapping_value(payload.get("treble"))
    dsu = mapping_value(payload.get("dsu"))
    if device.get("codename") != EXPECTED_CODENAME:
        blockers.append("ROM probe codename does not match kansas")
    if device.get("product") != EXPECTED_PRODUCT:
        blockers.append("ROM probe product does not match kansas_g_sys")
    if boot.get("flash_locked") != "0" or boot.get("vbmeta_device_state") != "unlocked":
        blockers.append("ROM probe does not show an unlocked bootloader")
    if treble.get("enabled") != "true":
        blockers.append("ROM probe does not show Treble enabled")
    if treble.get("dynamic_partitions") != "true":
        blockers.append("ROM probe does not show dynamic partitions")
    if dsu.get("package_installed") != "true":
        warnings.append("ROM probe did not confirm DSU package availability")

    return ReadinessSection(
        name="rom_probe",
        ok=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        evidence={
            "codename": device.get("codename", ""),
            "product": device.get("product", ""),
            "bootloader": boot.get("vbmeta_device_state", ""),
            "rom_path": str(payload.get("rom_path", "")),
        },
    )


def validate_manual_gate_evidence(path: Path | None, *, evidence_root: Path) -> ReadinessSection:
    if path is None:
        return ReadinessSection(
            name="manual_gates",
            ok=False,
            blockers=("ROM-0 manual gate evidence JSON was not supplied",),
        )
    try:
        payload = load_manual_gates(path)
        report = validate_manual_gates(payload, root=evidence_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ReadinessSection(name="manual_gates", ok=False, blockers=(str(exc),))
    return ReadinessSection(
        name="manual_gates",
        ok=report.ok,
        blockers=report.blockers,
        warnings=report.warnings,
        evidence=report.accepted_evidence,
    )


def validate_aosp_import_evidence(
    *,
    signed_apk: Path | None,
    aosp_root: Path,
    root: Path,
) -> ReadinessSection:
    if signed_apk is None:
        return ReadinessSection(
            name="aosp_import",
            ok=False,
            blockers=("Externally signed GOFFY APK was not supplied",),
        )
    try:
        report = create_aosp_product_import_report(
            aosp_root=aosp_root,
            apk_path=signed_apk,
            repo_root=root,
        )
    except (OSError, ValueError, json.JSONDecodeError, AospProductImportError) as exc:
        return ReadinessSection(name="aosp_import", ok=False, blockers=(str(exc),))
    apk_entry = next(
        (item for item in report.files if item.destination.endswith("GoffyOS.apk")),
        None,
    )
    evidence = {
        "aosp_root": report.aosp_root,
        "apk_sha256": apk_entry.sha256 if apk_entry else "",
        "apk_signature_schemes": ",".join(apk_entry.apk_signature_schemes) if apk_entry else "",
    }
    return ReadinessSection(
        name="aosp_import",
        ok=report.safe_to_execute,
        blockers=report.blockers,
        evidence=evidence,
    )


def next_steps(sections: tuple[ReadinessSection, ...]) -> tuple[str, ...]:
    steps: list[str] = []
    for section in sections:
        if section.ok:
            continue
        if section.name == "rom_probe":
            steps.append(
                "Run the read-only ROM feasibility probe and record unlocked-state evidence."
            )
        elif section.name == "manual_gates":
            steps.append("Complete ROM-0 manual gate evidence without secrets or live approval.")
        elif section.name == "aosp_import":
            steps.append(
                "Provide an externally signed non-debug GOFFY APK for AOSP import planning."
            )
        else:
            steps.append(f"Resolve blockers in {section.name}.")
    if not steps:
        steps.append(
            "Review the evidence manually; this report still does not authorize unlock, "
            "flash, or erase."
        )
    return tuple(dict.fromkeys(steps))


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def render_json(report: Rom0ReadinessReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_markdown(report: Rom0ReadinessReport) -> str:
    lines = [
        "# GOFFY ROM-0 Readiness",
        "",
        f"- Status: `{report.status}`",
        f"- OK: `{str(report.ok).lower()}`",
        f"- Destructive actions: `{report.destructive_actions}`",
    ]
    for section in report.sections:
        lines.extend(("", f"## {section.name}", f"- OK: `{str(section.ok).lower()}`"))
        if section.blockers:
            lines.append("- Blockers:")
            lines.extend(f"  - {blocker}" for blocker in section.blockers)
        if section.warnings:
            lines.append("- Warnings:")
            lines.extend(f"  - {warning}" for warning in section.warnings)
        if section.evidence:
            lines.append("- Evidence:")
            for key, value in section.evidence.items():
                lines.append(f"  - {key}: `{value or 'missing'}`")
    lines.extend(("", "## Next Steps"))
    lines.extend(f"- {step}" for step in report.next_steps)
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize GOFFY ROM-0 readiness without device or AOSP mutations.",
    )
    parser.add_argument("--probe-json", type=Path)
    parser.add_argument("--manual-gates-json", type=Path)
    parser.add_argument("--signed-apk", type=Path)
    parser.add_argument("--aosp-root", type=Path, default=DEFAULT_AOSP_ROOT)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=ROOT,
        help="Root used for rollback_doc paths inside manual gate evidence.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_readiness_report(
        probe_json=args.probe_json,
        manual_gates_json=args.manual_gates_json,
        signed_apk=args.signed_apk,
        aosp_root=args.aosp_root,
        evidence_root=args.evidence_root,
    )
    print(render_json(report) if args.json else render_markdown(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
