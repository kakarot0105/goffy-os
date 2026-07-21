from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_rom_manual_gates import ARCHIVE_NAME_PATTERN, SHA256_PATTERN  # noqa: E402

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
    parsed_source = urlsplit(source_url)
    if parsed_source.scheme != "https" or not parsed_source.netloc:
        findings.append("source URL must be https")
    elif parsed_source.username or parsed_source.password or "@" in parsed_source.netloc:
        findings.append("source URL must not include credentials")
    elif parsed_source.query or parsed_source.fragment:
        findings.append("source URL must not include query or fragment")

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
    output_path, relative_parts = confined_output_path(path, root=root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_no_follow(root / ".goffy-validation", relative_parts, text)


def confined_output_path(path: Path, *, root: Path) -> tuple[Path, tuple[str, ...]]:
    if not output_path_allowed(path, root=root):
        raise ValueError("output path must be under .goffy-validation")
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else root / expanded
    validation_root = root / ".goffy-validation"
    relative = candidate.relative_to(validation_root)
    if not relative.parts:
        raise ValueError("output path must be a file under .goffy-validation")
    return candidate, tuple(relative.parts)


def write_text_no_follow(validation_root: Path, relative_parts: tuple[str, ...], text: str) -> None:
    validation_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    child_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    encoding = text.encode("utf-8")
    dir_fd = os.open(validation_root, validation_flags)
    try:
        for part in relative_parts[:-1]:
            next_dir_fd = os.open(part, child_flags, dir_fd=dir_fd)
            os.close(dir_fd)
            dir_fd = next_dir_fd
        file_fd = os.open(relative_parts[-1], file_flags, 0o600, dir_fd=dir_fd)
        try:
            os.write(file_fd, encoding)
        finally:
            os.close(file_fd)
    finally:
        os.close(dir_fd)


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
