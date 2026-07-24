from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_manual_gates_template import load_stock_restore_evidence  # noqa: E402
from scripts.create_rom_stock_restore_evidence import sha256_file  # noqa: E402
from scripts.validate_rom_manual_gates import (  # noqa: E402
    EXPECTED_CODENAME,
    EXPECTED_PRODUCT,
    MOTOROLA_SOFTWARE_FIX_URL,
    TARGET_DEVICE_KEYS,
    load_probe_target_device,
    validate_stock_restore,
)

JSON_SCHEMA_VERSION = "goffy.rom-stock-rollback-bundle.v1"
DEFAULT_STOCK_RESTORE_EVIDENCE = Path(".goffy-validation/rom-stock-restore-evidence.json")
DEFAULT_PROBE_JSON = Path(".goffy-validation/rom-feasibility-current.json")


class StockRollbackBundleStatus(StrEnum):
    READY_FOR_MANUAL_REVIEW = "READY_FOR_MANUAL_REVIEW"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class StockArchiveCheck:
    requested: bool
    archive_name: str
    sha256: str
    filename_matches_evidence: bool
    sha256_matches_evidence: bool
    local_path_redacted: bool


@dataclass(frozen=True)
class StockRollbackSafety:
    execution_authority: str
    archive_downloaded: bool
    restore_invoked: bool
    device_mutation: str
    authorization: str
    destructive_actions: str


@dataclass(frozen=True)
class StockRollbackBundleReport:
    schema_version: str
    generated_at: str
    ok: bool
    status: StockRollbackBundleStatus
    stock_restore: dict[str, str]
    target_device: dict[str, str]
    archive_check: StockArchiveCheck
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    safety: StockRollbackSafety


def verify_stock_rollback_bundle(
    *,
    stock_restore_evidence: Path = DEFAULT_STOCK_RESTORE_EVIDENCE,
    probe_json: Path = DEFAULT_PROBE_JSON,
    archive_path: Path | None = None,
    root: Path = ROOT,
) -> StockRollbackBundleReport:
    blockers: list[str] = []
    warnings: list[str] = []
    stock_restore = load_stock_restore(stock_restore_evidence, blockers)
    target_device = load_target_device(probe_json, blockers)

    if stock_restore and target_device:
        validate_stock_restore(
            stock_restore,
            root=root,
            blockers=blockers,
            accepted={},
            target_device=target_device,
        )
        validate_rollback_doc_source(root=root, stock_restore=stock_restore, blockers=blockers)

    archive_check = validate_archive(
        archive_path,
        stock_restore=stock_restore,
        root=root,
        blockers=blockers,
        warnings=warnings,
    )

    unique_blockers = tuple(dict.fromkeys(blockers))
    return StockRollbackBundleReport(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=not unique_blockers,
        status=(
            StockRollbackBundleStatus.READY_FOR_MANUAL_REVIEW
            if not unique_blockers
            else StockRollbackBundleStatus.BLOCKED
        ),
        stock_restore=stock_restore,
        target_device=target_device,
        archive_check=archive_check,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        safety=StockRollbackSafety(
            execution_authority="LOCAL_FILE_VALIDATION_ONLY",
            archive_downloaded=False,
            restore_invoked=False,
            device_mutation="NONE",
            authorization="NON_AUTHORIZING_EVIDENCE",
            destructive_actions="WITHHELD",
        ),
    )


def load_stock_restore(path: Path, blockers: list[str]) -> dict[str, str]:
    try:
        return load_stock_restore_evidence(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        blockers.append(f"stock_restore_evidence: {safe_error(exc)}")
        return {}


def load_target_device(path: Path, blockers: list[str]) -> dict[str, str]:
    try:
        target = load_probe_target_device(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        blockers.append(f"probe_json: {safe_error(exc)}")
        return {}
    missing = [key for key in TARGET_DEVICE_KEYS if not target.get(key)]
    if missing:
        blockers.append(f"probe_json target_device is missing required keys: {missing}")
    if target.get("codename") and target.get("codename") != EXPECTED_CODENAME:
        blockers.append("probe_json target_device.codename must match kansas")
    if target.get("product") and target.get("product") != EXPECTED_PRODUCT:
        blockers.append("probe_json target_device.product must match kansas_g_sys")
    fingerprint = target.get("build_fingerprint", "")
    if fingerprint and EXPECTED_PRODUCT not in fingerprint:
        blockers.append("probe_json target_device.build_fingerprint must contain kansas_g_sys")
    return target


def validate_archive(
    archive_path: Path | None,
    *,
    stock_restore: Mapping[str, str],
    root: Path,
    blockers: list[str],
    warnings: list[str],
) -> StockArchiveCheck:
    if archive_path is None:
        warnings.append("local archive rehash was not requested; relying on stock evidence SHA-256")
        return StockArchiveCheck(
            requested=False,
            archive_name="",
            sha256="",
            filename_matches_evidence=False,
            sha256_matches_evidence=False,
            local_path_redacted=True,
        )

    expanded = archive_path.expanduser()
    input_archive = expanded if expanded.is_absolute() else root / expanded
    try:
        resolved_archive = input_archive.resolve()
    except (OSError, RuntimeError) as exc:
        blockers.append(f"archive: {safe_error(exc)}")
        return StockArchiveCheck(
            requested=True,
            archive_name=input_archive.name,
            sha256="",
            filename_matches_evidence=input_archive.name == stock_restore.get("archive_name", ""),
            sha256_matches_evidence=False,
            local_path_redacted=True,
        )
    archive_name = resolved_archive.name
    computed_sha = ""
    filename_matches = archive_name == stock_restore.get("archive_name", "")
    sha256_matches = False

    if path_has_symlink(input_archive, root=root):
        blockers.append("archive path must not contain symlinks")
    if path_is_inside(input_archive, root) or path_is_inside(resolved_archive, root):
        blockers.append("archive path must be outside the repo to avoid committing firmware")
    if not resolved_archive.is_file():
        blockers.append("archive path must point to an existing file")
    if archive_name and not filename_matches:
        blockers.append("archive filename must match stock restore evidence archive_name")

    if resolved_archive.is_file():
        try:
            computed_sha = sha256_file(resolved_archive)
        except OSError as exc:
            blockers.append(f"archive: {safe_error(exc)}")
        else:
            sha256_matches = computed_sha == stock_restore.get("sha256", "").lower()
            if not sha256_matches:
                blockers.append("archive SHA-256 must match stock restore evidence sha256")

    return StockArchiveCheck(
        requested=True,
        archive_name=archive_name,
        sha256=computed_sha,
        filename_matches_evidence=filename_matches,
        sha256_matches_evidence=sha256_matches,
        local_path_redacted=True,
    )


def path_has_symlink(path: Path, *, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.is_symlink()
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return True


def safe_error(exc: BaseException) -> str:
    if isinstance(exc, OSError):
        return f"local file operation failed: errno {exc.errno}"
    if isinstance(exc, RuntimeError):
        return "local file operation failed"
    return str(exc)


def validate_rollback_doc_source(
    *,
    root: Path,
    stock_restore: Mapping[str, str],
    blockers: list[str],
) -> None:
    rollback_doc = stock_restore.get("rollback_doc", "")
    rollback = Path(rollback_doc)
    if not rollback_doc or rollback.is_absolute() or ".." in rollback.parts:
        return
    rollback_path = root / rollback
    if not rollback_path.is_file():
        return
    try:
        text = rollback_path.read_text(encoding="utf-8")
    except OSError as exc:
        blockers.append(f"rollback_doc: {safe_error(exc)}")
        return
    if MOTOROLA_SOFTWARE_FIX_URL not in text:
        blockers.append("rollback doc must include the Motorola Software Fix URL")


def render_json(report: StockRollbackBundleReport) -> str:
    return json.dumps(asdict(report), indent=2) + "\n"


def render_text(report: StockRollbackBundleReport) -> str:
    lines = [
        "GOFFY ROM stock rollback bundle",
        f"schema: {report.schema_version}",
        f"ok: {str(report.ok).lower()}",
        f"status: {report.status}",
        f"archive: {report.stock_restore.get('archive_name', '<missing>')}",
        f"sha256: {report.stock_restore.get('sha256', '<missing>')}",
        f"rollback doc: {report.stock_restore.get('rollback_doc', '<missing>')}",
        f"target: {report.target_device.get('product', '<missing>')}",
        f"archive rehashed: {str(report.archive_check.requested).lower()}",
        f"restore invoked: {str(report.safety.restore_invoked).lower()}",
        f"device mutation: {report.safety.device_mutation}",
    ]
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify stock restore evidence, rollback Markdown, and ROM probe identity "
            "without downloading firmware, running Software Fix, or touching a phone."
        ),
    )
    parser.add_argument(
        "--stock-restore-evidence",
        type=Path,
        default=DEFAULT_STOCK_RESTORE_EVIDENCE,
    )
    parser.add_argument("--probe-json", type=Path, default=DEFAULT_PROBE_JSON)
    parser.add_argument(
        "--archive",
        type=Path,
        help="Optional local Motorola Software Fix archive to rehash against stock evidence.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    args = parse_args(argv)
    report = verify_stock_rollback_bundle(
        stock_restore_evidence=args.stock_restore_evidence,
        probe_json=args.probe_json,
        archive_path=args.archive,
        root=root,
    )
    print(render_json(report) if args.json else render_text(report), end="")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
