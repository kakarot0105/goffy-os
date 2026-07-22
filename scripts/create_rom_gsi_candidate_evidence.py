from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_stock_restore_evidence import sha256_file, write_output  # noqa: E402
from scripts.validate_rom_manual_gates import (  # noqa: E402
    ARCHIVE_NAME_PATTERN,
    SHA256_PATTERN,
)

JSON_SCHEMA_VERSION = "goffy.rom-gsi-candidate-evidence.v1"
OFFICIAL_GSI_RELEASES_URL = "https://developer.android.com/topic/generic-system-image/releases"
OFFICIAL_GSI_DOWNLOAD_HOST = "dl.google.com"
OFFICIAL_GSI_RELEASE_DIRECTORIES = frozenset(("baklava", "cinnamonbun"))
MIN_TARGET_ANDROID_RELEASE = 16
SUPPORTED_ARCHITECTURES = {
    "arm64": "arm64",
    "aosp_arm64": "arm64",
    "arm64+gms": "arm64+gms",
    "gsi_gms_arm64": "arm64+gms",
}
SUPPORTED_IMAGE_KINDS = frozenset(("archive",))
SUPPORTED_LICENSE_NOTE_CODES = frozenset(("official_google_gsi_terms",))
CANDIDATE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 ._+@-]{1,120}$")
GSI_ARTIFACT_NAME_PATTERN = re.compile(
    r"^(?P<family>aosp_arm64|gsi_gms_arm64|aosp_x86_64|gsi_gms_x86_64)"
    r"-exp-(?P<build>[A-Z0-9.]+)-(?P<build_number>[0-9]+)-(?P<sha_prefix>[a-f0-9]{8})"
    r"\.zip$",
    flags=re.IGNORECASE,
)
ARTIFACT_FAMILY_ARCHITECTURES = {
    "aosp_arm64": "arm64",
    "gsi_gms_arm64": "arm64+gms",
    "aosp_x86_64": "x86_64",
    "gsi_gms_x86_64": "x86_64+gms",
}
ANDROID_RELEASE_BUILD_PREFIXES = {
    "16": ("BP", "CP11."),
    "17": ("CP2", "CP3"),
}
FORBIDDEN_CANDIDATE_NAME_TERMS = (
    "approve",
    "approved",
    "approves",
    "approving",
    "approval",
    "approvals",
    "authorize",
    "authorized",
    "authorizes",
    "authorizing",
    "authorization",
    "authorizations",
    "bootloader",
    "dsu",
    "erase",
    "erased",
    "erases",
    "erasing",
    "fastboot",
    "flash",
    "flashed",
    "flashes",
    "flashing",
    "install",
    "installed",
    "installing",
    "installs",
    "reboot",
    "rebooted",
    "rebooting",
    "reboots",
    "root",
    "rooted",
    "rooting",
    "roots",
    "unlock",
    "unlocked",
    "unlocking",
    "unlocks",
    "wipe",
    "wiped",
    "wipes",
    "wiping",
)


class GsiCandidateStatus(StrEnum):
    ARTIFACT_CHECKSUM_VERIFIED = "ARTIFACT_CHECKSUM_VERIFIED"


@dataclass(frozen=True)
class GsiCandidate:
    name: str
    android_release: str
    architecture: str
    image_kind: str
    license_note_code: str


@dataclass(frozen=True)
class GsiArtifact:
    artifact_name: str
    byte_count: int
    sha256: str
    expected_sha256: str


@dataclass(frozen=True)
class GsiSource:
    source_url: str
    download_url: str


@dataclass(frozen=True)
class GsiSafety:
    execution_authority: str
    device_mutation: str
    authorization: str
    destructive_actions: str
    local_path_redacted: bool


@dataclass(frozen=True)
class GsiCandidateEvidence:
    schema_version: str
    generated_at: str
    ok: bool
    status: GsiCandidateStatus
    candidate: GsiCandidate
    artifact: GsiArtifact
    source: GsiSource
    safety: GsiSafety


def create_gsi_candidate_evidence(
    *,
    artifact_path: Path,
    source_url: str,
    download_url: str,
    expected_sha256: str,
    candidate_name: str,
    android_release: str,
    architecture: str,
    image_kind: str = "archive",
    license_note_code: str = "official_google_gsi_terms",
    root: Path = ROOT,
) -> GsiCandidateEvidence:
    input_artifact = input_path_without_symlink_resolution(artifact_path, root=root)
    artifact = input_artifact.resolve()
    findings: list[str] = []
    try:
        normalized_sha = normalize_sha256(expected_sha256)
    except ValueError as exc:
        findings.append(str(exc))
        normalized_sha = expected_sha256.strip().lower()
    try:
        normalized_architecture = normalize_architecture(architecture)
    except ValueError as exc:
        findings.append(str(exc))
        normalized_architecture = architecture.strip().lower()
    try:
        normalized_release = normalize_android_release(android_release)
    except ValueError as exc:
        findings.append(str(exc))
        normalized_release = android_release.strip()

    findings.extend(
        validate_inputs(
            artifact_path=artifact,
            input_artifact_path=input_artifact,
            source_url=source_url,
            download_url=download_url,
            expected_sha256=normalized_sha,
            candidate_name=candidate_name,
            android_release=normalized_release,
            architecture=normalized_architecture,
            image_kind=image_kind,
            license_note_code=license_note_code,
            root=root,
        )
    )
    if findings:
        raise ValueError("; ".join(dict.fromkeys(findings)))

    computed_sha = sha256_file(artifact)
    if computed_sha != normalized_sha:
        raise ValueError(
            "artifact SHA-256 does not match expected official checksum: "
            f"computed {computed_sha}, expected {normalized_sha}"
        )

    return GsiCandidateEvidence(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=True,
        status=GsiCandidateStatus.ARTIFACT_CHECKSUM_VERIFIED,
        candidate=GsiCandidate(
            name=candidate_name,
            android_release=normalized_release,
            architecture=normalized_architecture,
            image_kind=image_kind,
            license_note_code=license_note_code,
        ),
        artifact=GsiArtifact(
            artifact_name=artifact.name,
            byte_count=artifact.stat().st_size,
            sha256=computed_sha,
            expected_sha256=normalized_sha,
        ),
        source=GsiSource(
            source_url=source_url,
            download_url=download_url,
        ),
        safety=GsiSafety(
            execution_authority="OFFLINE_HASH_ONLY",
            device_mutation="NONE",
            authorization="NON_AUTHORIZING_EVIDENCE",
            destructive_actions="WITHHELD",
            local_path_redacted=True,
        ),
    )


def validate_inputs(
    *,
    artifact_path: Path,
    input_artifact_path: Path,
    source_url: str,
    download_url: str,
    expected_sha256: str,
    candidate_name: str,
    android_release: str,
    architecture: str,
    image_kind: str,
    license_note_code: str,
    root: Path,
) -> list[str]:
    findings: list[str] = []
    repo_root = root.resolve()

    if not artifact_path.is_file():
        findings.append("artifact path must point to an existing file")
    if artifact_path.suffix != ".zip":
        findings.append("official Google GSI candidate artifact must be a .zip archive")
    if not ARCHIVE_NAME_PATTERN.fullmatch(artifact_path.name):
        findings.append("artifact filename contains unsupported characters")
    if path_is_inside(input_artifact_path, repo_root) or path_is_inside(artifact_path, repo_root):
        findings.append("artifact path must be outside the repo to avoid committing GSI images")
    artifact_metadata = parse_gsi_artifact_name(artifact_path.name)
    if artifact_metadata is None:
        findings.append("artifact filename must match the official Google GSI naming pattern")
    else:
        artifact_architecture = ARTIFACT_FAMILY_ARCHITECTURES[artifact_metadata["family"].lower()]
        if artifact_architecture != architecture:
            findings.append("artifact filename architecture must match candidate architecture")
        if not build_matches_android_release(
            build_id=artifact_metadata["build"],
            android_release=android_release,
        ):
            findings.append("artifact filename build must match candidate Android release")
        if not expected_sha256.startswith(artifact_metadata["sha_prefix"].lower()):
            findings.append("artifact filename checksum prefix must match expected SHA-256")

    findings.extend(validate_official_source_url(source_url))
    findings.extend(validate_official_download_url(download_url, expected_name=artifact_path.name))

    if not SHA256_PATTERN.fullmatch(expected_sha256):
        findings.append("expected SHA-256 must be 64 hex characters")
    if not CANDIDATE_NAME_PATTERN.fullmatch(candidate_name):
        findings.append("candidate name contains unsupported characters")
    if candidate_name_contains_action_word(candidate_name):
        findings.append("candidate name must not contain approval or device-action wording")
    if not android_release.isdigit():
        findings.append("candidate Android release must be numeric")
    elif int(android_release) < MIN_TARGET_ANDROID_RELEASE:
        findings.append("candidate Android release must be 16 or newer for the target Moto")
    if architecture not in frozenset(SUPPORTED_ARCHITECTURES.values()):
        findings.append("candidate architecture must be arm64 or arm64+gms")
    if image_kind not in SUPPORTED_IMAGE_KINDS:
        findings.append("candidate image kind must be archive")
    if license_note_code not in SUPPORTED_LICENSE_NOTE_CODES:
        findings.append("license note code must acknowledge official Google GSI terms")
    return findings


def normalize_sha256(value: str) -> str:
    normalized = value.strip().lower()
    if SHA256_PATTERN.fullmatch(normalized) is None:
        raise ValueError("expected SHA-256 must be 64 hex characters")
    return normalized


def normalize_android_release(value: str) -> str:
    normalized = value.strip()
    if not normalized.isdigit():
        raise ValueError("candidate Android release must be numeric")
    return normalized


def normalize_architecture(value: str) -> str:
    normalized = value.strip().lower()
    canonical = SUPPORTED_ARCHITECTURES.get(normalized)
    if canonical is None:
        raise ValueError("candidate architecture must be arm64 or arm64+gms")
    return canonical


def validate_official_source_url(source_url: str) -> list[str]:
    findings: list[str] = []
    parsed = urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.netloc:
        findings.append("source URL must be https")
    elif parsed.username or parsed.password or "@" in parsed.netloc:
        findings.append("source URL must not include credentials")
    elif parsed.query or parsed.fragment:
        findings.append("source URL must not include query or fragment")
    elif source_url != OFFICIAL_GSI_RELEASES_URL:
        findings.append("source URL must be the official Android GSI releases page")
    return findings


def validate_official_download_url(download_url: str, *, expected_name: str) -> list[str]:
    findings: list[str] = []
    parsed = urlsplit(download_url)
    if parsed.scheme != "https" or not parsed.netloc:
        findings.append("download URL must be https")
    elif parsed.username or parsed.password or "@" in parsed.netloc:
        findings.append("download URL must not include credentials")
    elif parsed.query or parsed.fragment:
        findings.append("download URL must not include query or fragment")
    elif parsed.netloc != OFFICIAL_GSI_DOWNLOAD_HOST:
        findings.append("download URL must use the official Google download host")
    elif not official_gsi_download_path(parsed.path, expected_name=expected_name):
        findings.append("download URL must be under the official Android GSI downloads path")
    return findings


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def parse_gsi_artifact_name(name: str) -> dict[str, str] | None:
    match = GSI_ARTIFACT_NAME_PATTERN.fullmatch(name)
    if match is None:
        return None
    return match.groupdict()


def build_matches_android_release(*, build_id: str, android_release: str) -> bool:
    prefixes = ANDROID_RELEASE_BUILD_PREFIXES.get(android_release)
    if prefixes is None:
        return False
    return build_id.upper().startswith(prefixes)


def official_gsi_download_path(path: str, *, expected_name: str) -> bool:
    parts = tuple(part for part in path.split("/") if part)
    if len(parts) != 6:
        return False
    developers, android, release, images, gsi, filename = parts
    return (
        developers == "developers"
        and android == "android"
        and release in OFFICIAL_GSI_RELEASE_DIRECTORIES
        and images == "images"
        and gsi == "gsi"
        and filename == expected_name
    )


def input_path_without_symlink_resolution(path: Path, *, root: Path) -> Path:
    expanded = path.expanduser()
    candidate = expanded if expanded.is_absolute() else root / expanded
    return Path(os.path.abspath(candidate))


def candidate_name_contains_action_word(candidate_name: str) -> bool:
    for term in FORBIDDEN_CANDIDATE_NAME_TERMS:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", candidate_name, re.I):
            return True
    return False


def safe_os_error_message(exc: OSError) -> str:
    if exc.errno is not None:
        return f"local filesystem operation failed: errno {exc.errno}"
    return f"local filesystem operation failed: {exc.__class__.__name__}"


def render_json(evidence: GsiCandidateEvidence) -> str:
    return json.dumps(asdict(evidence), indent=2) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create redacted GOFFY ROM GSI candidate evidence from a local official "
            "Google GSI archive without downloading, flashing, or touching a device."
        ),
    )
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--download-url", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--candidate-name", required=True)
    parser.add_argument("--android-release", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--image-kind", default="archive")
    parser.add_argument("--license-note-code", default="official_google_gsi_terms")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path under .goffy-validation; stdout is used when omitted.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT) -> int:
    args = parse_args(argv)
    try:
        evidence = create_gsi_candidate_evidence(
            artifact_path=args.artifact,
            source_url=args.source_url,
            download_url=args.download_url,
            expected_sha256=args.expected_sha256,
            candidate_name=args.candidate_name,
            android_release=args.android_release,
            architecture=args.architecture,
            image_kind=args.image_kind,
            license_note_code=args.license_note_code,
            root=root,
        )
        text = render_json(evidence)
        if args.output is None:
            print(text, end="")
        else:
            write_output(args.output, text, root=root)
            print(f"wrote GSI candidate evidence to {args.output}")
    except OSError as exc:
        print(f"error: {safe_os_error_message(exc)}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
