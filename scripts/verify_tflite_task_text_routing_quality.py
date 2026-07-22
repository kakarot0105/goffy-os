from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_moto_g_tflite_task_text_benchmark import (  # noqa: E402
    command_sha256,
    validate_classifier_json_payload,
)
from scripts.verify_local_intent_router_corpus import (  # noqa: E402
    ALLOWED_LABELS,
    DEFAULT_CORPUS_PATH,
    ROUTE_LABELS,
    CorpusExample,
    load_json_object,
    mapping_items,
    string_items,
    string_value,
    verify_local_intent_router_corpus,
)

JSON_SCHEMA_VERSION = "goffy.tflite-task-text-routing-quality.v1"
EVIDENCE_SCHEMA_VERSION = "goffy.tflite-task-text-routing-quality-evidence.v1"
DEFAULT_SPLIT = "eval"
DEFAULT_MIN_ROUTE_ACCURACY = 0.90
DEFAULT_MIN_UNKNOWN_REJECTION_RATE = 1.0
DEFAULT_MAX_INFERENCE_MILLIS = 250
MAX_MODEL_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class AcceptedRoutingResult:
    example_id: str
    expected_label: str
    artifact: str
    inference_millis: float
    observation_type: str
    observation_route: str | None
    observation_confidence: float | None


@dataclass(frozen=True)
class RejectedRoutingResult:
    example_id: str
    expected_label: str | None
    artifact: str | None
    reason: str


@dataclass(frozen=True)
class TfliteTaskTextRoutingQualityReport:
    schema_version: str
    ok: bool
    status: str
    split: str
    expected_examples: int
    evaluated_examples: int
    correct_examples: int
    route_accuracy: float
    unknown_rejection_rate: float
    model_sha256: str | None
    model_bytes: int | None
    accepted_results: tuple[AcceptedRoutingResult, ...]
    rejected_results: tuple[RejectedRoutingResult, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def build_routing_quality_report(
    *,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    evidence_manifest: Path,
    split: str = DEFAULT_SPLIT,
    min_route_accuracy: float = DEFAULT_MIN_ROUTE_ACCURACY,
    min_unknown_rejection_rate: float = DEFAULT_MIN_UNKNOWN_REJECTION_RATE,
    max_inference_millis: int = DEFAULT_MAX_INFERENCE_MILLIS,
) -> TfliteTaskTextRoutingQualityReport:
    blockers: list[str] = []
    warnings: list[str] = []
    accepted: list[AcceptedRoutingResult] = []
    rejected: list[RejectedRoutingResult] = []

    corpus_report = verify_local_intent_router_corpus(corpus_path)
    if not corpus_report.ok:
        blockers.extend(f"corpus: {blocker}" for blocker in corpus_report.blockers)

    try:
        corpus_examples = load_corpus_examples(corpus_path, split=split)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        corpus_examples = {}
        blockers.append(f"corpus: {exc}")

    try:
        evidence = load_json_object(evidence_manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        evidence = {}
        blockers.append(f"evidence manifest: {exc}")

    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        blockers.append("evidence manifest schema_version mismatch")

    evidence_root = evidence_manifest.parent.resolve(strict=False)
    model_file = resolve_evidence_artifact(evidence_root, string_value(evidence.get("model_file")))
    model_sha: str | None = None
    model_bytes: int | None = None
    if model_file is None:
        blockers.append("evidence manifest model_file must stay under the evidence directory")
    elif model_file.suffix != ".tflite":
        blockers.append("evidence manifest model_file must point to a .tflite file")
    elif not model_file.is_file():
        blockers.append("evidence manifest model_file is missing")
    else:
        model_bytes = model_file.stat().st_size
        if model_bytes <= 0 or model_bytes > MAX_MODEL_BYTES:
            blockers.append(f"evidence manifest model file size must be 1..{MAX_MODEL_BYTES}")
        model_sha = sha256_file(model_file)

    declared_model_sha = string_value(evidence.get("model_sha256"))
    if declared_model_sha is not None and declared_model_sha != model_sha:
        blockers.append("evidence manifest model_sha256 does not match model_file")

    declared_model_bytes = int_value(evidence.get("model_bytes"))
    if declared_model_bytes is not None and declared_model_bytes != model_bytes:
        blockers.append("evidence manifest model_bytes does not match model_file")

    result_items = mapping_items(evidence.get("results"))
    artifacts_by_example: dict[str, Path] = {}
    seen_artifacts: set[Path] = set()
    for index, item in enumerate(result_items):
        example_id = string_value(item.get("example_id"))
        artifact_value = string_value(item.get("artifact"))
        if example_id is None or artifact_value is None:
            blockers.append(f"results[{index}]: example_id and artifact are required")
            continue
        if example_id in artifacts_by_example:
            blockers.append(f"{example_id}: duplicate evidence result")
            continue
        artifact_path = resolve_evidence_artifact(evidence_root, artifact_value)
        if artifact_path is None:
            blockers.append(
                f"{example_id}: artifact must stay under the evidence manifest directory"
            )
            continue
        if artifact_path in seen_artifacts:
            blockers.append(f"{example_id}: duplicate benchmark artifact path")
            continue
        seen_artifacts.add(artifact_path)
        artifacts_by_example[example_id] = artifact_path

    for example_id, example in corpus_examples.items():
        artifact = artifacts_by_example.get(example_id)
        if artifact is None:
            rejected.append(
                RejectedRoutingResult(
                    example_id=example_id,
                    expected_label=example.label,
                    artifact=None,
                    reason="missing benchmark artifact",
                )
            )
            blockers.append(f"{example_id}: missing benchmark artifact")
            continue
        try:
            result = validate_benchmark_artifact(
                example=example,
                artifact=artifact,
                max_inference_millis=max_inference_millis,
                model_sha256=model_sha,
                model_bytes=model_bytes,
            )
        except ValueError as exc:
            rejected.append(
                RejectedRoutingResult(
                    example_id=example_id,
                    expected_label=example.label,
                    artifact=str(artifact),
                    reason=str(exc),
                )
            )
            continue
        accepted.append(result)

    unknown_expected = sum(1 for example in corpus_examples.values() if example.label == "UNKNOWN")
    unknown_correct = sum(
        1
        for result in accepted
        if result.expected_label == "UNKNOWN" and result.observation_type == "Rejected"
    )
    route_expected = sum(1 for example in corpus_examples.values() if example.label in ROUTE_LABELS)
    route_correct = sum(
        1
        for result in accepted
        if result.expected_label in ROUTE_LABELS
        and result.observation_route == result.expected_label
    )
    correct_examples = route_correct + unknown_correct
    route_accuracy = route_correct / route_expected if route_expected else 0.0
    unknown_rejection_rate = unknown_correct / unknown_expected if unknown_expected else 0.0

    if route_expected == 0 or unknown_expected == 0:
        blockers.append("routing quality requires route and UNKNOWN eval examples")
    if route_accuracy < min_route_accuracy:
        blockers.append(
            f"route accuracy {route_accuracy:.3f} is below required {min_route_accuracy:.3f}"
        )
    if unknown_rejection_rate < min_unknown_rejection_rate:
        blockers.append(
            "UNKNOWN rejection rate "
            f"{unknown_rejection_rate:.3f} is below required {min_unknown_rejection_rate:.3f}"
        )
    unexpected_evidence = sorted(set(artifacts_by_example) - set(corpus_examples))
    if unexpected_evidence:
        warnings.append(f"unused evidence example ids: {unexpected_evidence}")

    deduped_blockers = tuple(dict.fromkeys(blockers))
    return TfliteTaskTextRoutingQualityReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=not deduped_blockers and not rejected,
        status="ACCEPTED" if not deduped_blockers and not rejected else "BLOCKED",
        split=split,
        expected_examples=len(corpus_examples),
        evaluated_examples=len(accepted) + len(rejected),
        correct_examples=correct_examples,
        route_accuracy=route_accuracy,
        unknown_rejection_rate=unknown_rejection_rate,
        model_sha256=model_sha,
        model_bytes=model_bytes,
        accepted_results=tuple(accepted),
        rejected_results=tuple(rejected),
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def load_corpus_examples(path: Path, *, split: str) -> dict[str, CorpusExample]:
    payload = load_json_object(path)
    examples: dict[str, CorpusExample] = {}
    for item in mapping_items(payload.get("examples")):
        example = CorpusExample(
            id=str(item.get("id", "")),
            text=str(item.get("text", "")),
            label=str(item.get("label", "")),
            split=str(item.get("split", "")),
            capability=str(item.get("capability", "")),
            risk_tags=tuple(string_items(item.get("risk_tags"))),
        )
        if example.split == split:
            examples[example.id] = example
    if split not in {"train", "eval"}:
        raise ValueError("split must be train or eval")
    if not examples:
        raise ValueError(f"no corpus examples found for split {split}")
    return examples


def resolve_evidence_artifact(evidence_root: Path, artifact_value: str | None) -> Path | None:
    if not artifact_value:
        return None
    artifact = Path(artifact_value)
    candidate = artifact if artifact.is_absolute() else evidence_root / artifact
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(evidence_root)
    except ValueError:
        return None
    return resolved


def validate_benchmark_artifact(
    *,
    example: CorpusExample,
    artifact: Path,
    max_inference_millis: int,
    model_sha256: str | None,
    model_bytes: int | None,
) -> AcceptedRoutingResult:
    payload = load_json_object(artifact)
    validation_failure = validate_classifier_json_payload(payload)
    if validation_failure is not None:
        raise ValueError(validation_failure)
    if payload.get("exampleId") != example.id:
        raise ValueError("benchmark artifact exampleId does not match corpus example")
    if payload.get("commandSha256") != command_sha256(example.text):
        raise ValueError("benchmark artifact commandSha256 does not match corpus text")
    if model_sha256 is None or payload.get("modelSha256") != model_sha256:
        raise ValueError("benchmark artifact modelSha256 does not match evidence model")
    if model_bytes is None or payload.get("modelBytes") != model_bytes:
        raise ValueError("benchmark artifact modelBytes does not match evidence model")
    inference_millis = number_value(payload.get("inferenceMillis"))
    if inference_millis is None:
        raise ValueError("benchmark artifact did not include inferenceMillis")
    if inference_millis <= 0 or inference_millis > max_inference_millis:
        raise ValueError(f"inferenceMillis {inference_millis:g} exceeds {max_inference_millis} ms")
    observation_type = string_value(payload.get("observationType"))
    if observation_type not in {"Candidate", "Rejected"}:
        raise ValueError("benchmark artifact did not report a terminal observation")

    observation_route = string_value(payload.get("observationRoute"))
    observation_confidence = number_value(payload.get("observationConfidence"))
    if example.label in ROUTE_LABELS:
        if observation_type != "Candidate":
            raise ValueError(f"{example.label} example did not produce a route candidate")
        if observation_route != example.label:
            raise ValueError(
                f"{example.label} example routed to {observation_route or '<missing>'}"
            )
        if observation_confidence is None or observation_confidence < 0.70:
            raise ValueError(f"{example.label} candidate confidence is below 0.70")
    elif example.label == "UNKNOWN":
        if observation_type != "Rejected":
            raise ValueError("UNKNOWN example was not rejected")
    elif example.label not in ALLOWED_LABELS:
        raise ValueError(f"unsupported expected label {example.label}")

    return AcceptedRoutingResult(
        example_id=example.id,
        expected_label=example.label,
        artifact=str(artifact),
        inference_millis=inference_millis,
        observation_type=observation_type,
        observation_route=observation_route,
        observation_confidence=observation_confidence,
    )


def int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def number_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def render_json(report: TfliteTaskTextRoutingQualityReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_text(report: TfliteTaskTextRoutingQualityReport) -> str:
    lines = [
        "GOFFY TFLite Task Text routing quality",
        f"status: {report.status}",
        f"ok: {str(report.ok).lower()}",
        f"split: {report.split}",
        f"expected examples: {report.expected_examples}",
        f"evaluated examples: {report.evaluated_examples}",
        f"correct examples: {report.correct_examples}",
        f"route accuracy: {report.route_accuracy:.3f}",
        f"UNKNOWN rejection rate: {report.unknown_rejection_rate:.3f}",
    ]
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.rejected_results:
        lines.append("rejected results:")
        lines.extend(
            f"- {result.example_id}: {result.reason}" for result in report.rejected_results
        )
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify physical Moto TFLite Task Text routing-quality evidence.",
    )
    parser.add_argument("evidence_manifest", type=Path)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--split", default=DEFAULT_SPLIT, choices=("train", "eval"))
    parser.add_argument("--min-route-accuracy", type=float, default=DEFAULT_MIN_ROUTE_ACCURACY)
    parser.add_argument(
        "--min-unknown-rejection-rate",
        type=float,
        default=DEFAULT_MIN_UNKNOWN_REJECTION_RATE,
    )
    parser.add_argument("--max-inference-millis", type=int, default=DEFAULT_MAX_INFERENCE_MILLIS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_routing_quality_report(
        corpus_path=args.corpus,
        evidence_manifest=args.evidence_manifest,
        split=args.split,
        min_route_accuracy=args.min_route_accuracy,
        min_unknown_rejection_rate=args.min_unknown_rejection_rate,
        max_inference_millis=args.max_inference_millis,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
