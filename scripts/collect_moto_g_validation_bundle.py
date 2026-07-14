from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = ROOT / "protocol" / "python"
if __package__ in {None, ""}:
    for import_root in (ROOT, PROTOCOL_ROOT):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

import scripts.guide_moto_g_validation as guide  # noqa: E402
import scripts.record_moto_g_smoke as smoke  # noqa: E402
from scripts.verify_moto_g_readiness import existing_directory  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.moto-g-validation-bundle.v1"
DEFAULT_OUTPUT_ROOT = ROOT / ".goffy-validation"
BUNDLE_MARKER = ".goffy-validation-bundle"


class BundleExistsError(RuntimeError):
    pass


@dataclass(frozen=True)
class BundleFile:
    relative_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class MetadataFile:
    relative_path: str
    role: str


@dataclass(frozen=True)
class ValidationBundle:
    schema_version: str
    created_utc: str
    bundle_name: str
    output_directory: Path
    ok: bool
    next_step_id: str | None
    artifact_files: tuple[BundleFile, ...]
    metadata_files: tuple[MetadataFile, ...]


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bundle_name(timestamp_utc: str) -> str:
    compact = (
        timestamp_utc.replace("-", "").replace(":", "").replace("+0000", "Z").replace("+00:00", "Z")
    )
    if compact.endswith("Z"):
        compact = compact[:-1] + "Z"
    safe = "".join(char for char in compact if char.isalnum() or char in {"T", "Z"})
    return f"moto-g-{safe}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def file_entry(root: Path, path: Path) -> BundleFile:
    return BundleFile(
        relative_path=path.relative_to(root).as_posix(),
        size_bytes=path.stat().st_size,
        sha256=sha256_file(path),
    )


def ensure_force_safe(bundle_dir: Path) -> None:
    if bundle_dir.is_symlink():
        raise BundleExistsError(f"refusing to overwrite symlinked bundle path: {bundle_dir}")
    marker = bundle_dir / BUNDLE_MARKER
    if marker.is_symlink() or not marker.is_file():
        raise BundleExistsError(
            f"refusing to overwrite unmarked directory: {bundle_dir}. "
            "Choose a different --output-root or remove it manually after inspection."
        )


def bundle_file_payload(file: BundleFile) -> dict[str, Any]:
    return {
        "relativePath": file.relative_path,
        "sizeBytes": file.size_bytes,
        "sha256": file.sha256,
    }


def metadata_file_payload(file: MetadataFile) -> dict[str, str]:
    return {
        "relativePath": file.relative_path,
        "role": file.role,
    }


def manifest_payload(bundle: ValidationBundle) -> dict[str, Any]:
    return {
        "schemaVersion": bundle.schema_version,
        "createdUtc": bundle.created_utc,
        "bundleName": bundle.bundle_name,
        "ok": bundle.ok,
        "nextStepId": bundle.next_step_id,
        "localOnly": True,
        "phoneMutation": False,
        "artifactFiles": [bundle_file_payload(file) for file in bundle.artifact_files],
        "metadataFiles": [metadata_file_payload(file) for file in bundle.metadata_files],
    }


def render_manifest(bundle: ValidationBundle) -> str:
    return json.dumps(manifest_payload(bundle), indent=2, sort_keys=True)


def render_text(bundle: ValidationBundle) -> str:
    lines = ["GOFFY Moto G validation bundle"]
    lines.append(f"bundle: {bundle.bundle_name}")
    lines.append(f"bundle-directory: {bundle.output_directory}")
    lines.append(f"overall: {'passed' if bundle.ok else 'not-passed'}")
    lines.append(f"next-step: {bundle.next_step_id or 'none'}")
    lines.append("local-only: true")
    lines.append("phone-mutation: false")
    lines.append("")
    lines.append("artifact files:")
    for artifact in bundle.artifact_files:
        lines.append(
            f"- {artifact.relative_path} size={artifact.size_bytes} sha256={artifact.sha256}"
        )
    lines.append("metadata files:")
    for metadata in bundle.metadata_files:
        lines.append(f"- {metadata.relative_path} role={metadata.role}")
    lines.append("")
    if bundle.ok:
        lines.append("Physical Moto G validation evidence is complete.")
    else:
        lines.append("Bundle captured current evidence; follow the next non-DONE guide step.")
    return "\n".join(lines)


def collect_bundle(
    *,
    root: Path = ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    manual: smoke.ManualSmokeEvidence | None = None,
    timestamp_utc: str | None = None,
    report: guide.GuideReport | None = None,
    force: bool = False,
) -> ValidationBundle:
    created_utc = timestamp_utc or utc_timestamp()
    name = bundle_name(created_utc)
    bundle_dir = output_root / name

    if bundle_dir.exists():
        if not force:
            raise BundleExistsError(f"validation bundle already exists: {bundle_dir}")
        ensure_force_safe(bundle_dir)
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)
    bundle_dir.chmod(0o700)

    validation_report = report or guide.build_report(root=root.resolve(), manual=manual)
    artifacts = {
        "guide.json": guide.render_json(validation_report),
        "guide.txt": guide.render_text(validation_report),
        "smoke.json": smoke.render_json(validation_report.record),
        "smoke.txt": smoke.render_text(validation_report.record),
    }
    for filename, content in artifacts.items():
        write_text(bundle_dir / filename, content)
    write_text(bundle_dir / BUNDLE_MARKER, f"{JSON_SCHEMA_VERSION}\n")

    bundle_without_manifest = ValidationBundle(
        schema_version=JSON_SCHEMA_VERSION,
        created_utc=created_utc,
        bundle_name=name,
        output_directory=bundle_dir,
        ok=validation_report.ok,
        next_step_id=validation_report.next_step_id,
        artifact_files=tuple(
            file_entry(bundle_dir, bundle_dir / filename) for filename in artifacts
        ),
        metadata_files=(
            MetadataFile("manifest.json", "bundle manifest"),
            MetadataFile(BUNDLE_MARKER, "force-overwrite safety marker"),
        ),
    )
    write_text(bundle_dir / "manifest.json", render_manifest(bundle_without_manifest))
    return bundle_without_manifest


def manual_from_args(args: argparse.Namespace) -> smoke.ManualSmokeEvidence:
    return smoke.ManualSmokeEvidence(
        app_launched=args.app_launched,
        command_submitted=args.command_submitted,
        mac_status_displayed=args.mac_status_displayed,
        timeline_recorded=args.timeline_recorded,
        restart_restored=args.restart_restored,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=existing_directory, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--force", action="store_true", help="Overwrite the timestamped bundle.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--app-launched",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    parser.add_argument(
        "--command-submitted",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    parser.add_argument(
        "--mac-status-displayed",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    parser.add_argument(
        "--timeline-recorded",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    parser.add_argument(
        "--restart-restored",
        type=smoke.manual_status,
        default=smoke.ManualStatus.NOT_RUN,
    )
    args = parser.parse_args(argv)

    try:
        bundle = collect_bundle(
            root=args.repo_root,
            output_root=args.output_root,
            manual=manual_from_args(args),
            force=args.force,
        )
    except BundleExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(render_manifest(bundle) if args.json else render_text(bundle))
    return 0 if bundle.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
