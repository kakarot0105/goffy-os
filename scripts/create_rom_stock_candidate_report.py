from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_rom_stock_restore_evidence import write_output  # noqa: E402
from scripts.validate_rom_manual_gates import ARCHIVE_NAME_PATTERN  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.rom-stock-candidate-report.v1"
SUPPORTED_PROBE_SCHEMA = "goffy.rom-feasibility-probe.v1"
MAX_CANDIDATES = 128


class CandidateReportStatus(StrEnum):
    BLOCKED_NO_EXACT_STOCK_ARCHIVE = "BLOCKED_NO_EXACT_STOCK_ARCHIVE"
    BUILD_ID_NAME_FOUND_NEEDS_VARIANT_HASH = "BUILD_ID_NAME_FOUND_NEEDS_VARIANT_HASH"


class CandidateMatchStatus(StrEnum):
    CODENAME_AND_BUILD_ID_PRESENT = "CODENAME_AND_BUILD_ID_PRESENT"
    RELATED_KANSAS_NEARBY_BUILD = "RELATED_KANSAS_NEARBY_BUILD"
    UNRELATED_OR_INSUFFICIENT = "UNRELATED_OR_INSUFFICIENT"


@dataclass(frozen=True)
class StockCandidateAssessment:
    archive_name: str
    source_url: str
    match_status: CandidateMatchStatus
    rollback_evidence: bool
    rationale: str


@dataclass(frozen=True)
class StockCandidateReport:
    schema_version: str
    generated_at: str
    ok: bool
    status: CandidateReportStatus
    device: dict[str, str]
    required_match: dict[str, str]
    candidates: tuple[StockCandidateAssessment, ...]
    blockers: tuple[str, ...]
    next_steps: tuple[str, ...]


def load_probe_json(path: Path) -> dict[str, Any]:
    text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("probe JSON must be an object")
    schema = payload.get("schema_version")
    if schema != SUPPORTED_PROBE_SCHEMA:
        raise ValueError(f"unsupported probe schema {schema!r}; expected {SUPPORTED_PROBE_SCHEMA}")
    return payload


def build_report(
    probe: Mapping[str, Any],
    *,
    candidate_names: Iterable[str],
    source_url: str = "",
) -> StockCandidateReport:
    candidates = normalize_candidates(candidate_names)
    source = normalize_source_url(source_url)
    device = compact_device(probe)
    required = required_match(probe)
    build_id = required.get("installed_build_id", "")
    codename = required.get("codename", "")

    blockers: list[str] = []
    if not build_id:
        blockers.append("installed build ID could not be parsed from ro.build.fingerprint")
    if not codename:
        blockers.append("device codename is missing from probe JSON")
    if not candidates:
        blockers.append("no stock firmware archive candidates were provided")

    assessments = tuple(
        assess_candidate(name, source_url=source, codename=codename, build_id=build_id)
        for name in candidates
    )
    has_build_id_name = any(
        item.match_status is CandidateMatchStatus.CODENAME_AND_BUILD_ID_PRESENT
        for item in assessments
    )
    if has_build_id_name:
        status = CandidateReportStatus.BUILD_ID_NAME_FOUND_NEEDS_VARIANT_HASH
        blockers.append(
            "archive name contains the installed build ID, but still needs variant "
            "confirmation, a trusted source check, local archive, SHA-256, and rollback "
            "document before it can become stock_restore evidence"
        )
    else:
        status = CandidateReportStatus.BLOCKED_NO_EXACT_STOCK_ARCHIVE
        if build_id:
            blockers.append(
                f"no candidate archive name contained the installed build ID {build_id}"
            )

    return StockCandidateReport(
        schema_version=JSON_SCHEMA_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        ok=False,
        status=status,
        device=device,
        required_match=required,
        candidates=assessments,
        blockers=tuple(dict.fromkeys(blockers)),
        next_steps=(
            "Use Motorola Software Fix or carrier/Motorola repair tooling to obtain "
            "the exact archive.",
            "Run create_rom_stock_restore_evidence.py only after the exact archive "
            "is downloaded locally.",
            "Do not seed manual gates from nearby firmware names or unverifiable mirrors.",
        ),
    )


def normalize_candidates(candidate_names: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_name in candidate_names:
        name = raw_name.strip()
        if not name or name.startswith("#"):
            continue
        if not ARCHIVE_NAME_PATTERN.fullmatch(name):
            raise ValueError(f"candidate archive name is invalid: {name!r}")
        normalized.append(name)
    deduped = tuple(dict.fromkeys(normalized))
    if len(deduped) > MAX_CANDIDATES:
        raise ValueError(f"candidate count exceeds limit of {MAX_CANDIDATES}")
    return deduped


def normalize_source_url(source_url: str) -> str:
    source = source_url.strip()
    if not source:
        return ""
    parsed = urlsplit(source)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("source URL must be https")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise ValueError("source URL must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("source URL must not include query or fragment")
    return source


def assess_candidate(
    archive_name: str,
    *,
    source_url: str,
    codename: str,
    build_id: str,
) -> StockCandidateAssessment:
    has_codename = token_present(archive_name, codename)
    has_build = token_present(archive_name, build_id)
    if has_codename and has_build:
        status = CandidateMatchStatus.CODENAME_AND_BUILD_ID_PRESENT
        rationale = (
            "archive name contains the target codename and installed build ID; "
            "this is only a filename candidate until variant, source, local SHA-256, "
            "and rollback docs are recorded"
        )
    elif has_codename:
        status = CandidateMatchStatus.RELATED_KANSAS_NEARBY_BUILD
        rationale = (
            "archive name contains the target codename but not the installed build ID; "
            "nearby firmware is not rollback evidence"
        )
    else:
        status = CandidateMatchStatus.UNRELATED_OR_INSUFFICIENT
        rationale = "archive name does not prove a match to this target device"
    return StockCandidateAssessment(
        archive_name=archive_name,
        source_url=source_url,
        match_status=status,
        rollback_evidence=False,
        rationale=rationale,
    )


def token_present(text: str, token: str) -> bool:
    if not token:
        return False
    pattern = re.compile(
        rf"(?<![A-Z0-9]){re.escape(token.upper())}(?![A-Z0-9])",
        flags=re.IGNORECASE,
    )
    return pattern.search(text) is not None


def compact_device(probe: Mapping[str, Any]) -> dict[str, str]:
    device = mapping_value(probe.get("device"))
    platform = mapping_value(probe.get("platform"))
    return {
        "model": device.get("model", ""),
        "codename": device.get("codename", ""),
        "product": device.get("product", ""),
        "carrier": device.get("carrier", ""),
        "android_release": platform.get("android_release", ""),
        "build_incremental": platform.get("build_incremental", ""),
        "build_security_patch": platform.get("build_security_patch", ""),
    }


def required_match(probe: Mapping[str, Any]) -> dict[str, str]:
    device = mapping_value(probe.get("device"))
    platform = mapping_value(probe.get("platform"))
    properties = mapping_value(probe.get("properties"))
    fingerprint = properties.get("ro.build.fingerprint", "")
    return {
        "codename": device.get("codename", ""),
        "product": device.get("product", ""),
        "android_release": platform.get("android_release", ""),
        "installed_build_id": parse_build_id_from_fingerprint(fingerprint),
        "build_incremental": platform.get("build_incremental", ""),
        "fingerprint": fingerprint,
    }


def parse_build_id_from_fingerprint(fingerprint: str) -> str:
    try:
        platform_part = fingerprint.split(":", maxsplit=2)[1]
        return platform_part.split("/", maxsplit=2)[1]
    except IndexError:
        return ""


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def load_candidate_file(path: Path) -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def render_json(report: StockCandidateReport) -> str:
    return json.dumps(asdict(report), indent=2) + "\n"


def render_markdown(report: StockCandidateReport) -> str:
    lines = [
        "# GOFFY ROM Stock Candidate Report",
        "",
        f"- Schema: `{report.schema_version}`",
        f"- Status: `{report.status}`",
        "- Rollback evidence ready: `false`",
        "",
        "## Required Match",
    ]
    for key, value in report.required_match.items():
        lines.append(f"- {key}: `{value or 'unknown'}`")
    lines.extend(("", "## Candidates"))
    if not report.candidates:
        lines.append("- none")
    for candidate in report.candidates:
        lines.append(f"- `{candidate.archive_name}`")
        lines.append(f"  Status: `{candidate.match_status}`")
        if candidate.source_url:
            lines.append(f"  Source: {candidate.source_url}")
        lines.append(f"  Rollback evidence: `{str(candidate.rollback_evidence).lower()}`")
        lines.append(f"  Rationale: {candidate.rationale}")
    if report.blockers:
        lines.extend(("", "## Blockers"))
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    lines.extend(("", "## Next Steps"))
    lines.extend(f"- {step}" for step in report.next_steps)
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare stock firmware archive names against the connected Moto ROM probe "
            "without downloading or flashing anything."
        ),
    )
    parser.add_argument("probe_json", type=Path, help="Probe JSON path, or '-' for stdin.")
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        help="Candidate firmware archive filename. May be passed more than once.",
    )
    parser.add_argument(
        "--candidates-file",
        type=Path,
        help="Optional text file containing one candidate archive filename per line.",
    )
    parser.add_argument(
        "--source-url",
        default="",
        help="Optional HTTPS source URL shared by all candidate filenames.",
    )
    parser.add_argument("--json", action="store_true", help="Emit structured JSON.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path under .goffy-validation; stdout is used when omitted.",
    )
    return parser.parse_args(argv)


def candidate_names_from_args(args: argparse.Namespace) -> tuple[str, ...]:
    names: list[str] = list(args.candidate)
    if args.candidates_file is not None:
        names.extend(load_candidate_file(args.candidates_file))
    return tuple(names)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.output is not None and args.output.suffix == ".json" and not args.json:
            raise ValueError("--json is required when writing to a .json output path")
        probe = load_probe_json(args.probe_json)
        report = build_report(
            probe,
            candidate_names=candidate_names_from_args(args),
            source_url=args.source_url,
        )
        text = render_json(report) if args.json else render_markdown(report)
        if args.output is None:
            print(text, end="")
        else:
            write_output(args.output, text)
            print(f"wrote stock candidate report to {args.output}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
