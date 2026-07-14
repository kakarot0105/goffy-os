from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ROOT = ROOT / "protocol" / "python"
if __package__ in {None, ""}:
    for import_root in (ROOT, PROTOCOL_ROOT):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

import scripts.collect_moto_g_validation_bundle as collect  # noqa: E402
import scripts.guide_moto_g_validation as guide  # noqa: E402
import scripts.record_moto_g_smoke as smoke  # noqa: E402
import scripts.verify_moto_g_validation_bundle as verify  # noqa: E402
from scripts.setup_doctor import DoctorReport, safe_text  # noqa: E402
from scripts.verify_moto_g_readiness import existing_directory  # noqa: E402

JSON_SCHEMA_VERSION = "goffy.moto-g-validation-pipeline.v1"


@dataclass(frozen=True)
class ValidationPipelineResult:
    bundle: collect.ValidationBundle | None
    verification: verify.BundleVerification | None
    error_code: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.verification.ok if self.verification is not None else False

    @property
    def integrity_ok(self) -> bool:
        return self.verification.integrity_ok if self.verification is not None else False

    @property
    def physical_smoke_passed(self) -> bool:
        return self.verification.physical_smoke_passed if self.verification is not None else False

    @property
    def verification_attempted(self) -> bool:
        return self.verification is not None

    @property
    def next_step_id(self) -> str | None:
        if self.verification is not None:
            return self.verification.next_step_id
        if self.bundle is not None:
            return self.bundle.next_step_id
        return None

    @property
    def exit_code(self) -> int:
        if self.verification is None:
            return 2
        return self.verification.exit_code


def run_pipeline(
    *,
    root: Path = ROOT,
    output_root: Path = collect.DEFAULT_OUTPUT_ROOT,
    manual: smoke.ManualSmokeEvidence | None = None,
    timestamp_utc: str | None = None,
    report: guide.GuideReport | None = None,
    force: bool = False,
) -> ValidationPipelineResult:
    try:
        bundle = collect.collect_bundle(
            root=root,
            output_root=output_root,
            manual=manual,
            timestamp_utc=timestamp_utc,
            report=report,
            force=force,
        )
    except collect.BundleExistsError as exc:
        return ValidationPipelineResult(
            bundle=None,
            verification=None,
            error_code="collection_conflict",
            error=str(exc),
        )
    verification = verify.verify_bundle(bundle.output_directory)
    return ValidationPipelineResult(bundle=bundle, verification=verification)


def redaction_report() -> DoctorReport:
    return DoctorReport(checks=(), repo_root=ROOT, home=Path.home())


def redacted_error(result: ValidationPipelineResult) -> str | None:
    if result.error is None:
        return None
    if result.error_code == "collection_conflict":
        return (
            "validation bundle collection conflict; choose another output root or use "
            "--force only for a previously marked GOFFY validation bundle"
        )
    return safe_text(result.error, report=redaction_report())


def verification_payload(result: ValidationPipelineResult) -> dict[str, Any] | None:
    if result.verification is None:
        return None
    payload = json.loads(verify.render_json(result.verification))
    if not isinstance(payload, dict):
        raise TypeError("bundle verifier returned a non-object payload")
    return payload


def render_json(result: ValidationPipelineResult) -> str:
    payload: dict[str, Any] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": result.ok,
        "verificationAttempted": result.verification_attempted,
        "integrityOk": result.integrity_ok if result.verification_attempted else None,
        "physicalSmokePassed": (
            result.physical_smoke_passed if result.verification_attempted else None
        ),
        "nextStepId": result.next_step_id,
        "bundleName": result.bundle.bundle_name if result.bundle is not None else None,
        "errorCode": result.error_code,
        "error": redacted_error(result),
        "verification": verification_payload(result),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_text(result: ValidationPipelineResult) -> str:
    lines = ["GOFFY Moto G validation pipeline"]
    lines.append(f"overall: {'passed' if result.ok else 'not-passed'}")
    lines.append(f"verification-attempted: {str(result.verification_attempted).lower()}")
    if result.verification_attempted:
        lines.append(f"integrity: {'passed' if result.integrity_ok else 'failed'}")
        lines.append(
            f"physical-smoke: {'passed' if result.physical_smoke_passed else 'not-passed'}"
        )
    else:
        lines.append("integrity: not-run")
        lines.append("physical-smoke: not-run")
    lines.append(f"next-step: {result.next_step_id or 'none'}")
    if result.bundle is not None:
        lines.append(f"bundle: {result.bundle.bundle_name}")
        lines.append("bundle-directory: see selected --output-root")
    if result.error_code is not None:
        lines.append(f"error-code: {result.error_code}")
    if result.error is not None:
        lines.append(f"error: {redacted_error(result)}")
    lines.append("")
    if result.verification is not None:
        lines.append("verification:")
        for check in result.verification.checks:
            status = "OK" if check.ok else "FAIL"
            lines.append(f"[{status}] {check.check_id}: {check.detail}")
            if not check.ok and check.remediation:
                lines.append(f"       fix: {check.remediation}")
    else:
        lines.append("No bundle was verified.")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=existing_directory, default=ROOT)
    parser.add_argument("--output-root", type=Path, default=collect.DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite a previously marked timestamped bundle before collecting evidence.",
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_pipeline(
        root=args.repo_root,
        output_root=args.output_root,
        manual=collect.manual_from_args(args),
        force=args.force,
    )
    print(render_json(result) if args.json else render_text(result))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
