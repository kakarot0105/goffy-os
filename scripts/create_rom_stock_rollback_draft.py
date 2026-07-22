from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_stock_restore_evidence import (  # noqa: E402
    sha256_file,
    write_output,
)
from scripts.validate_rom_manual_gates import (  # noqa: E402
    ARCHIVE_NAME_PATTERN,
    EXPECTED_CODENAME,
    EXPECTED_PRODUCT,
    MOTOROLA_SOFTWARE_FIX_URL,
    SHA256_PATTERN,
    TARGET_DEVICE_KEYS,
    load_probe_target_device,
)

JSON_SCHEMA_VERSION = "goffy.rom-stock-rollback-draft.v1"
CANONICAL_PROBE_JSON = Path(".goffy-validation/rom-feasibility-current.json")
DEFAULT_OUTPUT = Path(".goffy-validation/kansas-stock-rollback.draft.md")


@dataclass(frozen=True)
class StockRollbackDraft:
    schema_version: str
    generated_at: str
    source_url: str
    archive_name: str
    sha256: str
    target_device: dict[str, str]
    probe_json: str


def create_stock_rollback_draft(
    *,
    archive_path: Path,
    source_url: str,
    probe_json: Path,
    root: Path = ROOT,
) -> StockRollbackDraft:
    archive = archive_path.expanduser().resolve()
    resolved_probe, rendered_probe, input_findings = validate_inputs(
        archive_path=archive,
        source_url=source_url,
        probe_json=probe_json,
        root=root,
    )
    if input_findings:
        raise ValueError("; ".join(input_findings))

    target_device = load_probe_target_device(resolved_probe)
    target_findings = validate_target_device(target_device)
    if target_findings:
        raise ValueError("; ".join(target_findings))

    sha256 = sha256_file(archive)
    if SHA256_PATTERN.fullmatch(sha256) is None:
        raise ValueError("computed SHA-256 did not match expected format")

    return StockRollbackDraft(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        source_url=source_url,
        archive_name=archive.name,
        sha256=sha256,
        target_device=target_device,
        probe_json=rendered_probe,
    )


def validate_inputs(
    *,
    archive_path: Path,
    source_url: str,
    probe_json: Path,
    root: Path,
) -> tuple[Path, str, list[str]]:
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
    elif source_url != MOTOROLA_SOFTWARE_FIX_URL:
        findings.append("source URL must be the Motorola Software Fix URL")

    resolved_probe, rendered_probe, probe_findings = resolve_probe_json(probe_json, root=root)
    findings.extend(probe_findings)
    return resolved_probe, rendered_probe, findings


def resolve_probe_json(path: Path, *, root: Path) -> tuple[Path, str, list[str]]:
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
        return resolved, "<repo-relative-probe-json>", findings
    if relative != CANONICAL_PROBE_JSON:
        findings.append("probe JSON must be .goffy-validation/rom-feasibility-current.json")
    if not resolved.is_file():
        findings.append("probe JSON must exist")
    if resolved.suffix != ".json":
        findings.append("probe JSON must be a JSON file")
    return resolved, relative.as_posix(), findings


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


def render_markdown(draft: StockRollbackDraft) -> str:
    target = draft.target_device
    return "\n".join(
        (
            "# Kansas Stock Rollback Draft",
            "",
            "Copy this draft to `docs/setup/kansas-stock-rollback.md` only after a "
            "human security review confirms it contains no private identifiers. This "
            "draft does not grant destructive approval.",
            "",
            f"- Schema: `{draft.schema_version}`",
            f"- Generated at: `{draft.generated_at}`",
            "- Destructive approval: `not_granted`",
            "",
            "## Device Baseline",
            f"- Model: {target.get('model', '')}",
            f"- Codename: {target.get('codename', '')}",
            f"- Product: {target.get('product', '')}",
            f"- Hardware SKU: {target.get('hardware_sku', '')}",
            f"- Build fingerprint: {target.get('build_fingerprint', '')}",
            "- Android release/build: recorded from ROM feasibility probe",
            f"- Carrier/channel: {target.get('carrier', '')}",
            f"- ROM feasibility probe file: {draft.probe_json}",
            "",
            "## Stock Restore Source",
            f"- Source: {draft.source_url}",
            f"- Firmware archive: {draft.archive_name}",
            "- Local storage location: outside git; exact path intentionally redacted",
            "",
            "## SHA-256 Evidence",
            f"- SHA-256: {draft.sha256}",
            "- Hash command output: computed by GOFFY helper; local path intentionally redacted",
            "",
            "## Rollback Procedure",
            "1. Keep the phone charged and connected.",
            "2. Restore with Motorola Software Fix before attempting another ROM path.",
            "3. Reboot and verify Android boots normally.",
            "4. Re-run the GOFFY ROM feasibility probe.",
            "5. Re-run ROM-0 readiness validation before any further destructive decision.",
            "",
            "## Data Wipe Expectations",
            "- Bootloader unlock may wipe all user data.",
            (
                "- Stock restore may wipe app data, pairing state, photos, "
                "downloads, and local GOFFY notes."
            ),
            "- Backups must be verified before destructive approval is requested.",
            "",
            "## Approval Record",
            "- Destructive approval status: not granted by this document.",
            "- Human reviewer:",
            "- Review timestamp:",
            "- Notes:",
            "",
        )
    )


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
            "Create a redacted stock rollback Markdown draft from a local archive "
            "and read-only ROM probe evidence."
        ),
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--probe-json", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path under .goffy-validation; stdout is used with --stdout.",
    )
    parser.add_argument("--stdout", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    args = parse_args(argv)
    try:
        draft = create_stock_rollback_draft(
            archive_path=args.archive,
            source_url=args.source_url,
            probe_json=args.probe_json,
            root=root,
        )
        text = render_markdown(draft)
        if args.stdout:
            print(text, end="")
        else:
            write_output(args.output, text, root=root)
            print(f"wrote stock rollback draft to {render_output_path(args.output, root=root)}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
