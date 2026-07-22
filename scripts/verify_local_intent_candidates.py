from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES_PATH = ROOT / "docs" / "architecture" / "local-intent-classifier-candidates.json"

JSON_SCHEMA_VERSION = "goffy.local-intent-classifier-candidates.v1"
ALLOWED_LICENSES = frozenset({"Apache-2.0", "MIT", "Internal"})
ALLOWED_DECISIONS = frozenset(
    {
        "current_baseline",
        "prototype_candidate",
        "research_candidate",
        "prior_art_only",
        "rejected_for_phone",
    }
)
ALLOWED_DEFAULT_BUILD_INCLUSION = frozenset({"allowed", "blocked"})
ALLOWED_EXECUTION_AUTHORITY = frozenset({"observe_only", "not_imported"})
ALLOWED_SOURCE_KINDS = frozenset(
    {"internal", "official_runtime", "open_source_prior_art", "measured_runtime"}
)
ALLOWED_PRODUCTION_STATUSES = frozenset(
    {
        "active_non_executable",
        "blocked_until_physical_benchmark",
        "blocked_until_dependency_pin_and_physical_benchmark",
        "blocked_by_physical_evidence",
        "not_imported",
        "accepted_observe_only_nondefault",
        "accepted_modeldebug_only",
    }
)
EXTERNAL_SOURCE_KINDS = frozenset({"official_runtime", "open_source_prior_art", "measured_runtime"})
PROTOTYPE_DECISIONS = frozenset({"prototype_candidate", "research_candidate"})
ACCEPTED_NONDEFAULT_STATUSES = frozenset(
    {"accepted_observe_only_nondefault", "accepted_modeldebug_only"}
)
REQUIRED_PROTOTYPE_GATES = frozenset(
    {
        "license",
        "pinned_dependency",
        "apk_budget",
        "latency",
        "idle_memory",
        "routing_quality",
        "audit_non_authoritative",
        "physical_moto_benchmark",
    }
)

HARD_MAX_CANDIDATE_MODEL_BYTES = 8 * 1024 * 1024
HARD_MAX_DEFAULT_APK_DELTA_BYTES = 2 * 1024 * 1024
HARD_MAX_SINGLE_INFERENCE_MILLIS = 250
HARD_MAX_IDLE_PSS_KB = 16 * 1024

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_]{2,63}$")
EXACT_MAVEN_COORDINATE = re.compile(r"^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+:[A-Za-z0-9][A-Za-z0-9_.-]*$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class LocalIntentCandidateReport:
    schema_version: str
    ok: bool
    candidate_count: int
    prototype_candidate_ids: tuple[str, ...]
    rejected_candidate_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def verify_local_intent_candidates(
    path: Path = DEFAULT_CANDIDATES_PATH,
) -> LocalIntentCandidateReport:
    blockers: list[str] = []
    warnings: list[str] = []
    prototype_ids: list[str] = []
    rejected_ids: list[str] = []

    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return LocalIntentCandidateReport(
            schema_version=JSON_SCHEMA_VERSION,
            ok=False,
            candidate_count=0,
            prototype_candidate_ids=(),
            rejected_candidate_ids=(),
            blockers=(str(exc),),
            warnings=(),
        )

    if payload.get("schema_version") != JSON_SCHEMA_VERSION:
        blockers.append("local intent candidate registry schema_version mismatch")
    reviewed_at = string_value(payload.get("reviewed_at"))
    if reviewed_at is None or DATE.match(reviewed_at) is None:
        blockers.append("reviewed_at must be an ISO date")

    default_policy = mapping_value(payload.get("default_policy"))
    blockers.extend(validate_default_policy(default_policy))

    declared_required_gates = frozenset(string_items(payload.get("required_prototype_gates")))
    if not REQUIRED_PROTOTYPE_GATES.issubset(declared_required_gates):
        blockers.append("required_prototype_gates must include every GOFFY prototype gate")

    candidates = mapping_items(payload.get("candidates"))
    if not candidates:
        blockers.append("at least one local intent candidate is required")

    seen_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        candidate_id = string_value(candidate.get("id"))
        label = candidate_id or f"candidate[{index}]"
        if candidate_id is None or SAFE_ID.match(candidate_id) is None:
            blockers.append(f"{label}: id must be safe lower snake case")
        elif candidate_id in seen_ids:
            blockers.append(f"{candidate_id}: duplicate candidate id")
        elif candidate_id is not None:
            seen_ids.add(candidate_id)

        decision = string_value(candidate.get("decision"))
        if decision in PROTOTYPE_DECISIONS and candidate_id is not None:
            prototype_ids.append(candidate_id)
        if decision == "rejected_for_phone" and candidate_id is not None:
            rejected_ids.append(candidate_id)

        blockers.extend(validate_candidate(candidate, label=label))

    if not prototype_ids:
        warnings.append("no reusable lightweight classifier prototype candidate is selected")

    deduped_blockers = tuple(dict.fromkeys(blockers))
    return LocalIntentCandidateReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=not deduped_blockers,
        candidate_count=len(candidates),
        prototype_candidate_ids=tuple(prototype_ids),
        rejected_candidate_ids=tuple(rejected_ids),
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def validate_default_policy(policy: dict[str, object]) -> tuple[str, ...]:
    blockers: list[str] = []
    if not policy:
        return ("default_policy is required",)
    if policy.get("default_build_must_remain_model_free") is not True:
        blockers.append("default build must remain model-free")
    if policy.get("observations_must_remain_non_authoritative") is not True:
        blockers.append("local classifier observations must remain non-authoritative")
    if not is_within_positive_budget(
        policy.get("max_candidate_model_bytes"),
        HARD_MAX_CANDIDATE_MODEL_BYTES,
    ):
        blockers.append(
            f"max_candidate_model_bytes must be at most {HARD_MAX_CANDIDATE_MODEL_BYTES}"
        )
    if not is_within_positive_budget(
        policy.get("max_default_apk_delta_bytes"),
        HARD_MAX_DEFAULT_APK_DELTA_BYTES,
    ):
        blockers.append(
            f"max_default_apk_delta_bytes must be at most {HARD_MAX_DEFAULT_APK_DELTA_BYTES}"
        )
    if not is_within_positive_budget(
        policy.get("max_single_inference_millis"),
        HARD_MAX_SINGLE_INFERENCE_MILLIS,
    ):
        blockers.append(
            f"max_single_inference_millis must be at most {HARD_MAX_SINGLE_INFERENCE_MILLIS}"
        )
    if not is_within_positive_budget(policy.get("max_idle_pss_kb"), HARD_MAX_IDLE_PSS_KB):
        blockers.append(f"max_idle_pss_kb must be at most {HARD_MAX_IDLE_PSS_KB}")
    return tuple(blockers)


def validate_candidate(candidate: dict[str, object], *, label: str) -> tuple[str, ...]:
    blockers: list[str] = []
    source_kind = string_value(candidate.get("source_kind"))
    decision = string_value(candidate.get("decision"))
    default_build_inclusion = string_value(candidate.get("default_build_inclusion"))
    execution_authority = string_value(candidate.get("execution_authority"))
    production_status = string_value(candidate.get("production_status"))
    license_name = string_value(candidate.get("license"))
    required_gates = frozenset(string_items(candidate.get("required_gates")))

    if license_name not in ALLOWED_LICENSES:
        blockers.append(f"{label}: license must be allowlisted")
    if source_kind not in ALLOWED_SOURCE_KINDS:
        blockers.append(f"{label}: source_kind is unsupported")
    if production_status not in ALLOWED_PRODUCTION_STATUSES:
        blockers.append(f"{label}: production_status is unsupported")
    if decision not in ALLOWED_DECISIONS:
        blockers.append(f"{label}: decision is unsupported")
    if default_build_inclusion not in ALLOWED_DEFAULT_BUILD_INCLUSION:
        blockers.append(f"{label}: default_build_inclusion is unsupported")
    if execution_authority not in ALLOWED_EXECUTION_AUTHORITY:
        blockers.append(f"{label}: execution_authority is unsupported")
    if not string_items(candidate.get("reasons")):
        blockers.append(f"{label}: reasons are required")
    if not string_items(candidate.get("risks")):
        blockers.append(f"{label}: risks are required")
    if string_value(candidate.get("next_action")) is None:
        blockers.append(f"{label}: next_action is required")

    source_urls = string_items(candidate.get("source_urls"))
    if not source_urls:
        blockers.append(f"{label}: source_urls are required")
    for source_url in source_urls:
        if contains_unsafe_text(source_url):
            blockers.append(f"{label}: source_url contains unsafe text")
        elif not (source_url.startswith("https://") or source_url.startswith("internal:")):
            blockers.append(f"{label}: source URLs must be https or internal evidence")
        elif source_kind == "internal" and not source_url.startswith("internal:"):
            blockers.append(f"{label}: internal source URLs must use internal:")
        elif source_kind in EXTERNAL_SOURCE_KINDS and not (
            source_url.startswith("https://") or source_url.startswith("internal:")
        ):
            blockers.append(f"{label}: external source URLs must be https or internal evidence")

    dependency_coordinate = string_value(candidate.get("dependency_coordinate"))
    if dependency_coordinate is not None and not EXACT_MAVEN_COORDINATE.match(
        dependency_coordinate
    ):
        blockers.append(f"{label}: dependency_coordinate must be an exact pinned Maven coordinate")
    elif dependency_coordinate is not None and is_dynamic_maven_coordinate(dependency_coordinate):
        blockers.append(f"{label}: dependency_coordinate must not use a dynamic version")

    if decision in PROTOTYPE_DECISIONS:
        blockers.extend(
            validate_prototype_candidate(
                candidate,
                label=label,
                default_build_inclusion=default_build_inclusion,
                execution_authority=execution_authority,
                production_status=production_status,
                required_gates=required_gates,
                dependency_coordinate=dependency_coordinate,
            )
        )
    elif decision == "current_baseline":
        blockers.extend(validate_current_baseline(candidate, label=label))
    elif decision in {"prior_art_only", "rejected_for_phone"}:
        if default_build_inclusion != "blocked":
            blockers.append(f"{label}: non-selected candidates must stay out of default builds")
        if production_status in ACCEPTED_NONDEFAULT_STATUSES | {"active_non_executable"}:
            blockers.append(f"{label}: non-selected candidates must not be active")

    if default_build_inclusion == "allowed" and dependency_coordinate is not None:
        blockers.append(f"{label}: default-build candidates must not declare dependencies")

    return tuple(blockers)


def validate_prototype_candidate(
    candidate: dict[str, object],
    *,
    label: str,
    default_build_inclusion: str | None,
    execution_authority: str | None,
    production_status: str | None,
    required_gates: frozenset[str],
    dependency_coordinate: str | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if default_build_inclusion != "blocked":
        blockers.append(f"{label}: prototype candidates must stay out of default builds")
    if execution_authority != "observe_only":
        blockers.append(f"{label}: prototype candidates must remain observe-only")
    if production_status in ACCEPTED_NONDEFAULT_STATUSES:
        blockers.extend(
            validate_accepted_nondefault_candidate(
                candidate,
                label=label,
                required_gates=required_gates,
            )
        )
    elif not production_status or not production_status.startswith("blocked_until_"):
        blockers.append(
            f"{label}: prototype candidates must be blocked or accepted only after benchmark gates"
        )
    if candidate.get("model_file_required") is not True:
        blockers.append(f"{label}: prototype candidates must require an explicit model file")
    if not REQUIRED_PROTOTYPE_GATES.issubset(required_gates):
        blockers.append(f"{label}: prototype candidate is missing required gates")
    if not is_within_positive_budget(
        candidate.get("candidate_model_budget_bytes"),
        HARD_MAX_CANDIDATE_MODEL_BYTES,
    ):
        blockers.append(
            f"{label}: candidate_model_budget_bytes must stay within the small-classifier budget"
        )
    if not is_within_positive_budget(
        candidate.get("max_inference_millis"),
        HARD_MAX_SINGLE_INFERENCE_MILLIS,
    ):
        blockers.append(f"{label}: max_inference_millis must stay within the Moto budget")
    if not is_within_positive_budget(candidate.get("max_idle_pss_kb"), HARD_MAX_IDLE_PSS_KB):
        blockers.append(f"{label}: max_idle_pss_kb must stay within the Moto budget")
    if dependency_coordinate is None and candidate.get("pinned_dependency_required") is not True:
        blockers.append(f"{label}: prototype candidates require a pinned dependency plan")
    return tuple(blockers)


def validate_accepted_nondefault_candidate(
    candidate: dict[str, object],
    *,
    label: str,
    required_gates: frozenset[str],
) -> tuple[str, ...]:
    blockers: list[str] = []
    if candidate.get("default_build_inclusion") != "blocked":
        blockers.append(
            f"{label}: accepted classifier candidates must remain out of default builds"
        )
    if candidate.get("execution_authority") != "observe_only":
        blockers.append(f"{label}: accepted classifier candidates must remain observe-only")
    if not REQUIRED_PROTOTYPE_GATES.issubset(required_gates):
        blockers.append(f"{label}: accepted classifier candidate is missing required gates")
    physical_evidence = string_value(candidate.get("physical_evidence"))
    if physical_evidence is None:
        blockers.append(f"{label}: accepted classifier candidates require physical_evidence")
    elif not is_internal_evidence_reference(physical_evidence):
        blockers.append(
            f"{label}: accepted classifier physical_evidence must be an internal evidence reference"
        )
    return tuple(blockers)


def validate_current_baseline(candidate: dict[str, object], *, label: str) -> tuple[str, ...]:
    blockers: list[str] = []
    if candidate.get("source_kind") != "internal":
        blockers.append(f"{label}: current baseline must be internal")
    if candidate.get("default_build_inclusion") != "allowed":
        blockers.append(f"{label}: current baseline must be allowed in the default build")
    if candidate.get("model_file_required") is not False:
        blockers.append(f"{label}: current baseline must not require a model file")
    if candidate.get("execution_authority") != "observe_only":
        blockers.append(f"{label}: current baseline must remain observe-only")
    if int_or_none(candidate.get("candidate_model_budget_bytes")) != 0:
        blockers.append(f"{label}: current baseline must stay model-free")
    if candidate.get("dependency_coordinate") is not None:
        blockers.append(f"{label}: current baseline must not declare a dependency")
    return tuple(blockers)


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def mapping_value(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def mapping_items(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def positive_int(value: object) -> int | None:
    parsed = int_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def is_within_positive_budget(value: object, maximum: int) -> bool:
    parsed = positive_int(value)
    return parsed is not None and parsed <= maximum


def int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def contains_unsafe_text(value: str) -> bool:
    return any(not char.isascii() or ord(char) < 32 or ord(char) == 127 for char in value)


def is_internal_evidence_reference(value: str) -> bool:
    return value.startswith("internal:.goffy-validation/") and not contains_unsafe_text(value)


def is_dynamic_maven_coordinate(value: str) -> bool:
    version = value.rsplit(":", maxsplit=1)[-1]
    return version.startswith("latest.") or "+" in version


def render_json(report: LocalIntentCandidateReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_text(report: LocalIntentCandidateReport) -> str:
    lines = [
        "GOFFY local intent classifier candidates",
        f"schema: {report.schema_version}",
        f"ok: {str(report.ok).lower()}",
        f"candidates: {report.candidate_count}",
        f"prototype candidates: {', '.join(report.prototype_candidate_ids) or 'none'}",
        f"rejected candidates: {', '.join(report.rejected_candidate_ids) or 'none'}",
    ]
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify GOFFY's reuse-first local intent classifier candidate registry.",
    )
    parser.add_argument("--candidates-json", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = verify_local_intent_candidates(args.candidates_json)
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
