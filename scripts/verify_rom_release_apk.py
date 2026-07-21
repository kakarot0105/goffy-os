from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_aosp_product_import import detect_apk_signature_schemes  # noqa: E402
from scripts.create_rom_release_signing_plan import DEFAULT_SIGNED_APK  # noqa: E402
from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.rom-release-apk-verification.v1"
DEFAULT_OUTPUT = Path(".goffy-validation/rom-signing/release-apk-verification.json")


@dataclass(frozen=True)
class ReleaseApkArtifact:
    path: str
    exists: bool
    sha256: str | None
    byte_count: int | None
    signature_schemes: tuple[str, ...]


@dataclass(frozen=True)
class RomReleaseApkVerification:
    schema_version: str
    ok: bool
    status: str
    destructive_actions: str
    apk: ReleaseApkArtifact
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def verify_release_apk(
    *, apk: Path = DEFAULT_SIGNED_APK, root: Path = ROOT
) -> RomReleaseApkVerification:
    apk_path = resolve_path(apk, root=root)
    blockers: list[str] = []
    warnings: list[str] = []
    signature_schemes: tuple[str, ...] = ()
    apk_hash: str | None = None
    byte_count: int | None = None

    if apk_path.suffix != ".apk":
        blockers.append("GOFFY release verification artifact must be an APK")
    if "debug" in apk_path.name.lower():
        blockers.append("GOFFY release verification APK must not be a debug build artifact")
    if apk_path.name.endswith("-unsigned.apk"):
        blockers.append("GOFFY release verification APK must not be an unsigned Gradle artifact")
    if not apk_path.is_file():
        blockers.append("GOFFY release verification APK is missing")
    else:
        byte_count = apk_path.stat().st_size
        if byte_count <= 0:
            blockers.append("GOFFY release verification APK must not be empty")
        else:
            apk_hash = sha256_file(apk_path)
            is_zip_container = zipfile.is_zipfile(apk_path)
            if not is_zip_container:
                blockers.append("GOFFY release verification APK must be a valid APK/ZIP container")
            else:
                signature_schemes = detect_apk_signature_schemes(apk_path)
            if is_zip_container and not signature_schemes:
                blockers.append(
                    "GOFFY release verification APK must contain an APK Signature "
                    "Scheme v2/v3 block"
                )

    return RomReleaseApkVerification(
        schema_version=JSON_SCHEMA_VERSION,
        ok=not blockers,
        status="VERIFIED" if not blockers else "BLOCKED_APK_VERIFICATION",
        destructive_actions="withheld",
        apk=ReleaseApkArtifact(
            path=str(apk_path),
            exists=apk_path.is_file(),
            sha256=apk_hash,
            byte_count=byte_count,
            signature_schemes=signature_schemes,
        ),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def resolve_path(path: Path, *, root: Path) -> Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else root / expanded


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_json(verification: RomReleaseApkVerification) -> str:
    return json.dumps(asdict(verification), indent=2) + "\n"


def render_markdown(verification: RomReleaseApkVerification) -> str:
    byte_count = (
        verification.apk.byte_count if verification.apk.byte_count is not None else "missing"
    )
    lines = [
        "# GOFFY ROM Release APK Verification",
        "",
        f"- Status: `{verification.status}`",
        f"- OK: `{str(verification.ok).lower()}`",
        f"- Destructive actions: `{verification.destructive_actions}`",
        "",
        "## APK",
        f"- path: `{verification.apk.path}`",
        f"- exists: `{str(verification.apk.exists).lower()}`",
        f"- sha256: `{verification.apk.sha256 or 'missing'}`",
        f"- byte_count: `{byte_count}`",
        f"- signature_schemes: `{','.join(verification.apk.signature_schemes) or 'missing'}`",
    ]
    if verification.blockers:
        lines.extend(("", "## Blockers"))
        lines.extend(f"- {blocker}" for blocker in verification.blockers)
    if verification.warnings:
        lines.extend(("", "## Warnings"))
        lines.extend(f"- {warning}" for warning in verification.warnings)
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a signed GOFFY ROM APK without signing, flashing, or AOSP mutation.",
    )
    parser.add_argument("--apk", type=Path, default=DEFAULT_SIGNED_APK)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Optional JSON output path under .goffy-validation.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print instead of writing JSON.")
    parser.add_argument("--markdown", action="store_true", help="Render Markdown instead of JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.markdown and not args.stdout:
            raise ValueError("--markdown requires --stdout")
        verification = verify_release_apk(apk=args.apk)
        text = render_markdown(verification) if args.markdown else render_json(verification)
        if args.stdout:
            print(text, end="")
        else:
            write_output(args.output, render_json(verification))
            print(f"wrote ROM release APK verification to {args.output}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0 if verification.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
