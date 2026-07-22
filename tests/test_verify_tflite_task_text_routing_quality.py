from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.run_moto_g_tflite_task_text_benchmark import command_sha256
from scripts.verify_local_intent_router_corpus import DEFAULT_CORPUS_PATH
from scripts.verify_tflite_task_text_routing_quality import (
    EVIDENCE_SCHEMA_VERSION,
    JSON_SCHEMA_VERSION,
    build_routing_quality_report,
)


def test_routing_quality_accepts_complete_eval_evidence(tmp_path: Path) -> None:
    manifest = write_complete_evidence(tmp_path)

    report = build_routing_quality_report(evidence_manifest=manifest)

    assert report.schema_version == JSON_SCHEMA_VERSION
    assert report.ok
    assert report.status == "ACCEPTED"
    assert report.expected_examples == 17
    assert report.evaluated_examples == 17
    assert report.correct_examples == 17
    assert report.route_accuracy == 1.0
    assert report.unknown_rejection_rate == 1.0


def test_routing_quality_blocks_unknown_false_positive(tmp_path: Path) -> None:
    manifest = write_complete_evidence(tmp_path)
    unknown = next(example for example in eval_examples() if example["label"] == "UNKNOWN")
    unknown_id = str(unknown["id"])
    write_artifact(tmp_path, unknown, force_candidate="PHONE")

    report = build_routing_quality_report(evidence_manifest=manifest)

    assert not report.ok
    assert any(result.example_id == unknown_id for result in report.rejected_results)
    assert any("UNKNOWN rejection rate" in blocker for blocker in report.blockers)


def test_routing_quality_blocks_slow_inference(tmp_path: Path) -> None:
    manifest = write_complete_evidence(tmp_path)
    phone = next(example for example in eval_examples() if example["label"] == "PHONE")
    write_artifact(tmp_path, phone, inference_millis=999)

    report = build_routing_quality_report(evidence_manifest=manifest)

    assert not report.ok
    assert any(
        "inferenceMillis 999 exceeds 250 ms" in result.reason for result in report.rejected_results
    )


def test_routing_quality_blocks_artifact_path_escape(tmp_path: Path) -> None:
    manifest = write_complete_evidence(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    first_result = payload["results"][0]
    assert isinstance(first_result, dict)
    first_result["artifact"] = "../outside.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    report = build_routing_quality_report(evidence_manifest=manifest)

    assert not report.ok
    assert any("artifact must stay under" in blocker for blocker in report.blockers)


def test_routing_quality_blocks_replayed_artifact_path(tmp_path: Path) -> None:
    manifest = write_complete_evidence(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    results = payload["results"]
    assert isinstance(results, list)
    first_result = results[0]
    second_result = results[1]
    assert isinstance(first_result, dict)
    assert isinstance(second_result, dict)
    second_result["artifact"] = first_result["artifact"]
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    report = build_routing_quality_report(evidence_manifest=manifest)

    assert not report.ok
    assert any("duplicate benchmark artifact path" in blocker for blocker in report.blockers)


def test_routing_quality_blocks_example_id_mismatch(tmp_path: Path) -> None:
    manifest = write_complete_evidence(tmp_path)
    first = eval_examples()[0]
    write_artifact(tmp_path, first, example_id_override="wrong_example_id")

    report = build_routing_quality_report(evidence_manifest=manifest)

    assert not report.ok
    assert any("exampleId does not match" in result.reason for result in report.rejected_results)


def test_routing_quality_blocks_model_hash_mismatch(tmp_path: Path) -> None:
    manifest = write_complete_evidence(tmp_path)
    first = eval_examples()[0]
    write_artifact(tmp_path, first, model_sha_override="0" * 64)

    report = build_routing_quality_report(evidence_manifest=manifest)

    assert not report.ok
    assert any("modelSha256 does not match" in result.reason for result in report.rejected_results)


def write_complete_evidence(tmp_path: Path) -> Path:
    model_file = write_model_file(tmp_path)
    model_sha = sha256_file(model_file)
    results: list[dict[str, str]] = []
    for example in eval_examples():
        example_id = str(example["id"])
        artifact = write_artifact(tmp_path, example)
        results.append(
            {
                "example_id": example_id,
                "artifact": str(artifact.relative_to(tmp_path)),
            }
        )
    manifest = tmp_path / "routing-quality-evidence.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "model_file": str(model_file.relative_to(tmp_path)),
                "model_sha256": model_sha,
                "model_bytes": model_file.stat().st_size,
                "results": results,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def write_artifact(
    tmp_path: Path,
    example: dict[str, object],
    *,
    inference_millis: int = 12,
    force_candidate: str | None = None,
    example_id_override: str | None = None,
    model_sha_override: str | None = None,
) -> Path:
    example_id = str(example["id"])
    expected_label = str(example["label"])
    command = str(example["text"])
    artifact = tmp_path / "results" / f"{example_id}.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    is_route = expected_label in {"PHONE", "MAC", "CLOUD"}
    forced_route = force_candidate
    payload: dict[str, Any] = {
        "status": "PASS",
        "categoryCount": 1,
        "topLabel": forced_route or expected_label,
        "topScore": 0.91,
        "modelBytes": 4096,
        "modelSha256": model_sha_override
        or sha256_file(tmp_path / "models" / "tiny-router.tflite"),
        "exampleId": example_id_override or example_id,
        "commandSha256": command_sha256(command),
        "inferenceMillis": inference_millis,
        "nonAuthoritative": True,
    }
    if is_route or forced_route is not None:
        route = forced_route or expected_label
        payload.update(
            {
                "observationType": "Candidate",
                "observationRoute": route,
                "observationConfidence": 0.91,
            }
        )
    else:
        payload.update(
            {
                "observationType": "Rejected",
                "observationRoute": None,
                "observationConfidence": None,
                "observationReason": "TFLite Task Text classifier top label is not a GOFFY route.",
            }
        )
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    return artifact


def write_model_file(tmp_path: Path) -> Path:
    model_file = tmp_path / "models" / "tiny-router.tflite"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_bytes(b"goffy tiny classifier test model".ljust(4096, b"\0"))
    return model_file


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def eval_examples() -> list[dict[str, object]]:
    payload = json.loads(DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    examples = payload["examples"]
    assert isinstance(examples, list)
    return [
        example
        for example in examples
        if isinstance(example, dict) and example.get("split") == "eval"
    ]
