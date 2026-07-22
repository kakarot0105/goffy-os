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
PROBE_SCHEMA_VERSION = "goffy.rom-feasibility-probe.v1"
MOTOROLA_SOFTWARE_FIX_URL = "https://en-us.support.motorola.com/app/softwarefix"
SHA256_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
ARCHIVE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._+@-]{1,180}$")
SENSITIVE_KEYS = {
    "android_id",
    "bluetooth",
    "credential",
    "iccid",
    "imei",
    "imsi",
    "meid",
    "msisdn",
    "password",
    "phone_number",
    "secret",
    "serial",
    "sim_serial",
    "subscriber",
    "token",
    "wifi_mac",
}
EXPECTED_CODENAME = "kansas"
EXPECTED_PRODUCT = "kansas_g_sys"
TARGET_DEVICE_KEYS = (
    "model",
    "codename",
    "product",
    "hardware_sku",
    "build_fingerprint",
    "carrier",
)
STOCK_RESTORE_KEYS = frozenset(("source_url", "archive_name", "sha256", "rollback_doc"))
MANUAL_GATE_KEYS = frozenset(
    (
        "schema_version",
        "backup_confirmed",
        "oem_unlocking_enabled",
        "motorola_unlock_eligibility",
        "destructive_approval",
        "target_device",
        "stock_restore",
    )
)
ROLLBACK_REQUIRED_HEADINGS = (
    "## Device Baseline",
    "## Stock Restore Source",
    "## SHA-256 Evidence",
    "## Rollback Procedure",
    "## Data Wipe Expectations",
    "## Approval Record",
)


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
    unsupported = unsupported_keys(payload, allowed=MANUAL_GATE_KEYS)
    if unsupported:
        raise ValueError(f"manual gate evidence contains unsupported keys: {unsupported}")
    target_device = payload.get("target_device")
    if isinstance(target_device, Mapping):
        unsupported_target = unsupported_keys(
            target_device,
            allowed=frozenset(TARGET_DEVICE_KEYS),
        )
        if unsupported_target:
            raise ValueError(f"target_device contains unsupported keys: {unsupported_target}")
    stock_restore = payload.get("stock_restore")
    if isinstance(stock_restore, Mapping):
        unsupported_stock = unsupported_keys(stock_restore, allowed=STOCK_RESTORE_KEYS)
        if unsupported_stock:
            raise ValueError(f"stock_restore contains unsupported keys: {unsupported_stock}")
    return payload


def validate_manual_gates(
    payload: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_target_device: Mapping[str, str] | None = None,
) -> ManualGateReport:
    blockers: list[str] = []
    warnings: list[str] = []
    accepted: dict[str, str] = {}

    append_unsupported_key_blockers(
        payload, allowed=MANUAL_GATE_KEYS, label="manual gate evidence", blockers=blockers
    )
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

    target_device = mapping_value(payload.get("target_device"))
    validate_target_device(
        target_device,
        blockers=blockers,
        accepted=accepted,
        expected_target_device=expected_target_device,
    )

    stock_restore = mapping_value(payload.get("stock_restore"))
    validate_stock_restore(
        stock_restore,
        root=root,
        blockers=blockers,
        accepted=accepted,
        target_device=target_device,
    )

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
    target_device: Mapping[str, str],
) -> None:
    append_unsupported_key_blockers(
        stock_restore,
        allowed=STOCK_RESTORE_KEYS,
        label="stock_restore",
        blockers=blockers,
    )
    source_url = stock_restore.get("source_url", "")
    archive_name = stock_restore.get("archive_name", "")
    sha256 = stock_restore.get("sha256", "")
    rollback_doc = stock_restore.get("rollback_doc", "")

    if not source_url.startswith("https://"):
        blockers.append("stock_restore.source_url must be an https URL")
    elif source_url != MOTOROLA_SOFTWARE_FIX_URL:
        blockers.append("stock_restore.source_url must be the Motorola Software Fix URL")
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
        elif not rollback_path.is_file():
            blockers.append("stock_restore.rollback_doc must exist")
        else:
            validate_rollback_doc(
                rollback_path=rollback_path,
                archive_name=archive_name,
                sha256=sha256,
                target_device=target_device,
                blockers=blockers,
            )

    accepted["stock_restore.source_url"] = source_url
    accepted["stock_restore.archive_name"] = archive_name
    accepted["stock_restore.sha256"] = sha256.lower()
    accepted["stock_restore.rollback_doc"] = rollback_doc


def validate_target_device(
    target_device: Mapping[str, str],
    *,
    blockers: list[str],
    accepted: dict[str, str],
    expected_target_device: Mapping[str, str] | None,
) -> None:
    append_unsupported_key_blockers(
        target_device,
        allowed=frozenset(TARGET_DEVICE_KEYS),
        label="target_device",
        blockers=blockers,
    )
    for key in TARGET_DEVICE_KEYS:
        value = target_device.get(key, "")
        if not value:
            blockers.append(f"target_device.{key} is required")
        accepted[f"target_device.{key}"] = value

    if not expected_target_device:
        blockers.append("target_device baseline probe evidence is required")
    else:
        for key in TARGET_DEVICE_KEYS:
            expected_value = expected_target_device.get(key, "")
            actual_value = target_device.get(key, "")
            if not expected_value:
                blockers.append(f"target_device baseline {key} is missing")
            elif actual_value and actual_value != expected_value:
                blockers.append(f"target_device.{key} must match ROM probe")

    if target_device.get("codename") and target_device.get("codename") != EXPECTED_CODENAME:
        blockers.append("target_device.codename must match kansas")
    if target_device.get("product") and target_device.get("product") != EXPECTED_PRODUCT:
        blockers.append("target_device.product must match kansas_g_sys")
    fingerprint = target_device.get("build_fingerprint", "")
    if fingerprint and EXPECTED_PRODUCT not in fingerprint:
        blockers.append("target_device.build_fingerprint must contain kansas_g_sys")


def validate_rollback_doc(
    *,
    rollback_path: Path,
    archive_name: str,
    sha256: str,
    target_device: Mapping[str, str],
    blockers: list[str],
) -> None:
    text = rollback_path.read_text(encoding="utf-8")
    for heading in ROLLBACK_REQUIRED_HEADINGS:
        if heading not in text:
            blockers.append(f"stock_restore.rollback_doc missing heading {heading}")
    if archive_name and archive_name not in text:
        blockers.append("stock_restore.rollback_doc must include the exact archive name")
    if SHA256_PATTERN.fullmatch(sha256) and sha256.lower() not in text.lower():
        blockers.append("stock_restore.rollback_doc must include the exact SHA-256")
    for key in TARGET_DEVICE_KEYS:
        value = target_device.get(key, "")
        if value and value not in text:
            blockers.append(f"stock_restore.rollback_doc must include target_device.{key}")


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def load_probe_target_device(path: Path) -> dict[str, str]:
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
    device = mapping_value(payload.get("device"))
    properties = mapping_value(payload.get("properties"))
    return {
        "model": device.get("model", ""),
        "codename": device.get("codename", ""),
        "product": device.get("product", ""),
        "hardware_sku": device.get("hardware_sku", ""),
        "build_fingerprint": properties.get("ro.build.fingerprint", ""),
        "carrier": device.get("carrier", ""),
    }


def unsupported_keys(
    value: Mapping[str, Any] | Mapping[object, object], *, allowed: frozenset[str]
) -> list[str]:
    return sorted(str(key) for key in value if str(key) not in allowed)


def append_unsupported_key_blockers(
    value: Mapping[str, Any] | Mapping[object, object],
    *,
    allowed: frozenset[str],
    label: str,
    blockers: list[str],
) -> None:
    unsupported = unsupported_keys(value, allowed=allowed)
    if unsupported:
        blockers.append(f"{label} contains unsupported keys: {unsupported}")


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
    parser.add_argument(
        "--probe-json",
        type=Path,
        help=(
            "Output from rom_feasibility_probe.py. Required for READY_FOR_HUMAN_REVIEW "
            "because manual target-device evidence must match the read-only probe."
        ),
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = load_manual_gates(args.manual_gates_json)
        expected_target_device = (
            load_probe_target_device(args.probe_json) if args.probe_json else None
        )
        report = validate_manual_gates(payload, expected_target_device=expected_target_device)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(render_json(report) if args.json else render_markdown(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
