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

from scripts.create_rom_gsi_candidate_evidence import (  # noqa: E402
    JSON_SCHEMA_VERSION as GSI_SCHEMA_VERSION,
)
from scripts.create_rom_gsi_candidate_evidence import GsiCandidateStatus  # noqa: E402
from scripts.create_rom_manual_gates_template import load_stock_restore_evidence  # noqa: E402
from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402
from scripts.rom_feasibility_probe import JSON_SCHEMA_VERSION as PROBE_SCHEMA_VERSION  # noqa: E402
from scripts.validate_rom_manual_gates import (  # noqa: E402
    EXPECTED_CODENAME,
    EXPECTED_PRODUCT,
    TARGET_DEVICE_KEYS,
    first_sensitive_key_path,
    load_probe_target_device,
)

JSON_SCHEMA_VERSION = "goffy.rom-dsu-preflight-evidence.v1"
DEFAULT_PROBE_JSON = Path(".goffy-validation/rom-feasibility-current.json")
DEFAULT_STOCK_EVIDENCE = Path(".goffy-validation/rom-stock-restore-evidence.json")
DEFAULT_GSI_EVIDENCE = Path(".goffy-validation/rom-gsi-candidate-evidence.json")
DEFAULT_OUTPUT = Path(".goffy-validation/rom-dsu-preflight-evidence.json")
ANDROID_DSU_DOCS_URL = "https://developer.android.com/topic/dsu"
ANDROID_GSI_RELEASES_URL = "https://developer.android.com/topic/generic-system-image/releases"
DSU_TOP_LEVEL_KEYS = frozenset(
    (
        "schema_version",
        "generated_at",
        "ok",
        "status",
        "destructive_actions",
        "target_device",
        "probe",
        "evidence_inputs",
        "blockers",
        "warnings",
        "next_steps",
        "official_sources",
        "reuse_decision",
        "safety",
    )
)
DSU_SAFETY_KEYS = frozenset(
    (
        "execution_authority",
        "device_mutation",
        "install_authority",
        "destructive_actions",
        "external_installers_imported",
    )
)


class DsuPreflightStatus(StrEnum):
    BLOCKED_EVIDENCE = "BLOCKED_EVIDENCE"
    READY_FOR_MANUAL_DSU_REVIEW = "READY_FOR_MANUAL_DSU_REVIEW"


class EvidenceStatus(StrEnum):
    LOADED = "LOADED"
    MISSING = "MISSING"
    INVALID = "INVALID"


@dataclass(frozen=True)
class DsuProbeSummary:
    generated_at: str
    bootloader_state: str
    android_release: str
    sdk: str
    treble_enabled: str
    dynamic_partitions: str
    dsu_package_present: str
    dsu_start_install_resolves: str
    dsu_start_install_activity: str


@dataclass(frozen=True)
class DsuEvidenceInput:
    name: str
    status: EvidenceStatus
    detail: str


@dataclass(frozen=True)
class DsuSafety:
    execution_authority: str
    device_mutation: str
    install_authority: str
    destructive_actions: str
    external_installers_imported: bool


@dataclass(frozen=True)
class DsuPreflightEvidence:
    schema_version: str
    generated_at: str
    ok: bool
    status: DsuPreflightStatus
    destructive_actions: str
    target_device: dict[str, str]
    probe: DsuProbeSummary
    evidence_inputs: tuple[DsuEvidenceInput, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    next_steps: tuple[str, ...]
    official_sources: dict[str, str]
    reuse_decision: str
    safety: DsuSafety


def create_dsu_preflight_evidence(
    *,
    probe_json: Path = DEFAULT_PROBE_JSON,
    stock_restore_evidence: Path = DEFAULT_STOCK_EVIDENCE,
    gsi_candidate_evidence: Path = DEFAULT_GSI_EVIDENCE,
    root: Path = ROOT,
) -> DsuPreflightEvidence:
    probe_path = confined_existing_validation_path(probe_json, root=root)
    if probe_path is None:
        raise ValueError("ROM feasibility probe evidence is missing")
    probe_payload = load_probe_payload(probe_path)
    target_device = load_probe_target_device(probe_path)
    target_findings = validate_target_device(target_device)
    if target_findings:
        raise ValueError("; ".join(target_findings))

    stock, stock_input = load_optional_stock_evidence(stock_restore_evidence, root=root)
    gsi, gsi_input = load_optional_gsi_evidence(gsi_candidate_evidence, root=root)
    probe_summary = dsu_probe_summary(probe_payload)
    blockers = dsu_blockers(
        target_device=target_device,
        probe_summary=probe_summary,
        stock_loaded=stock is not None,
        gsi_loaded=gsi is not None,
    )
    warnings = dsu_warnings(probe_summary=probe_summary)
    ok = not blockers

    return DsuPreflightEvidence(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=ok,
        status=(
            DsuPreflightStatus.READY_FOR_MANUAL_DSU_REVIEW
            if ok
            else DsuPreflightStatus.BLOCKED_EVIDENCE
        ),
        destructive_actions="withheld",
        target_device=target_device,
        probe=probe_summary,
        evidence_inputs=(stock_input, gsi_input),
        blockers=blockers,
        warnings=warnings,
        next_steps=next_steps(blockers=blockers, ok=ok),
        official_sources={
            "android_dsu_docs": ANDROID_DSU_DOCS_URL,
            "android_gsi_releases": ANDROID_GSI_RELEASES_URL,
        },
        reuse_decision=(
            "Use Android platform DSU and official Google GSI evidence first. "
            "Do not import DSU installer apps or ADB installer scripts until a separate "
            "manual review approves their license, permissions, maintenance, and mutation scope."
        ),
        safety=DsuSafety(
            execution_authority="LOCAL_FILE_VALIDATION_ONLY",
            device_mutation="NONE",
            install_authority="WITHHELD",
            destructive_actions="WITHHELD",
            external_installers_imported=False,
        ),
    )


def load_dsu_preflight_evidence(path: Path) -> dict[str, str]:
    payload = load_json_mapping(path)
    blockers: list[str] = []
    extra_keys = sorted(set(payload) - DSU_TOP_LEVEL_KEYS)
    if extra_keys:
        blockers.append(f"DSU preflight evidence contains unsupported keys: {extra_keys}")
    if payload.get("schema_version") != JSON_SCHEMA_VERSION:
        blockers.append("DSU preflight evidence schema_version mismatch")
    if payload.get("destructive_actions") != "withheld":
        blockers.append("DSU preflight evidence destructive_actions must be withheld")
    status = str(payload.get("status", ""))
    if status not in {item.value for item in DsuPreflightStatus}:
        blockers.append("DSU preflight evidence status is unsupported")

    safety = payload.get("safety")
    if not isinstance(safety, Mapping):
        blockers.append("DSU preflight evidence safety must be an object")
        safety = {}
    else:
        safety_extra_keys = sorted(set(safety) - DSU_SAFETY_KEYS)
        if safety_extra_keys:
            blockers.append(
                f"DSU preflight evidence safety contains unsupported keys: {safety_extra_keys}"
            )
    if safety.get("execution_authority") != "LOCAL_FILE_VALIDATION_ONLY":
        blockers.append("DSU preflight evidence execution_authority must be local-only")
    if safety.get("device_mutation") != "NONE":
        blockers.append("DSU preflight evidence device_mutation must be NONE")
    if safety.get("install_authority") != "WITHHELD":
        blockers.append("DSU preflight evidence install_authority must be WITHHELD")
    if safety.get("destructive_actions") != "WITHHELD":
        blockers.append("DSU preflight evidence safety destructive_actions must be WITHHELD")
    if safety.get("external_installers_imported") is not False:
        blockers.append("DSU preflight evidence must not import external installers")

    target_device = mapping_value(payload.get("target_device"))
    blockers.extend(validate_target_device(target_device))
    if payload.get("ok") is not True:
        blockers.extend(string_items(payload.get("blockers")) or ("DSU preflight is not ready",))
    if status != DsuPreflightStatus.READY_FOR_MANUAL_DSU_REVIEW:
        blockers.append("DSU preflight is not ready for manual DSU review")

    if blockers:
        raise ValueError("; ".join(tuple(dict.fromkeys(blockers))))

    probe = mapping_value(payload.get("probe"))
    return {
        "status": status,
        "bootloader_state": probe.get("bootloader_state", ""),
        "treble_enabled": probe.get("treble_enabled", ""),
        "dynamic_partitions": probe.get("dynamic_partitions", ""),
        "dsu_package_present": probe.get("dsu_package_present", ""),
        "dsu_start_install_resolves": probe.get("dsu_start_install_resolves", ""),
        "install_authority": str(safety.get("install_authority", "")),
        "destructive_actions": str(payload.get("destructive_actions", "")),
    }


def load_json_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("DSU preflight evidence must be a JSON object")
    return payload


def load_probe_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ROM feasibility probe evidence must be a JSON object")
    sensitive_path = first_sensitive_key_path(payload)
    if sensitive_path:
        raise ValueError(f"sensitive key is not allowed in ROM probe evidence: {sensitive_path}")
    if payload.get("schema_version") != PROBE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported ROM probe schema {payload.get('schema_version')!r}; "
            f"expected {PROBE_SCHEMA_VERSION}"
        )
    return payload


def validate_target_device(target_device: Mapping[str, str]) -> tuple[str, ...]:
    blockers: list[str] = []
    extra_keys = sorted(set(target_device) - set(TARGET_DEVICE_KEYS))
    if extra_keys:
        blockers.append(f"target_device contains unsupported keys: {extra_keys}")
    for key in TARGET_DEVICE_KEYS:
        if not target_device.get(key):
            blockers.append(f"target_device.{key} is required")
    if target_device.get("codename") != EXPECTED_CODENAME:
        blockers.append("target_device.codename must match kansas")
    if target_device.get("product") != EXPECTED_PRODUCT:
        blockers.append("target_device.product must match kansas_g_sys")
    fingerprint = target_device.get("build_fingerprint", "")
    if fingerprint and EXPECTED_PRODUCT not in fingerprint:
        blockers.append("target_device.build_fingerprint must contain kansas_g_sys")
    return tuple(blockers)


def dsu_probe_summary(probe_payload: Mapping[str, Any]) -> DsuProbeSummary:
    boot = mapping_value(probe_payload.get("boot"))
    platform = mapping_value(probe_payload.get("platform"))
    treble = mapping_value(probe_payload.get("treble"))
    dsu = mapping_value(probe_payload.get("dsu"))
    return DsuProbeSummary(
        generated_at=str(probe_payload.get("generated_at", "")),
        bootloader_state=bootloader_state(boot),
        android_release=platform.get("android_release", ""),
        sdk=platform.get("sdk", ""),
        treble_enabled=treble.get("enabled", ""),
        dynamic_partitions=treble.get("dynamic_partitions", ""),
        dsu_package_present=bool_value_text(dsu.get("package_present")),
        dsu_start_install_resolves=bool_value_text(dsu.get("start_install_resolves")),
        dsu_start_install_activity=dsu.get("start_install_activity", ""),
    )


def dsu_blockers(
    *,
    target_device: Mapping[str, str],
    probe_summary: DsuProbeSummary,
    stock_loaded: bool,
    gsi_loaded: bool,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if target_device.get("codename") != EXPECTED_CODENAME:
        blockers.append("ROM target codename is not kansas")
    if target_device.get("product") != EXPECTED_PRODUCT:
        blockers.append("ROM target product is not kansas_g_sys")
    if probe_summary.treble_enabled != "true":
        blockers.append("Treble support is not confirmed")
    if probe_summary.dynamic_partitions != "true":
        blockers.append("dynamic partitions are not confirmed")
    if probe_summary.dsu_package_present != "true":
        blockers.append("Android Dynamic System package is not visible")
    if probe_summary.dsu_start_install_resolves != "true":
        blockers.append("Android DSU start install activity is not resolvable")
    if not stock_loaded:
        blockers.append("exact stock restore evidence is missing")
    if not gsi_loaded:
        blockers.append("official Google ARM64 GSI evidence is missing")
    return tuple(dict.fromkeys(blockers))


def dsu_warnings(*, probe_summary: DsuProbeSummary) -> tuple[str, ...]:
    warnings = [
        "DSU preflight does not prove the selected GSI will boot on this Moto",
        "destructive approval remains withheld even when preflight is ready",
    ]
    if probe_summary.bootloader_state == "locked":
        warnings.append("bootloader is locked; use DSU review only, not fastboot mutation")
    return tuple(warnings)


def next_steps(*, blockers: tuple[str, ...], ok: bool) -> tuple[str, ...]:
    if ok:
        return (
            "Review DSU manually through Android system UI after backup and rollback evidence",
            "Do not install, unlock, flash, wipe, root, or reboot from this evidence helper",
        )
    steps: list[str] = []
    if "exact stock restore evidence is missing" in blockers:
        steps.append("Record exact stock restore archive and rollback evidence")
    if "official Google ARM64 GSI evidence is missing" in blockers:
        steps.append("Record official Google ARM64 GSI checksum evidence")
    if any("DSU" in blocker or "Dynamic System" in blocker for blocker in blockers):
        steps.append("Refresh the read-only ROM probe and confirm DSU availability")
    if not steps:
        steps.append("Resolve DSU preflight blockers before any GSI review")
    return tuple(steps)


def load_optional_stock_evidence(
    path: Path, *, root: Path
) -> tuple[dict[str, str] | None, DsuEvidenceInput]:
    resolved = confined_existing_validation_path(path, root=root)
    if resolved is None:
        return None, DsuEvidenceInput(
            name="stock_restore",
            status=EvidenceStatus.MISSING,
            detail="not present",
        )
    try:
        stock = load_stock_restore_evidence(resolved)
    except (OSError, ValueError, json.JSONDecodeError):
        return None, DsuEvidenceInput(
            name="stock_restore",
            status=EvidenceStatus.INVALID,
            detail="invalid or malformed",
        )
    return stock, DsuEvidenceInput(
        name="stock_restore",
        status=EvidenceStatus.LOADED,
        detail="validated and consumed",
    )


def load_optional_gsi_evidence(
    path: Path, *, root: Path
) -> tuple[dict[str, str] | None, DsuEvidenceInput]:
    resolved = confined_existing_validation_path(path, root=root)
    if resolved is None:
        return None, DsuEvidenceInput(
            name="gsi_candidate",
            status=EvidenceStatus.MISSING,
            detail="not present",
        )
    try:
        gsi = load_gsi_candidate_evidence(resolved)
    except (OSError, ValueError, json.JSONDecodeError):
        return None, DsuEvidenceInput(
            name="gsi_candidate",
            status=EvidenceStatus.INVALID,
            detail="invalid or malformed",
        )
    return gsi, DsuEvidenceInput(
        name="gsi_candidate",
        status=EvidenceStatus.LOADED,
        detail="validated and consumed",
    )


def load_gsi_candidate_evidence(path: Path) -> dict[str, str]:
    payload = load_json_mapping(path)
    blockers: list[str] = []
    if payload.get("schema_version") != GSI_SCHEMA_VERSION:
        blockers.append("GSI candidate evidence schema_version mismatch")
    if payload.get("ok") is not True:
        blockers.append("GSI candidate evidence is not OK")
    if payload.get("status") != GsiCandidateStatus.ARTIFACT_CHECKSUM_VERIFIED:
        blockers.append("GSI candidate evidence status is not ARTIFACT_CHECKSUM_VERIFIED")
    artifact = mapping_value(payload.get("artifact"))
    source = mapping_value(payload.get("source"))
    safety = mapping_value(payload.get("safety"))
    if not artifact.get("artifact_name"):
        blockers.append("GSI candidate evidence artifact_name is missing")
    if not artifact.get("sha256"):
        blockers.append("GSI candidate evidence sha256 is missing")
    if not source.get("source_url"):
        blockers.append("GSI candidate evidence source_url is missing")
    if safety.get("authorization") != "NON_AUTHORIZING_EVIDENCE":
        blockers.append("GSI candidate evidence authorization must be non-authorizing")
    if safety.get("destructive_actions") != "WITHHELD":
        blockers.append("GSI candidate evidence destructive_actions must be WITHHELD")
    if blockers:
        raise ValueError("; ".join(tuple(dict.fromkeys(blockers))))
    return {
        "status": str(payload.get("status", "")),
        "authorization": safety.get("authorization", ""),
        "artifact_name": artifact.get("artifact_name", ""),
        "sha256": artifact.get("sha256", ""),
        "source_url": source.get("source_url", ""),
    }


def confined_existing_validation_path(path: Path, *, root: Path) -> Path | None:
    repo_root = root.expanduser().resolve(strict=False)
    validation_root = repo_root / ".goffy-validation"
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else repo_root / expanded
    try:
        relative = candidate.relative_to(validation_root)
    except ValueError as exc:
        raise ValueError("evidence path must be under .goffy-validation") from exc
    if ".." in relative.parts:
        raise ValueError("evidence path must not escape .goffy-validation")
    reject_symlink_path(validation_root=validation_root, relative=relative)
    if not candidate.exists():
        return None
    if not candidate.is_file():
        raise ValueError("evidence path must be a regular file under .goffy-validation")
    return candidate


def reject_symlink_path(*, validation_root: Path, relative: Path) -> None:
    if validation_root.is_symlink():
        raise ValueError(".goffy-validation must not be a symlink")
    current = validation_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("evidence path must not contain symlinks")


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def bool_value_text(value: object) -> str:
    return "true" if str(value).strip().lower() == "true" else "false"


def bootloader_state(boot: Mapping[str, str]) -> str:
    if boot.get("flash_locked") == "0" or boot.get("vbmeta_device_state") == "unlocked":
        return "unlocked"
    if boot.get("flash_locked") == "1" or boot.get("vbmeta_device_state") == "locked":
        return "locked"
    return "unknown"


def render_json(evidence: DsuPreflightEvidence) -> str:
    return json.dumps(asdict(evidence), indent=2) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create read-only GOFFY ROM DSU preflight evidence from existing local "
            "probe, stock-restore, and GSI checksum evidence."
        ),
    )
    parser.add_argument("--probe-json", type=Path, default=DEFAULT_PROBE_JSON)
    parser.add_argument("--stock-restore-evidence", type=Path, default=DEFAULT_STOCK_EVIDENCE)
    parser.add_argument("--gsi-candidate-evidence", type=Path, default=DEFAULT_GSI_EVIDENCE)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path under .goffy-validation; stdout is used when omitted.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    args = parse_args(argv)
    try:
        evidence = create_dsu_preflight_evidence(
            probe_json=args.probe_json,
            stock_restore_evidence=args.stock_restore_evidence,
            gsi_candidate_evidence=args.gsi_candidate_evidence,
            root=root,
        )
        text = render_json(evidence)
        if args.output is None:
            print(text, end="")
        else:
            write_output(args.output, text, root=root)
            print(f"wrote DSU preflight evidence to {args.output}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
