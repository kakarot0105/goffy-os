from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_stock_restore_evidence import (  # noqa: E402
    JSON_SCHEMA_VERSION as STOCK_RESTORE_SCHEMA_VERSION,
)
from scripts.validate_rom_manual_gates import (  # noqa: E402
    ARCHIVE_NAME_PATTERN,
    SHA256_PATTERN,
    first_sensitive_key_path,
)
from scripts.validate_rom_manual_gates import (  # noqa: E402
    JSON_SCHEMA_VERSION as MANUAL_GATES_SCHEMA_VERSION,
)

VALIDATION_DIR = ROOT / ".goffy-validation"
DEFAULT_OUTPUT = VALIDATION_DIR / "rom-0-manual-gates.template.json"
MOTOROLA_SOFTWARE_FIX_URL = "https://en-us.support.motorola.com/app/softwarefix"
STOCK_RESTORE_KEYS = frozenset(("source_url", "archive_name", "sha256", "rollback_doc"))


def create_manual_gates_template(
    *,
    stock_restore_evidence: Path | None = None,
) -> dict[str, Any]:
    stock_restore = {
        "source_url": MOTOROLA_SOFTWARE_FIX_URL,
        "archive_name": "",
        "sha256": "",
        "rollback_doc": "docs/setup/kansas-stock-rollback.md",
    }
    if stock_restore_evidence is not None:
        stock_restore = load_stock_restore_evidence(stock_restore_evidence)

    return {
        "schema_version": MANUAL_GATES_SCHEMA_VERSION,
        "backup_confirmed": False,
        "oem_unlocking_enabled": False,
        "motorola_unlock_eligibility": "unknown",
        "destructive_approval": "not_requested",
        "stock_restore": stock_restore,
    }


def load_stock_restore_evidence(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("stock restore evidence must be a JSON object")
    sensitive_path = first_sensitive_key_path(payload)
    if sensitive_path:
        raise ValueError(
            f"sensitive key is not allowed in stock restore evidence: {sensitive_path}"
        )
    if payload.get("schema_version") != STOCK_RESTORE_SCHEMA_VERSION:
        raise ValueError(
            "unsupported stock restore evidence schema "
            f"{payload.get('schema_version')!r}; expected {STOCK_RESTORE_SCHEMA_VERSION}"
        )

    stock_restore = payload.get("stock_restore")
    if not isinstance(stock_restore, Mapping):
        raise ValueError("stock restore evidence must include stock_restore object")
    extra_keys = set(stock_restore) - STOCK_RESTORE_KEYS
    if extra_keys:
        raise ValueError(f"stock_restore contains unsupported keys: {sorted(extra_keys)}")

    missing = [key for key in STOCK_RESTORE_KEYS if key not in stock_restore]
    if missing:
        raise ValueError(f"stock_restore is missing required keys: {missing}")
    typed: dict[str, str] = {}
    for key in STOCK_RESTORE_KEYS:
        value = stock_restore[key]
        if not isinstance(value, str):
            raise ValueError(f"stock_restore.{key} must be a string")
        typed[key] = value
    validate_stock_restore_fields(typed)
    return typed


def validate_stock_restore_fields(stock_restore: Mapping[str, str]) -> None:
    source_url = stock_restore["source_url"]
    archive_name = stock_restore["archive_name"]
    sha256 = stock_restore["sha256"]
    rollback_doc = stock_restore["rollback_doc"]

    if source_url != MOTOROLA_SOFTWARE_FIX_URL:
        raise ValueError("stock_restore.source_url must be the Motorola Software Fix URL")
    if not ARCHIVE_NAME_PATTERN.fullmatch(archive_name):
        raise ValueError("stock_restore.archive_name must be a filename, not a path")
    if not SHA256_PATTERN.fullmatch(sha256):
        raise ValueError("stock_restore.sha256 must be 64 hex characters")
    rollback = Path(rollback_doc)
    if not rollback_doc:
        raise ValueError("stock_restore.rollback_doc is required")
    if rollback.is_absolute() or ".." in rollback.parts:
        raise ValueError("stock_restore.rollback_doc must be a relative path inside the repo")
    if rollback.suffix != ".md":
        raise ValueError("stock_restore.rollback_doc must point to a Markdown file")


def render_json(template: Mapping[str, Any]) -> str:
    return json.dumps(template, indent=2) + "\n"


def output_path_allowed(path: Path, *, root: Path = ROOT) -> bool:
    validation_root = root / ".goffy-validation"
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else root / expanded
    try:
        relative = candidate.relative_to(validation_root)
    except ValueError:
        return False
    if ".." in relative.parts:
        return False
    if validation_root.is_symlink():
        return False
    if candidate.is_symlink():
        return False
    return not any(parent.is_symlink() for parent in candidate.parents)


def write_output(path: Path, text: str, *, root: Path = ROOT) -> None:
    if not output_path_allowed(path, root=root):
        raise ValueError("output path must be under .goffy-validation")
    expanded = path.expanduser()
    resolved = expanded if expanded.is_absolute() else root / expanded
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a safe GOFFY ROM-0 manual-gates template without running device actions."
        ),
    )
    parser.add_argument(
        "--stock-restore-evidence",
        type=Path,
        help="Optional output from create_rom_stock_restore_evidence.py to seed stock_restore.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path under .goffy-validation.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON instead of writing the default .goffy-validation file.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        template = create_manual_gates_template(
            stock_restore_evidence=args.stock_restore_evidence,
        )
        text = render_json(template)
        if args.stdout:
            print(text, end="")
        else:
            write_output(args.output, text)
            print(f"wrote ROM-0 manual-gates template to {args.output}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
