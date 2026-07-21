from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
JSON_SCHEMA_VERSION = "goffy.rom-manual-gates.v1"
SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
ARCHIVE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._+@-]{1,180}$")
SENSITIVE_KEYS = {"imei", "serial", "token", "password", "secret", "credential"}


class ManualGateStatus(StrEnum):
    BLOCKED_MANUAL_GATES = "BLOCKED_MANUAL_GATES"
    READY_FOR_HUMAN_REVIEW = "READY_FOR_HUMAN_REVIEW"


@dataclass(frozen=True)
class ManualGateReport:
    schema_version: str
    generated_at: str
    ok: bool
    status: ManualGateStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    accepted_evidence: dict[str, str]


def load_manual_gates(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manual gate evidence must be a JSON object")
    schema = payload.get("schema_version")
    if schema != JSON_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported manual gate schema {schema!r}; expected {JSON_SCHEMA_VERSION}"
        )
    sensitive_path = first_sensitive_key_path(payload)
    if sensitive_path:
        raise ValueError(f"sensitive key is not allowed in manual gate evidence: {sensitive_path}")
    return payload


def validate_manual_gates(payload: Mapping[str, Any], *, root: Path = ROOT) -> ManualGateReport:
    blockers: list[str] = []
    warnings: list[str] = []
    accepted: dict[str, str] = {}

    require_bool_true(payload, "backup_confirmed", blockers)
    require_bool_true(payload, "oem_unlocking_enabled", blockers)

    eligibility = str(payload.get("motorola_unlock_eligibility", "unknown"))
    if eligibility != "eligible":
        blockers.append("Motorola bootloader unlock eligibility is not recorded as eligible")
    accepted["motorola_unlock_eligibility"] = eligibility

    destructive_approval = str(payload.get("destructive_approval", "not_requested"))
    if destructive_approval != "not_requested":
        warnings.append(
            "destructive approval belongs outside evidence validation and must be requested live"
        )
    accepted["destructive_approval"] = destructive_approval

    stock_restore = mapping_value(payload.get("stock_restore"))
    validate_stock_restore(stock_restore, root=root, blockers=blockers, accepted=accepted)

    ok = not blockers
    return ManualGateReport(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=ok,
        status=ManualGateStatus.READY_FOR_HUMAN_REVIEW
        if ok
        else ManualGateStatus.BLOCKED_MANUAL_GATES,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        accepted_evidence=accepted,
    )


def require_bool_true(payload: Mapping[str, Any], key: str, blockers: list[str]) -> None:
    if payload.get(key) is not True:
        blockers.append(f"{key} must be true")


def validate_stock_restore(
    stock_restore: Mapping[str, str],
    *,
    root: Path,
    blockers: list[str],
    accepted: dict[str, str],
) -> None:
    source_url = stock_restore.get("source_url", "")
    archive_name = stock_restore.get("archive_name", "")
    sha256 = stock_restore.get("sha256", "")
    rollback_doc = stock_restore.get("rollback_doc", "")

    if not source_url.startswith("https://"):
        blockers.append("stock_restore.source_url must be an https URL")
    if not ARCHIVE_NAME_PATTERN.fullmatch(archive_name):
        blockers.append("stock_restore.archive_name must be a filename, not a path")
    if not SHA256_PATTERN.fullmatch(sha256):
        blockers.append("stock_restore.sha256 must be 64 hex characters")
    if not rollback_doc:
        blockers.append("stock_restore.rollback_doc is required")
    elif Path(rollback_doc).is_absolute() or ".." in Path(rollback_doc).parts:
        blockers.append("stock_restore.rollback_doc must be a relative path inside the repo")
    else:
        rollback_path = root / rollback_doc
        if rollback_path.suffix != ".md":
            blockers.append("stock_restore.rollback_doc must point to a Markdown file")
        if not rollback_path.is_file():
            blockers.append("stock_restore.rollback_doc must exist")

    accepted["stock_restore.source_url"] = source_url
    accepted["stock_restore.archive_name"] = archive_name
    accepted["stock_restore.sha256"] = sha256.lower()
    accepted["stock_restore.rollback_doc"] = rollback_doc


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def first_sensitive_key_path(value: object, *, prefix: str = "") -> str:
    if isinstance(value, Mapping):
        for key, item in value.items():
            text_key = str(key)
            path = f"{prefix}.{text_key}" if prefix else text_key
            lower_key = text_key.lower()
            if any(sensitive in lower_key for sensitive in SENSITIVE_KEYS):
                return path
            nested = first_sensitive_key_path(item, prefix=path)
            if nested:
                return nested
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested = first_sensitive_key_path(item, prefix=f"{prefix}[{index}]")
            if nested:
                return nested
    return ""


def render_markdown(report: ManualGateReport) -> str:
    lines = [
        "# GOFFY ROM-0 Manual Gate Validation",
        "",
        f"- Status: `{report.status}`",
        f"- OK: `{str(report.ok).lower()}`",
        "- Destructive commands: withheld",
    ]
    if report.blockers:
        lines.extend(("", "## Blockers"))
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.extend(("", "## Warnings"))
        lines.extend(f"- {warning}" for warning in report.warnings)
    lines.extend(("", "## Accepted Evidence"))
    for key, value in report.accepted_evidence.items():
        lines.append(f"- {key}: `{value or 'missing'}`")
    lines.extend(
        (
            "",
            "## Next Step",
            "- If status is `READY_FOR_HUMAN_REVIEW`, review the evidence manually before "
            "asking for any destructive bootloader action.",
            "",
        )
    )
    return "\n".join(lines)


def render_json(report: ManualGateReport) -> str:
    return json.dumps(asdict(report), indent=2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate GOFFY ROM-0 manual evidence without executing device actions.",
    )
    parser.add_argument("manual_gates_json", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = load_manual_gates(args.manual_gates_json)
        report = validate_manual_gates(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(render_json(report) if args.json else render_markdown(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
