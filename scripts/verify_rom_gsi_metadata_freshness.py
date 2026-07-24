from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_gsi_candidate_evidence import (  # noqa: E402
    ARTIFACT_FAMILY_ARCHITECTURES,
    DEFAULT_ANDROID16_GSI_ARCHITECTURE,
    DEFAULT_ANDROID16_GSI_ARTIFACT_NAME,
    DEFAULT_ANDROID16_GSI_DOWNLOAD_URL,
    DEFAULT_ANDROID16_GSI_RELEASE,
    DEFAULT_ANDROID16_GSI_SHA256,
    OFFICIAL_GSI_RELEASES_URL,
    build_matches_android_release,
    parse_gsi_artifact_name,
    validate_official_download_url,
    validate_official_source_url,
)

JSON_SCHEMA_VERSION = "goffy.rom-gsi-metadata-freshness.v1"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RELEASES_PAGE_BYTES = 4 * 1024 * 1024
DEFAULT_ANDROID16_GSI_SECTION_TITLE = "Android 16 QPR3 (Beta)"
ANDROID_GSI_SECTION_PATTERN = r"<h2\b[^>]*>\s*Android\s+{android_release}\s+GSIs\s*</h2>"
NEXT_ANDROID_GSI_SECTION_PATTERN = r"<h2\b[^>]*>\s*Android\s+\d+\s+GSIs\s*</h2>"
ANDROID_GSI_SUBSECTION_PATTERN = re.compile(
    r"<h3\b[^>]*>\s*(?P<title>Android\s+\d+[^<]*)\s*</h3>",
    flags=re.IGNORECASE,
)
ANDROID_ARM64_ARTIFACT_PATTERN = re.compile(
    r"<button\b[^>]*>\s*"
    r"(?P<artifact>aosp_arm64-exp-[^<\s]+\.zip)"
    r"\s*</button>\s*<br\s*/?>\s*"
    r"<code\b[^>]*>\s*(?P<sha256>[a-f0-9]{64})\s*</code>",
    flags=re.IGNORECASE | re.DOTALL,
)

Fetcher = Callable[[str, int], str]


class GsiMetadataFreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    INVALID_EXPECTED_METADATA = "INVALID_EXPECTED_METADATA"
    INVALID_OFFICIAL_METADATA = "INVALID_OFFICIAL_METADATA"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


@dataclass(frozen=True)
class GsiMetadataCandidate:
    artifact_name: str
    sha256: str
    download_url: str
    android_release: str
    architecture: str
    section_title: str


@dataclass(frozen=True)
class GsiMetadataSafety:
    execution_authority: str
    artifact_downloaded: bool
    device_mutation: str
    authorization: str
    destructive_actions: str


@dataclass(frozen=True)
class GsiMetadataFreshnessReport:
    schema_version: str
    generated_at: str
    ok: bool
    status: GsiMetadataFreshnessStatus
    source_url: str
    expected: GsiMetadataCandidate
    observed: GsiMetadataCandidate | None
    blockers: tuple[str, ...]
    safety: GsiMetadataSafety


def default_fetcher(url: str, timeout_seconds: int) -> str:
    source_findings = validate_official_source_url(url)
    if source_findings:
        raise ValueError("; ".join(source_findings))
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={"User-Agent": "GOFFY-OS-ROM-metadata-check"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            raise ValueError("official GSI releases response must be text/html")
        payload: bytes = response.read(MAX_RELEASES_PAGE_BYTES + 1)
    if len(payload) > MAX_RELEASES_PAGE_BYTES:
        raise ValueError("official GSI releases response is unexpectedly large")
    return payload.decode("utf-8", errors="replace")


def expected_android16_candidate() -> GsiMetadataCandidate:
    return GsiMetadataCandidate(
        artifact_name=DEFAULT_ANDROID16_GSI_ARTIFACT_NAME,
        sha256=DEFAULT_ANDROID16_GSI_SHA256,
        download_url=DEFAULT_ANDROID16_GSI_DOWNLOAD_URL,
        android_release=DEFAULT_ANDROID16_GSI_RELEASE,
        architecture=DEFAULT_ANDROID16_GSI_ARCHITECTURE,
        section_title=DEFAULT_ANDROID16_GSI_SECTION_TITLE,
    )


def verify_rom_gsi_metadata_freshness(
    *,
    fetcher: Fetcher = default_fetcher,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    page_text: str | None = None,
) -> GsiMetadataFreshnessReport:
    expected = expected_android16_candidate()
    expected_blockers = validate_candidate_metadata(expected, label="expected")
    if expected_blockers:
        return freshness_report(
            status=GsiMetadataFreshnessStatus.INVALID_EXPECTED_METADATA,
            expected=expected,
            observed=None,
            blockers=expected_blockers,
        )

    try:
        source_text = (
            page_text
            if page_text is not None
            else fetcher(OFFICIAL_GSI_RELEASES_URL, min(timeout_seconds, DEFAULT_TIMEOUT_SECONDS))
        )
    except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
        return freshness_report(
            status=GsiMetadataFreshnessStatus.SOURCE_UNAVAILABLE,
            expected=expected,
            observed=None,
            blockers=(safe_source_error(exc),),
        )

    try:
        observed = latest_android_arm64_gsi_candidate(
            source_text,
            android_release=DEFAULT_ANDROID16_GSI_RELEASE,
        )
    except ValueError as exc:
        return freshness_report(
            status=GsiMetadataFreshnessStatus.INVALID_OFFICIAL_METADATA,
            expected=expected,
            observed=None,
            blockers=(str(exc),),
        )

    official_blockers = validate_candidate_metadata(observed, label="official")
    if official_blockers:
        return freshness_report(
            status=GsiMetadataFreshnessStatus.INVALID_OFFICIAL_METADATA,
            expected=expected,
            observed=observed,
            blockers=official_blockers,
        )

    freshness_blockers = compare_candidates(expected=expected, observed=observed)
    return freshness_report(
        status=(
            GsiMetadataFreshnessStatus.FRESH
            if not freshness_blockers
            else GsiMetadataFreshnessStatus.STALE
        ),
        expected=expected,
        observed=observed,
        blockers=freshness_blockers,
    )


def latest_android_arm64_gsi_candidate(
    page_text: str,
    *,
    android_release: str,
) -> GsiMetadataCandidate:
    section = android_gsi_section(page_text, android_release=android_release)
    subsection_title, subsection = latest_android_gsi_subsection(
        section,
        android_release=android_release,
    )
    match = ANDROID_ARM64_ARTIFACT_PATTERN.search(subsection)
    if match is None:
        raise ValueError(
            f"official Android {android_release} ARM64 GSI entry was not found "
            f"in subsection {subsection_title}"
        )

    artifact_name = unescape(match.group("artifact")).strip()
    sha256 = match.group("sha256").lower()
    return GsiMetadataCandidate(
        artifact_name=artifact_name,
        sha256=sha256,
        download_url=download_url_for_artifact(artifact_name),
        android_release=android_release,
        architecture=DEFAULT_ANDROID16_GSI_ARCHITECTURE,
        section_title=subsection_title,
    )


def android_gsi_section(page_text: str, *, android_release: str) -> str:
    heading = re.search(
        ANDROID_GSI_SECTION_PATTERN.format(android_release=re.escape(android_release)),
        page_text,
        flags=re.IGNORECASE,
    )
    if heading is None:
        raise ValueError(f"official Android {android_release} GSI section was not found")

    start = heading.end()
    next_heading = re.search(
        NEXT_ANDROID_GSI_SECTION_PATTERN,
        page_text[start:],
        flags=re.IGNORECASE,
    )
    end = start + next_heading.start() if next_heading is not None else len(page_text)
    return page_text[start:end]


def latest_android_gsi_subsection(section: str, *, android_release: str) -> tuple[str, str]:
    matches = tuple(ANDROID_GSI_SUBSECTION_PATTERN.finditer(section))
    for index, match in enumerate(matches):
        title = clean_heading_text(match.group("title"))
        if not title.startswith(f"Android {android_release}"):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        return title, section[start:end]
    raise ValueError(f"official Android {android_release} GSI subsection was not found")


def clean_heading_text(value: str) -> str:
    return " ".join(unescape(value).split())


def download_url_for_artifact(artifact_name: str) -> str:
    directory = DEFAULT_ANDROID16_GSI_DOWNLOAD_URL.rsplit("/", 1)[0]
    return f"{directory}/{artifact_name}"


def validate_candidate_metadata(candidate: GsiMetadataCandidate, *, label: str) -> tuple[str, ...]:
    blockers: list[str] = []
    source_findings = validate_official_source_url(OFFICIAL_GSI_RELEASES_URL)
    blockers.extend(f"{label}: {finding}" for finding in source_findings)
    download_findings = validate_official_download_url(
        candidate.download_url,
        expected_name=candidate.artifact_name,
    )
    blockers.extend(f"{label}: {finding}" for finding in download_findings)

    metadata = parse_gsi_artifact_name(candidate.artifact_name)
    if metadata is None:
        blockers.append(f"{label}: artifact name does not match official GSI naming")
        return tuple(dict.fromkeys(blockers))

    artifact_architecture = ARTIFACT_FAMILY_ARCHITECTURES[metadata["family"].lower()]
    if artifact_architecture != candidate.architecture:
        blockers.append(f"{label}: artifact architecture does not match {candidate.architecture}")
    if not build_matches_android_release(
        build_id=metadata["build"],
        android_release=candidate.android_release,
    ):
        blockers.append(
            f"{label}: artifact build does not match Android {candidate.android_release}"
        )
    if not candidate.sha256.lower().startswith(metadata["sha_prefix"].lower()):
        blockers.append(f"{label}: artifact checksum prefix does not match SHA-256")
    return tuple(dict.fromkeys(blockers))


def compare_candidates(
    *,
    expected: GsiMetadataCandidate,
    observed: GsiMetadataCandidate,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if expected.section_title != observed.section_title:
        blockers.append(
            "selected Android 16 ARM64 GSI subsection is stale: "
            f"expected {expected.section_title}, official page has {observed.section_title}"
        )
    if expected.artifact_name != observed.artifact_name:
        blockers.append(
            "selected Android 16 ARM64 GSI artifact is stale: "
            f"expected {expected.artifact_name}, official page has {observed.artifact_name}"
        )
    if expected.sha256.lower() != observed.sha256.lower():
        blockers.append(
            "selected Android 16 ARM64 GSI SHA-256 is stale: "
            f"expected {expected.sha256.lower()}, official page has {observed.sha256.lower()}"
        )
    return tuple(dict.fromkeys(blockers))


def freshness_report(
    *,
    status: GsiMetadataFreshnessStatus,
    expected: GsiMetadataCandidate,
    observed: GsiMetadataCandidate | None,
    blockers: tuple[str, ...],
) -> GsiMetadataFreshnessReport:
    return GsiMetadataFreshnessReport(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=status is GsiMetadataFreshnessStatus.FRESH,
        status=status,
        source_url=OFFICIAL_GSI_RELEASES_URL,
        expected=expected,
        observed=observed,
        blockers=blockers,
        safety=GsiMetadataSafety(
            execution_authority="OFFICIAL_METADATA_READ_ONLY",
            artifact_downloaded=False,
            device_mutation="NONE",
            authorization="NON_AUTHORIZING_EVIDENCE",
            destructive_actions="WITHHELD",
        ),
    )


def safe_source_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        return "official GSI releases page could not be read"
    if isinstance(exc, TimeoutError):
        return "official GSI releases page read timed out"
    if isinstance(exc, OSError):
        return f"official GSI releases page read failed: errno {exc.errno}"
    return f"official GSI releases page read failed: {exc}"


def render_json(report: GsiMetadataFreshnessReport) -> str:
    return json.dumps(asdict(report), indent=2) + "\n"


def render_text(report: GsiMetadataFreshnessReport) -> str:
    lines = [
        "GOFFY ROM GSI metadata freshness",
        f"schema: {report.schema_version}",
        f"ok: {str(report.ok).lower()}",
        f"status: {report.status}",
        f"source: {report.source_url}",
        f"expected artifact: {report.expected.artifact_name}",
        f"expected sha256: {report.expected.sha256}",
        f"expected subsection: {report.expected.section_title}",
        f"observed artifact: {report.observed.artifact_name if report.observed else '<missing>'}",
        f"observed sha256: {report.observed.sha256 if report.observed else '<missing>'}",
        f"observed subsection: {report.observed.section_title if report.observed else '<missing>'}",
        f"artifact downloaded: {str(report.safety.artifact_downloaded).lower()}",
        f"device mutation: {report.safety.device_mutation}",
    ]
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the committed Android 16 ARM64 GSI metadata against Google's official "
            "GSI releases page without downloading artifacts or touching a device."
        ),
    )
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--source-html",
        type=Path,
        help="Optional local HTML fixture to parse instead of fetching the official page.",
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    parser.add_argument(
        "--allow-source-unavailable",
        action="store_true",
        help=(
            "Exit successfully only when the official source is unavailable. Stale or invalid "
            "metadata still fails."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        page_text = (
            args.source_html.read_text(encoding="utf-8", errors="replace")
            if args.source_html is not None
            else None
        )
    except OSError as exc:
        report = freshness_report(
            status=GsiMetadataFreshnessStatus.SOURCE_UNAVAILABLE,
            expected=expected_android16_candidate(),
            observed=None,
            blockers=(safe_source_error(exc),),
        )
        print(render_json(report) if args.json else render_text(report), end="")
        return 0 if args.allow_source_unavailable else 1

    report = verify_rom_gsi_metadata_freshness(
        timeout_seconds=args.timeout_seconds,
        page_text=page_text,
    )
    print(render_json(report) if args.json else render_text(report), end="")
    source_unavailable_allowed = (
        args.allow_source_unavailable
        and report.status is GsiMetadataFreshnessStatus.SOURCE_UNAVAILABLE
    )
    return 0 if report.ok or source_unavailable_allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
