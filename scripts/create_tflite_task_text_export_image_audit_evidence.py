from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_tflite_task_text_model_maker_docker import (  # noqa: E402
    IMAGE_AUDIT_SCHEMA_VERSION,
    IMAGE_DIGEST,
)
from scripts.verify_tflite_task_text_training_environment import sha256_file  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.tflite-task-text-export-image-audit-report.v1"
SUPPORTED_SCANNERS = ("auto", "trivy", "grype")
SEVERITIES = ("critical", "high", "medium", "low", "negligible", "unknown")
BLOCKING_SEVERITIES = ("critical", "high", "medium")


class StepStatus(StrEnum):
    OK = "OK"
    FAIL = "FAIL"


@dataclass(frozen=True)
class AuditEvidenceStep:
    name: str
    status: StepStatus
    detail: str = ""


@dataclass(frozen=True)
class ExportImageAuditEvidenceReport:
    schema_version: str
    ok: bool
    status: str
    image: str
    scanner: str | None
    scanner_report: str | None
    scanner_report_sha256: str | None
    output: str | None
    evidence: dict[str, object] | None
    steps: tuple[AuditEvidenceStep, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def build_report(
    *,
    image: str,
    scanner_report: Path,
    scanner: str = "auto",
    output: Path | None = None,
    write: bool = False,
) -> ExportImageAuditEvidenceReport:
    steps: list[AuditEvidenceStep] = []
    blockers: list[str] = []
    warnings: list[str] = []

    if IMAGE_DIGEST.fullmatch(image) is None:
        blockers.append("image must be immutable and pinned by sha256 digest")

    if scanner not in SUPPORTED_SCANNERS:
        blockers.append(f"scanner must be one of {', '.join(SUPPORTED_SCANNERS)}")

    resolved_report = scanner_report.expanduser().resolve()
    report_sha: str | None = None
    payload: object | None = None
    if not resolved_report.is_file():
        blockers.append("scanner report file is missing")
        steps.append(AuditEvidenceStep("Load scanner report", StepStatus.FAIL, "file is missing"))
    else:
        try:
            payload = json.loads(resolved_report.read_text(encoding="utf-8"))
            report_sha = sha256_file(resolved_report)
            steps.append(
                AuditEvidenceStep(
                    "Load scanner report",
                    StepStatus.OK,
                    "scanner report JSON loaded and hashed",
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            blockers.append(f"scanner report could not be read: {exc}")
            steps.append(AuditEvidenceStep("Load scanner report", StepStatus.FAIL, str(exc)))

    detected_scanner: str | None = None
    counts = {severity: 0 for severity in SEVERITIES}
    if payload is not None:
        detected_scanner, counts, image_identities, parse_warnings, parse_blockers = (
            parse_scanner_report(
                payload,
                requested_scanner=scanner,
            )
        )
        warnings.extend(parse_warnings)
        blockers.extend(parse_blockers)
        blockers.extend(
            validate_scanned_image_identity(
                image=image,
                identities=image_identities,
                scanner=detected_scanner,
            )
        )
        steps.append(
            AuditEvidenceStep(
                "Parse scanner report",
                StepStatus.OK if not parse_blockers else StepStatus.FAIL,
                f"scanner={detected_scanner or 'unknown'}",
            )
        )

    for severity in BLOCKING_SEVERITIES:
        if counts[severity] > 0:
            blockers.append(f"image audit has {counts[severity]} {severity} findings")

    evidence: dict[str, object] | None = None
    if not blockers:
        evidence = {
            "schema_version": IMAGE_AUDIT_SCHEMA_VERSION,
            "image": image,
            "ok": True,
            "scanner": detected_scanner,
            "scanned_image_identities": sorted(image_identities),
            "scanner_report": str(resolved_report),
            "scanner_report_sha256": report_sha,
            "vulnerability_counts": counts,
        }

    resolved_output = output.expanduser().resolve() if output is not None else None
    if write:
        if evidence is None:
            blockers.append("audit evidence was not written because the scan is blocked")
        elif resolved_output is None:
            blockers.append("output path is required when --write is used")
        else:
            try:
                resolved_output.parent.mkdir(parents=True, exist_ok=True)
                resolved_output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
                steps.append(
                    AuditEvidenceStep(
                        "Write audit evidence",
                        StepStatus.OK,
                        "wrote GOFFY image audit evidence",
                    )
                )
            except OSError as exc:
                blockers.append(f"audit evidence could not be written: {exc}")
                steps.append(AuditEvidenceStep("Write audit evidence", StepStatus.FAIL, str(exc)))

    deduped_blockers = tuple(dict.fromkeys(blockers))
    return ExportImageAuditEvidenceReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=not deduped_blockers,
        status="READY" if not deduped_blockers else "BLOCKED",
        image=image,
        scanner=detected_scanner,
        scanner_report=str(resolved_report) if scanner_report else None,
        scanner_report_sha256=report_sha,
        output=str(resolved_output) if resolved_output else None,
        evidence=evidence,
        steps=tuple(steps),
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def parse_scanner_report(
    payload: object,
    *,
    requested_scanner: str,
) -> tuple[str | None, dict[str, int], set[str], tuple[str, ...], tuple[str, ...]]:
    if requested_scanner == "trivy":
        return parse_trivy_report(payload)
    if requested_scanner == "grype":
        return parse_grype_report(payload)
    trivy = parse_trivy_report(payload)
    if not trivy[3]:
        return trivy
    grype = parse_grype_report(payload)
    if not grype[3]:
        return grype
    return (
        None,
        {severity: 0 for severity in SEVERITIES},
        set(),
        (),
        ("scanner report was not recognized as Trivy or Grype JSON",),
    )


def parse_trivy_report(
    payload: object,
) -> tuple[str | None, dict[str, int], set[str], tuple[str, ...], tuple[str, ...]]:
    if not isinstance(payload, Mapping):
        return None, empty_counts(), set(), (), ("Trivy report must be a JSON object",)
    results = payload.get("Results")
    if not isinstance(results, list):
        return None, empty_counts(), set(), (), ("Trivy report must contain Results list",)

    counts = empty_counts()
    blockers: list[str] = []
    identities = extract_trivy_image_identities(payload)
    for result_index, result in enumerate(results):
        if not isinstance(result, Mapping):
            blockers.append(f"Results[{result_index}] must be an object")
            continue
        vulnerabilities = result.get("Vulnerabilities", [])
        if vulnerabilities is None:
            continue
        if not isinstance(vulnerabilities, list):
            blockers.append(f"Results[{result_index}].Vulnerabilities must be a list")
            continue
        for finding_index, finding in enumerate(vulnerabilities):
            severity = severity_from_mapping(finding)
            if severity is None:
                blockers.append(
                    f"Results[{result_index}].Vulnerabilities[{finding_index}] severity is missing"
                )
                counts["unknown"] += 1
            else:
                counts[severity] += 1
                if severity == "unknown":
                    blockers.append(
                        "Results"
                        f"[{result_index}].Vulnerabilities[{finding_index}] severity is unknown"
                    )
    return "trivy", counts, identities, (), tuple(blockers)


def parse_grype_report(
    payload: object,
) -> tuple[str | None, dict[str, int], set[str], tuple[str, ...], tuple[str, ...]]:
    if not isinstance(payload, Mapping):
        return None, empty_counts(), set(), (), ("Grype report must be a JSON object",)
    matches = payload.get("matches")
    if not isinstance(matches, list):
        return None, empty_counts(), set(), (), ("Grype report must contain matches list",)

    counts = empty_counts()
    blockers: list[str] = []
    identities = extract_grype_image_identities(payload)
    for index, match in enumerate(matches):
        if not isinstance(match, Mapping):
            blockers.append(f"matches[{index}] must be an object")
            counts["unknown"] += 1
            continue
        severity = severity_from_mapping(match.get("vulnerability"))
        if severity is None:
            severity = severity_from_mapping(match)
        if severity is None:
            blockers.append(f"matches[{index}] severity is missing")
            counts["unknown"] += 1
        else:
            counts[severity] += 1
            if severity == "unknown":
                blockers.append(f"matches[{index}] severity is unknown")
    return "grype", counts, identities, (), tuple(blockers)


def extract_trivy_image_identities(payload: Mapping[object, object]) -> set[str]:
    identities: set[str] = set()
    metadata = payload.get("Metadata")
    if isinstance(metadata, Mapping):
        add_string_list_identities(identities, metadata.get("RepoDigests"))
    return identities


def extract_grype_image_identities(payload: Mapping[object, object]) -> set[str]:
    identities: set[str] = set()
    source = payload.get("source")
    if not isinstance(source, Mapping):
        return identities
    target = source.get("target")
    if not isinstance(target, Mapping):
        return identities
    user_input = target.get("userInput")
    if isinstance(user_input, str) and IMAGE_DIGEST.fullmatch(user_input.strip()):
        add_string_identity(identities, user_input)
    add_string_identity(identities, target.get("manifestDigest"))
    add_string_list_identities(identities, target.get("repoDigests"))
    return identities


def add_string_identity(identities: set[str], value: object) -> None:
    if isinstance(value, str) and value.strip():
        identities.add(value.strip())


def add_string_list_identities(identities: set[str], value: object) -> None:
    if not isinstance(value, list):
        return
    for item in value:
        add_string_identity(identities, item)


def validate_scanned_image_identity(
    *,
    image: str,
    identities: set[str],
    scanner: str | None,
) -> tuple[str, ...]:
    if not identities:
        return (f"{scanner or 'scanner'} report must include scanned image identity metadata",)
    requested_digest = image.rsplit("@", 1)[-1]
    allowed_identities = {image, requested_digest}
    if not any(identity in allowed_identities for identity in identities):
        return ("scanner report image identity does not match requested image digest",)
    return ()


def severity_from_mapping(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    severity = value.get("Severity")
    if not isinstance(severity, str):
        severity = value.get("severity")
    if not isinstance(severity, str):
        return None
    normalized = severity.strip().lower()
    if normalized in {"critical", "high", "medium", "low", "negligible"}:
        return normalized
    if normalized in {"unknown", "none"}:
        return "unknown"
    return "unknown"


def empty_counts() -> dict[str, int]:
    return {severity: 0 for severity in SEVERITIES}


def render_json(report: ExportImageAuditEvidenceReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_text(report: ExportImageAuditEvidenceReport) -> str:
    lines = [
        "GOFFY Task Text export image audit evidence",
        f"status: {report.status}",
        f"ok: {str(report.ok).lower()}",
        f"image: {report.image}",
        f"scanner: {report.scanner or 'unknown'}",
    ]
    if report.evidence:
        counts = report.evidence.get("vulnerability_counts")
        if isinstance(counts, dict):
            rendered_counts = ", ".join(f"{key}={counts[key]}" for key in SEVERITIES)
            lines.append(f"vulnerabilities: {rendered_counts}")
    if report.output:
        lines.append(f"output: {report.output}")
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    for step in report.steps:
        lines.append(f"[{step.status}] {step.name}")
        if step.detail:
            lines.append(f"       detail: {step.detail}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create GOFFY audit evidence for a digest-pinned Task Text export image "
            "from Trivy or Grype JSON output."
        )
    )
    parser.add_argument("--image", required=True)
    parser.add_argument("--scanner-report", required=True, type=Path)
    parser.add_argument("--scanner", choices=SUPPORTED_SCANNERS, default="auto")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        image=args.image,
        scanner_report=args.scanner_report,
        scanner=args.scanner,
        output=args.output,
        write=args.write,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
