from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402
from scripts.validate_rom_manual_gates import (  # noqa: E402
    EXPECTED_CODENAME,
    EXPECTED_PRODUCT,
    PROBE_SCHEMA_VERSION,
    TARGET_DEVICE_KEYS,
    first_sensitive_key_path,
    load_probe_target_device,
)

JSON_SCHEMA_VERSION = "goffy.rom-unlock-eligibility-evidence.v2"
MOTOROLA_BOOTLOADER_SUPPORT_URL = "https://en-us.support.motorola.com/app/answers/detail/a_id/89973"
DEFAULT_OUTPUT = Path(".goffy-validation/rom-unlock-eligibility-evidence.json")
CANONICAL_PROBE_JSON = Path(".goffy-validation/rom-feasibility-current.json")
MAX_NOTE_CHARS = 300
UNLOCK_EVIDENCE_MAX_AGE = timedelta(hours=24)
TOP_LEVEL_KEYS = frozenset(
    ("schema_version", "generated_at", "target_device", "probe_binding", "unlock_eligibility")
)
PROBE_BINDING_KEYS = frozenset(("source_path", "probe_generated_at", "public_target_sha256"))
UNLOCK_ELIGIBILITY_KEYS = frozenset(
    (
        "source_url",
        "oem_unlocking_visible",
        "oem_unlocking_enabled",
        "motorola_unlock_eligibility",
        "operator_note_code",
    )
)
OPERATOR_NOTE_CODES = frozenset(
    (
        "not_checked",
        "checked_no_identifiers_stored",
        "carrier_restricted",
        "motorola_page_unavailable",
    )
)


class MotorolaUnlockEligibility(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class UnlockEligibilityEvidence:
    schema_version: str
    generated_at: str
    target_device: dict[str, str]
    probe_binding: dict[str, str]
    unlock_eligibility: dict[str, Any]


def create_unlock_eligibility_evidence(
    *,
    oem_unlocking_visible: bool,
    oem_unlocking_enabled: bool,
    motorola_unlock_eligibility: str,
    probe_json: Path,
    source_url: str = MOTOROLA_BOOTLOADER_SUPPORT_URL,
    operator_note_code: str = "not_checked",
    root: Path = ROOT,
) -> UnlockEligibilityEvidence:
    eligibility = normalize_eligibility(motorola_unlock_eligibility)
    note_code = normalize_note_code(operator_note_code)
    resolved_probe, probe_findings = resolve_probe_json(probe_json, root=root)
    findings = validate_inputs(
        oem_unlocking_visible=oem_unlocking_visible,
        oem_unlocking_enabled=oem_unlocking_enabled,
        source_url=source_url,
    )
    findings.extend(probe_findings)
    if findings:
        raise ValueError("; ".join(findings))
    target_device = load_probe_target_device(resolved_probe)
    target_findings = validate_target_device(target_device)
    if target_findings:
        raise ValueError("; ".join(target_findings))
    probe_generated_at = load_probe_generated_at(resolved_probe)

    return UnlockEligibilityEvidence(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        target_device=target_device,
        probe_binding={
            "source_path": CANONICAL_PROBE_JSON.as_posix(),
            "probe_generated_at": probe_generated_at,
            "public_target_sha256": public_target_sha256(target_device),
        },
        unlock_eligibility={
            "source_url": source_url,
            "oem_unlocking_visible": oem_unlocking_visible,
            "oem_unlocking_enabled": oem_unlocking_enabled,
            "motorola_unlock_eligibility": eligibility,
            "operator_note_code": note_code,
        },
    )


def validate_inputs(
    *,
    oem_unlocking_visible: bool,
    oem_unlocking_enabled: bool,
    source_url: str,
) -> list[str]:
    findings: list[str] = []
    if oem_unlocking_enabled and not oem_unlocking_visible:
        findings.append("OEM unlocking cannot be enabled when the toggle is not visible")
    if source_url != MOTOROLA_BOOTLOADER_SUPPORT_URL:
        findings.append("source URL must be the Motorola bootloader support URL")
    return findings


def load_probe_generated_at(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("ROM probe evidence must be a JSON object")
    sensitive_path = first_sensitive_key_path(payload)
    if sensitive_path:
        raise ValueError(f"sensitive key is not allowed in ROM probe evidence: {sensitive_path}")
    if payload.get("schema_version") != PROBE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported ROM probe schema {payload.get('schema_version')!r}; "
            f"expected {PROBE_SCHEMA_VERSION}"
        )
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("ROM probe evidence generated_at must be a string")
    parse_iso_datetime(generated_at, label="ROM probe evidence generated_at")
    return generated_at


def resolve_probe_json(path: Path, *, root: Path) -> tuple[Path, list[str]]:
    findings: list[str] = []
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else root / expanded
    if path_has_symlink(candidate, root=root):
        findings.append("probe JSON path must not contain symlinks")
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError:
        findings.append("probe JSON must be inside the repo")
        return resolved, findings
    if relative != CANONICAL_PROBE_JSON:
        findings.append("probe JSON must be .goffy-validation/rom-feasibility-current.json")
    if not resolved.is_file():
        findings.append("probe JSON must exist")
    if resolved.suffix != ".json":
        findings.append("probe JSON must be a JSON file")
    return resolved, findings


def path_has_symlink(path: Path, *, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def validate_target_device(target_device: Mapping[str, str]) -> list[str]:
    findings: list[str] = []
    extra_keys = sorted(set(target_device) - set(TARGET_DEVICE_KEYS))
    if extra_keys:
        findings.append(f"target_device contains unsupported keys: {extra_keys}")
    for key in TARGET_DEVICE_KEYS:
        if not target_device.get(key):
            findings.append(f"target_device.{key} is required")
    if target_device.get("codename") and target_device.get("codename") != EXPECTED_CODENAME:
        findings.append("target_device.codename must match kansas")
    if target_device.get("product") and target_device.get("product") != EXPECTED_PRODUCT:
        findings.append("target_device.product must match kansas_g_sys")
    fingerprint = target_device.get("build_fingerprint", "")
    if fingerprint and EXPECTED_PRODUCT not in fingerprint:
        findings.append("target_device.build_fingerprint must contain kansas_g_sys")
    return findings


def public_target_sha256(target_device: Mapping[str, str]) -> str:
    canonical = {key: target_device.get(key, "") for key in TARGET_DEVICE_KEYS}
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_eligibility(value: str) -> str:
    normalized = value.strip().lower()
    allowed = {item.value for item in MotorolaUnlockEligibility}
    if normalized not in allowed:
        raise ValueError(f"motorola eligibility must be one of: {sorted(allowed)}")
    return normalized


def normalize_note_code(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in OPERATOR_NOTE_CODES:
        raise ValueError(f"operator note code must be one of: {sorted(OPERATOR_NOTE_CODES)}")
    return normalized


def load_unlock_eligibility_evidence(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("unlock eligibility evidence must be a JSON object")
    sensitive_path = first_sensitive_key_path(payload)
    if sensitive_path:
        raise ValueError(
            f"sensitive key is not allowed in unlock eligibility evidence: {sensitive_path}"
        )
    extra_top_level_keys = set(payload) - TOP_LEVEL_KEYS
    if extra_top_level_keys:
        raise ValueError(
            "unlock eligibility evidence contains unsupported top-level keys: "
            f"{sorted(extra_top_level_keys)}"
        )
    generated_at = payload.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("unlock eligibility evidence generated_at must be a string")
    parse_iso_datetime(generated_at, label="unlock eligibility evidence generated_at")
    if payload.get("schema_version") != JSON_SCHEMA_VERSION:
        raise ValueError(
            "unsupported unlock eligibility evidence schema "
            f"{payload.get('schema_version')!r}; expected {JSON_SCHEMA_VERSION}"
        )

    target_device = payload.get("target_device")
    if not isinstance(target_device, Mapping):
        raise ValueError("unlock eligibility evidence must include target_device object")
    typed_target_device = mapping_value(target_device)
    target_findings = validate_target_device(typed_target_device)
    if target_findings:
        raise ValueError("; ".join(target_findings))

    probe_binding = payload.get("probe_binding")
    if not isinstance(probe_binding, Mapping):
        raise ValueError("unlock eligibility evidence must include probe_binding object")
    typed_probe_binding = mapping_value(probe_binding)
    validate_probe_binding(typed_probe_binding, target_device=typed_target_device)

    unlock = payload.get("unlock_eligibility")
    if not isinstance(unlock, Mapping):
        raise ValueError("unlock eligibility evidence must include unlock_eligibility object")
    extra_keys = set(unlock) - UNLOCK_ELIGIBILITY_KEYS
    if extra_keys:
        raise ValueError(f"unlock_eligibility contains unsupported keys: {sorted(extra_keys)}")
    missing = [key for key in UNLOCK_ELIGIBILITY_KEYS if key not in unlock]
    if missing:
        raise ValueError(f"unlock_eligibility is missing required keys: {missing}")
    source_url = string_value(unlock.get("source_url"), "unlock_eligibility.source_url")
    oem_visible = bool_value(unlock.get("oem_unlocking_visible"))
    oem_enabled = bool_value(unlock.get("oem_unlocking_enabled"))
    eligibility = normalize_eligibility(
        string_value(
            unlock.get("motorola_unlock_eligibility"),
            "unlock_eligibility.motorola_unlock_eligibility",
        )
    )
    note_code = normalize_note_code(
        string_value(unlock.get("operator_note_code"), "unlock_eligibility.operator_note_code")
    )
    findings = validate_inputs(
        oem_unlocking_visible=oem_visible,
        oem_unlocking_enabled=oem_enabled,
        source_url=source_url,
    )
    if findings:
        raise ValueError("; ".join(findings))
    return {
        "generated_at": generated_at,
        "target_device": typed_target_device,
        "probe_binding": typed_probe_binding,
        "source_url": source_url,
        "oem_unlocking_visible": oem_visible,
        "oem_unlocking_enabled": oem_enabled,
        "motorola_unlock_eligibility": eligibility,
        "operator_note_code": note_code,
    }


def bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError("unlock eligibility boolean fields must be true or false")


def mapping_value(value: Mapping[object, object]) -> dict[str, str]:
    return {str(key): str(item) for key, item in value.items()}


def validate_probe_binding(
    probe_binding: Mapping[str, str],
    *,
    target_device: Mapping[str, str],
) -> None:
    extra_keys = sorted(set(probe_binding) - PROBE_BINDING_KEYS)
    if extra_keys:
        raise ValueError(f"probe_binding contains unsupported keys: {extra_keys}")
    missing = [key for key in PROBE_BINDING_KEYS if key not in probe_binding]
    if missing:
        raise ValueError(f"probe_binding is missing required keys: {missing}")
    if probe_binding["source_path"] != CANONICAL_PROBE_JSON.as_posix():
        raise ValueError("probe_binding.source_path must be the canonical ROM probe path")
    parse_iso_datetime(
        probe_binding["probe_generated_at"],
        label="probe_binding.probe_generated_at",
    )
    if probe_binding["public_target_sha256"] != public_target_sha256(target_device):
        raise ValueError("probe_binding.public_target_sha256 must match target_device")


def unlock_evidence_probe_blockers(
    unlock_evidence: Mapping[str, Any],
    *,
    target_device: Mapping[str, str],
    probe_generated_at: str,
) -> tuple[str, ...]:
    blockers: list[str] = []
    evidence_target = unlock_evidence.get("target_device")
    if not isinstance(evidence_target, Mapping):
        return ("unlock eligibility evidence target_device is missing",)
    for key in TARGET_DEVICE_KEYS:
        if str(evidence_target.get(key, "")) != target_device.get(key, ""):
            blockers.append(f"unlock eligibility target_device.{key} must match ROM probe")

    binding_generated: datetime | None = None
    probe_binding = unlock_evidence.get("probe_binding")
    if not isinstance(probe_binding, Mapping):
        blockers.append("unlock eligibility probe_binding is missing")
    else:
        binding = mapping_value(probe_binding)
        if binding.get("public_target_sha256", "") != public_target_sha256(target_device):
            blockers.append("unlock eligibility probe binding must match ROM probe target")
        if binding.get("source_path", "") != CANONICAL_PROBE_JSON.as_posix():
            blockers.append("unlock eligibility probe binding must use the canonical probe path")
        if "probe_generated_at" not in binding:
            blockers.append("unlock eligibility probe binding timestamp is missing")
        else:
            binding_generated = parseable_datetime_or_blocker(
                binding["probe_generated_at"],
                label="unlock eligibility probe binding timestamp",
                blockers=blockers,
            )

    evidence_generated = parseable_datetime_or_blocker(
        str(unlock_evidence.get("generated_at", "")),
        label="unlock eligibility evidence timestamp",
        blockers=blockers,
    )
    probe_generated = parseable_datetime_or_blocker(
        probe_generated_at,
        label="current ROM probe timestamp",
        blockers=blockers,
    )
    if evidence_generated is not None and probe_generated is not None:
        if binding_generated is not None and evidence_generated < binding_generated:
            blockers.append("unlock eligibility evidence timestamp precedes bound ROM probe")
        if evidence_generated - probe_generated > UNLOCK_EVIDENCE_MAX_AGE:
            blockers.append(
                "unlock eligibility evidence is newer than the current ROM probe window"
            )
        if probe_generated - evidence_generated > UNLOCK_EVIDENCE_MAX_AGE:
            blockers.append("unlock eligibility evidence is stale relative to current ROM probe")
    return tuple(blockers)


def parseable_datetime_or_blocker(
    value: str,
    *,
    label: str,
    blockers: list[str],
) -> datetime | None:
    try:
        return parse_iso_datetime(value, label=label)
    except ValueError as exc:
        blockers.append(str(exc))
        return None


def parse_iso_datetime(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(UTC)


def string_value(value: object, key: str) -> str:
    if isinstance(value, str):
        return value
    raise ValueError(f"{key} must be a string")


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "y", "1"}:
        return True
    if normalized in {"false", "no", "n", "0"}:
        return False
    raise argparse.ArgumentTypeError("expected yes/no or true/false")


def render_json(evidence: UnlockEligibilityEvidence) -> str:
    return json.dumps(asdict(evidence), indent=2) + "\n"


def render_output_path(path: Path, *, root: Path = ROOT) -> str:
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else root / expanded
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return ".goffy-validation/<redacted-output>"
    return relative.as_posix()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create redacted GOFFY ROM-0 unlock eligibility evidence from manual checks "
            "without running adb, fastboot, unlock, flash, or root actions."
        ),
    )
    parser.add_argument("--oem-unlocking-visible", type=parse_bool, required=True)
    parser.add_argument("--oem-unlocking-enabled", type=parse_bool, required=True)
    parser.add_argument(
        "--probe-json",
        type=Path,
        required=True,
        help="Canonical .goffy-validation/rom-feasibility-current.json probe evidence.",
    )
    parser.add_argument(
        "--motorola-eligibility",
        choices=[item.value for item in MotorolaUnlockEligibility],
        required=True,
    )
    parser.add_argument(
        "--source-url",
        default=MOTOROLA_BOOTLOADER_SUPPORT_URL,
        help="Motorola bootloader support URL; defaults to the official support article.",
    )
    parser.add_argument(
        "--operator-note-code",
        choices=sorted(OPERATOR_NOTE_CODES),
        default="not_checked",
        help="Closed-set redacted note code; free-form identifiers are never stored.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path under .goffy-validation.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print JSON instead of writing.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    args = parse_args(argv)
    try:
        evidence = create_unlock_eligibility_evidence(
            oem_unlocking_visible=args.oem_unlocking_visible,
            oem_unlocking_enabled=args.oem_unlocking_enabled,
            motorola_unlock_eligibility=args.motorola_eligibility,
            probe_json=args.probe_json,
            source_url=args.source_url,
            operator_note_code=args.operator_note_code,
            root=root,
        )
        text = render_json(evidence)
        if args.stdout:
            print(text, end="")
        else:
            write_output(args.output, text, root=root)
            print(
                f"wrote unlock eligibility evidence to {render_output_path(args.output, root=root)}"
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
