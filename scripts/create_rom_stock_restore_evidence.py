from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.validate_rom_manual_gates import ARCHIVE_NAME_PATTERN, SHA256_PATTERN

ROOT = Path(__file__).resolve().parents[1]
JSON_SCHEMA_VERSION = "goffy.rom-stock-restore-evidence.v1"
VALIDATION_DIR = ROOT / ".goffy-validation"


@dataclass(frozen=True)
class StockRestoreEvidence:
    schema_version: str
    generated_at: str
    stock_restore: dict[str, str]


def create_stock_restore_evidence(
    *,
    archive_path: Path,
    source_url: str,
    rollback_doc: str,
    root: Path = ROOT,
) -> StockRestoreEvidence:
    archive = archive_path.expanduser().resolve()
    findings = validate_inputs(
        archive_path=archive,
        source_url=source_url,
        rollback_doc=rollback_doc,
        root=root,
    )
    if findings:
        raise ValueError("; ".join(findings))

    sha256 = sha256_file(archive)
    if SHA256_PATTERN.fullmatch(sha256) is None:
        raise ValueError("computed SHA-256 did not match expected format")

    return StockRestoreEvidence(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        stock_restore={
            "source_url": source_url,
            "archive_name": archive.name,
            "sha256": sha256,
            "rollback_doc": rollback_doc,
        },
    )


def validate_inputs(
    *,
    archive_path: Path,
    source_url: str,
    rollback_doc: str,
    root: Path,
) -> list[str]:
    findings: list[str] = []
    if not archive_path.is_file():
        findings.append("archive path must point to an existing file")
    if not ARCHIVE_NAME_PATTERN.fullmatch(archive_path.name):
        findings.append("archive filename contains unsupported characters")
    if not source_url.startswith("https://"):
        findings.append("source URL must be https")

    rollback = Path(rollback_doc)
    if not rollback_doc:
        findings.append("rollback doc is required")
    elif rollback.is_absolute() or ".." in rollback.parts:
        findings.append("rollback doc must be a relative repo path")
    else:
        rollback_path = root / rollback
        if rollback_path.suffix != ".md":
            findings.append("rollback doc must be Markdown")
        if not rollback_path.is_file():
            findings.append("rollback doc must exist")
    return findings


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_json(evidence: StockRestoreEvidence) -> str:
    return json.dumps(asdict(evidence), indent=2) + "\n"


def output_path_allowed(path: Path, *, root: Path = ROOT) -> bool:
    try:
        path.expanduser().resolve().relative_to((root / ".goffy-validation").resolve())
    except ValueError:
        return False
    return True


def write_output(path: Path, text: str, *, root: Path = ROOT) -> None:
    if not output_path_allowed(path, root=root):
        raise ValueError("output path must be under .goffy-validation")
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create redacted GOFFY ROM stock-restore evidence from a local archive.",
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--rollback-doc", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path under .goffy-validation; stdout is used when omitted.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        evidence = create_stock_restore_evidence(
            archive_path=args.archive,
            source_url=args.source_url,
            rollback_doc=args.rollback_doc,
        )
        text = render_json(evidence)
        if args.output is None:
            print(text, end="")
        else:
            write_output(args.output, text)
            print(f"wrote stock-restore evidence to {args.output}")
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
