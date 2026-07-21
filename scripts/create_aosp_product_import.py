from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_rom_product_overlay import validate_rom_product_overlay  # noqa: E402
from scripts.validate_rom_system_app import validate_rom_system_app  # noqa: E402

SYSTEM_APP_DESCRIPTOR = ROOT / "rom" / "system-app" / "goffy-system-app.json"
PRODUCT_DESCRIPTOR = ROOT / "rom" / "product" / "goffy-product-overlay.json"

PRODUCT_IMPORT_DIR = Path("device/goffy/goffy_gsi_phone")
APP_IMPORT_DIR = Path("vendor/goffy/apps/GoffyOS")
APK_SIG_BLOCK_MAGIC = b"APK Sig Block 42"
ZIP_EOCD_MAGIC = b"PK\x05\x06"
APK_SIGNATURE_SCHEME_IDS = {
    0x7109871A,  # v2
    0xF05368C0,  # v3
    0x1B93AD61,  # v3.1
}


@dataclass(frozen=True)
class PlannedImportFile:
    source: str
    destination: str
    sha256: str | None
    byte_count: int | None
    status: str
    apk_signature_schemes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AospProductImportReport:
    mode: str
    aosp_root: str
    safe_to_execute: bool
    blockers: tuple[str, ...]
    files: tuple[PlannedImportFile, ...]


class AospProductImportError(RuntimeError):
    pass


def create_aosp_product_import_report(
    *,
    aosp_root: Path,
    apk_path: Path | None = None,
    repo_root: Path = ROOT,
    mode: str = "plan",
) -> AospProductImportReport:
    blockers = list(validate_descriptors(repo_root))
    product_descriptor = load_json(repo_root / PRODUCT_DESCRIPTOR.relative_to(ROOT))
    system_descriptor = load_json(repo_root / SYSTEM_APP_DESCRIPTOR.relative_to(ROOT))

    resolved_apk_path = resolve_apk_path(
        apk_path=apk_path,
        source_apk=system_descriptor.get("source_apk"),
        repo_root=repo_root,
    )
    blockers.extend(apk_blockers(resolved_apk_path))

    files = tuple(
        planned_files(
            product_descriptor=product_descriptor,
            system_descriptor=system_descriptor,
            apk_path=resolved_apk_path,
            repo_root=repo_root,
        )
    )
    blockers.extend(missing_source_blockers(files))

    return AospProductImportReport(
        mode=mode,
        aosp_root=str(aosp_root),
        safe_to_execute=not blockers,
        blockers=tuple(blockers),
        files=files,
    )


def execute_aosp_product_import(
    report: AospProductImportReport,
    *,
    aosp_root: Path,
) -> AospProductImportReport:
    if report.blockers:
        raise AospProductImportError("cannot execute AOSP import while blockers exist")
    if not aosp_root.is_dir():
        raise AospProductImportError("AOSP root must be an existing directory in execute mode")

    executed_files: list[PlannedImportFile] = []
    resolved_root = aosp_root.resolve()
    for planned in report.files:
        source = Path(planned.source)
        destination = safe_destination(resolved_root, Path(planned.destination))
        source_bytes = source.read_bytes()
        if destination.exists():
            if destination.read_bytes() == source_bytes:
                executed_files.append(replace(planned, status="unchanged"))
                continue
            raise AospProductImportError(
                f"refusing to overwrite different existing file: {planned.destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_bytes)
        executed_files.append(replace(planned, status="copied"))

    return replace(report, mode="execute", files=tuple(executed_files))


def planned_files(
    *,
    product_descriptor: dict[str, Any],
    system_descriptor: dict[str, Any],
    apk_path: Path,
    repo_root: Path,
) -> list[PlannedImportFile]:
    return [
        planned_file(
            source=repo_file(product_descriptor.get("android_products_template"), repo_root),
            destination=PRODUCT_IMPORT_DIR / "AndroidProducts.mk",
        ),
        planned_file(
            source=repo_file(product_descriptor.get("product_makefile_template"), repo_root),
            destination=PRODUCT_IMPORT_DIR / "goffy_gsi_phone.mk",
        ),
        planned_file(
            source=repo_file(product_descriptor.get("packages_makefile_template"), repo_root),
            destination=PRODUCT_IMPORT_DIR / "goffy_product_packages.mk",
        ),
        planned_file(
            source=repo_file(system_descriptor.get("aosp_template"), repo_root),
            destination=APP_IMPORT_DIR / "Android.bp",
        ),
        planned_file(
            source=apk_path,
            destination=APP_IMPORT_DIR
            / str(system_descriptor.get("aosp_import_apk", "GoffyOS.apk")),
        ),
    ]


def planned_file(*, source: Path, destination: Path) -> PlannedImportFile:
    if source.is_file():
        source_hash = sha256_file(source)
        byte_count = source.stat().st_size
        apk_signature_schemes = (
            detect_apk_signature_schemes(source) if source.suffix == ".apk" else ()
        )
    else:
        source_hash = None
        byte_count = None
        apk_signature_schemes = ()
    return PlannedImportFile(
        source=str(source),
        destination=destination.as_posix(),
        sha256=source_hash,
        byte_count=byte_count,
        status="planned",
        apk_signature_schemes=apk_signature_schemes,
    )


def validate_descriptors(repo_root: Path) -> list[str]:
    findings: list[str] = []
    findings.extend(f"ROM system-app: {item}" for item in validate_rom_system_app(root=repo_root))
    findings.extend(
        f"ROM product overlay: {item}" for item in validate_rom_product_overlay(root=repo_root)
    )
    return findings


def resolve_apk_path(*, apk_path: Path | None, source_apk: object, repo_root: Path) -> Path:
    if apk_path is not None:
        return resolve_path(apk_path, repo_root)
    if not isinstance(source_apk, str):
        return repo_root / "android/app/build/outputs/apk/release/app-release-unsigned.apk"
    return resolve_path(Path(source_apk), repo_root)


def apk_blockers(path: Path) -> list[str]:
    blockers: list[str] = []
    if path.suffix != ".apk":
        blockers.append("GOFFY import artifact must be an APK")
    if "debug" in path.name.lower():
        blockers.append("GOFFY import APK must not be a debug build artifact")
    if path.name.endswith("-unsigned.apk"):
        blockers.append("GOFFY import APK must be externally signed before ROM import")
    if path.is_file() and path.stat().st_size <= 0:
        blockers.append("GOFFY import APK must not be empty")
    if path.is_file() and not detect_apk_signature_schemes(path):
        blockers.append("GOFFY import APK must contain an APK Signature Scheme v2/v3 block")
    return blockers


def detect_apk_signature_schemes(path: Path) -> tuple[str, ...]:
    data = path.read_bytes()
    eocd_offset = data.rfind(ZIP_EOCD_MAGIC)
    if eocd_offset < 0 or eocd_offset + 22 > len(data):
        return ()
    central_directory_offset = struct.unpack_from("<I", data, eocd_offset + 16)[0]
    if central_directory_offset < 32 or central_directory_offset > len(data):
        return ()
    if data[central_directory_offset - 16 : central_directory_offset] != APK_SIG_BLOCK_MAGIC:
        return ()
    block_size = struct.unpack_from("<Q", data, central_directory_offset - 24)[0]
    block_start = central_directory_offset - block_size - 8
    if block_start < 0:
        return ()
    leading_size = struct.unpack_from("<Q", data, block_start)[0]
    if leading_size != block_size:
        return ()

    schemes: list[str] = []
    pair_offset = block_start + 8
    pair_limit = central_directory_offset - 24
    while pair_offset < pair_limit:
        if pair_offset + 12 > pair_limit:
            return ()
        pair_size = struct.unpack_from("<Q", data, pair_offset)[0]
        pair_end = pair_offset + 8 + pair_size
        if pair_size < 4 or pair_end > pair_limit:
            return ()
        signature_id = struct.unpack_from("<I", data, pair_offset + 8)[0]
        if signature_id in APK_SIGNATURE_SCHEME_IDS:
            name = scheme_name(signature_id)
            if name not in schemes:
                schemes.append(name)
        pair_offset = pair_end
    return tuple(schemes)


def scheme_name(signature_id: int) -> str:
    if signature_id == 0x7109871A:
        return "v2"
    if signature_id == 0xF05368C0:
        return "v3"
    if signature_id == 0x1B93AD61:
        return "v3.1"
    return f"unknown:{signature_id:x}"


def missing_source_blockers(files: tuple[PlannedImportFile, ...]) -> list[str]:
    return [
        f"missing import source: {planned.source}"
        for planned in files
        if planned.sha256 is None or planned.byte_count is None
    ]


def safe_destination(aosp_root: Path, relative_destination: Path) -> Path:
    if relative_destination.is_absolute() or ".." in relative_destination.parts:
        raise AospProductImportError("destination paths must stay relative to the AOSP root")
    destination = (aosp_root / relative_destination).resolve()
    try:
        destination.relative_to(aosp_root)
    except ValueError as exc:
        raise AospProductImportError("destination escaped the AOSP root") from exc
    return destination


def repo_file(value: object, repo_root: Path) -> Path:
    if not isinstance(value, str) or not value:
        return repo_root / "<missing>"
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return repo_root / "<unsafe>"
    return repo_root / path


def resolve_path(path: Path, repo_root: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AospProductImportError(f"{path} must contain a JSON object")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_report(report: AospProductImportReport, *, as_json: bool) -> str:
    if as_json:
        return json.dumps(asdict(report), indent=2, sort_keys=True)
    lines = [
        "GOFFY AOSP product import",
        f"mode: {report.mode}",
        f"aosp root: {report.aosp_root}",
        f"safe to execute: {str(report.safe_to_execute).lower()}",
    ]
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    lines.append("files:")
    for planned in report.files:
        size = "missing" if planned.byte_count is None else f"{planned.byte_count} bytes"
        signatures = (
            f", apk signatures={','.join(planned.apk_signature_schemes)}"
            if planned.apk_signature_schemes
            else ""
        )
        lines.append(
            f"- {planned.destination} <- {planned.source} [{planned.status}, {size}{signatures}]"
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or execute a safe GOFFY AOSP product import plan.",
    )
    parser.add_argument("--aosp-root", type=Path, required=True)
    parser.add_argument("--apk", type=Path, default=None, help="Externally signed GOFFY APK.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-aosp-tree-mutation", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    mode = "execute" if args.execute else "plan"
    try:
        report = create_aosp_product_import_report(
            aosp_root=args.aosp_root,
            apk_path=args.apk,
            mode=mode,
        )
        if args.execute:
            if not args.confirm_aosp_tree_mutation:
                raise AospProductImportError("--execute requires --confirm-aosp-tree-mutation")
            report = execute_aosp_product_import(report, aosp_root=args.aosp_root)
    except (OSError, json.JSONDecodeError, AospProductImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(render_report(report, as_json=args.json))
    return 0 if report.safe_to_execute else 1


if __name__ == "__main__":
    raise SystemExit(main())
