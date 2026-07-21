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

from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402
from scripts.validate_rom_manual_gates import first_sensitive_key_path  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.rom-unlock-eligibility-evidence.v1"
MOTOROLA_BOOTLOADER_SUPPORT_URL = "https://en-us.support.motorola.com/app/answers/detail/a_id/89973"
DEFAULT_OUTPUT = Path(".goffy-validation/rom-unlock-eligibility-evidence.json")
MAX_NOTE_CHARS = 300
TOP_LEVEL_KEYS = frozenset(("schema_version", "generated_at", "unlock_eligibility"))
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
    unlock_eligibility: dict[str, Any]


def create_unlock_eligibility_evidence(
    *,
    oem_unlocking_visible: bool,
    oem_unlocking_enabled: bool,
    motorola_unlock_eligibility: str,
    source_url: str = MOTOROLA_BOOTLOADER_SUPPORT_URL,
    operator_note_code: str = "not_checked",
) -> UnlockEligibilityEvidence:
    eligibility = normalize_eligibility(motorola_unlock_eligibility)
    note_code = normalize_note_code(operator_note_code)
    findings = validate_inputs(
        oem_unlocking_visible=oem_unlocking_visible,
        oem_unlocking_enabled=oem_unlocking_enabled,
        source_url=source_url,
    )
    if findings:
        raise ValueError("; ".join(findings))

    return UnlockEligibilityEvidence(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
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
    if payload.get("schema_version") != JSON_SCHEMA_VERSION:
        raise ValueError(
            "unsupported unlock eligibility evidence schema "
            f"{payload.get('schema_version')!r}; expected {JSON_SCHEMA_VERSION}"
        )

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


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        evidence = create_unlock_eligibility_evidence(
            oem_unlocking_visible=args.oem_unlocking_visible,
            oem_unlocking_enabled=args.oem_unlocking_enabled,
            motorola_unlock_eligibility=args.motorola_eligibility,
            source_url=args.source_url,
            operator_note_code=args.operator_note_code,
        )
        text = render_json(evidence)
        if args.stdout:
            print(text, end="")
        else:
            write_output(args.output, text)
            print(f"wrote unlock eligibility evidence to {args.output}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
