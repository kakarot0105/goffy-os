from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from _pytest.capture import CaptureFixture
from scripts.verify_local_intent_candidates import (
    HARD_MAX_CANDIDATE_MODEL_BYTES,
    HARD_MAX_IDLE_PSS_KB,
    HARD_MAX_SINGLE_INFERENCE_MILLIS,
    JSON_SCHEMA_VERSION,
    REQUIRED_PROTOTYPE_GATES,
    main,
    verify_local_intent_candidates,
)


def test_local_intent_candidate_registry_passes() -> None:
    report = verify_local_intent_candidates()

    assert report.ok
    assert report.candidate_count >= 5
    assert "tflite_task_text_nlclassifier" in report.prototype_candidate_ids
    assert "litert_lm_granite_350m" in report.rejected_candidate_ids


def test_local_intent_candidates_reject_schema_mismatch(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    payload["schema_version"] = "goffy.local-intent-classifier-candidates.v0"
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert "local intent candidate registry schema_version mismatch" in report.blockers


def test_local_intent_candidates_reject_prototype_in_default_build(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate_at(payload, 1)["default_build_inclusion"] = "allowed"
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any(
        "prototype candidates must stay out of default builds" in item for item in report.blockers
    )


def test_local_intent_candidates_reject_baseline_dependency(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate_at(payload, 0)["dependency_coordinate"] = (
        "org.tensorflow:tensorflow-lite-task-text:0.4.4"
    )
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any("current baseline must not declare a dependency" in item for item in report.blockers)
    assert any(
        "default-build candidates must not declare dependencies" in item for item in report.blockers
    )


def test_local_intent_candidates_reject_unknown_source_kind_with_file_url(
    tmp_path: Path,
) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate_at(payload, 1)["source_kind"] = "mystery_runtime"
    candidate_at(payload, 1)["source_urls"] = ["file:///tmp/model.tflite"]
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any("source_kind is unsupported" in item for item in report.blockers)
    assert any("source URLs must be https" in item for item in report.blockers)


def test_local_intent_candidates_accept_stricter_budgets(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    default_policy = default_policy_from(payload)
    default_policy["max_candidate_model_bytes"] = 4 * 1024 * 1024
    default_policy["max_single_inference_millis"] = 200
    default_policy["max_idle_pss_kb"] = 8192
    candidate = candidate_at(payload, 1)
    candidate["candidate_model_budget_bytes"] = 4 * 1024 * 1024
    candidate["max_inference_millis"] = 200
    candidate["max_idle_pss_kb"] = 8192
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert report.ok


def test_local_intent_candidates_accept_future_observe_only_nondefault_state(
    tmp_path: Path,
) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate = candidate_at(payload, 1)
    candidate["production_status"] = "accepted_observe_only_nondefault"
    candidate["physical_evidence"] = "internal:.goffy-validation/intent-classifier/moto.json"
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert report.ok


def test_local_intent_candidates_reject_accepted_state_without_physical_evidence(
    tmp_path: Path,
) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate_at(payload, 1)["production_status"] = "accepted_observe_only_nondefault"
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any("require physical_evidence" in item for item in report.blockers)


def test_local_intent_candidates_reject_invalid_accepted_physical_evidence(
    tmp_path: Path,
) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate = candidate_at(payload, 1)
    candidate["production_status"] = "accepted_observe_only_nondefault"
    candidate["physical_evidence"] = "not-a-proof-path"
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any(
        "physical_evidence must be an internal evidence reference" in item
        for item in report.blockers
    )


def test_local_intent_candidates_reject_nonprototype_accepted_status(
    tmp_path: Path,
) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    prior_art = dict(candidate_at(payload, 1))
    prior_art["id"] = "fasttext_prior_art"
    prior_art["decision"] = "prior_art_only"
    prior_art["production_status"] = "accepted_observe_only_nondefault"
    prior_art["execution_authority"] = "not_imported"
    prior_art["source_kind"] = "open_source_prior_art"
    prior_art["source_urls"] = ["https://github.com/facebookresearch/fastText"]
    rejected = dict(prior_art)
    rejected["id"] = "rejected_model"
    rejected["decision"] = "rejected_for_phone"
    candidates = candidates_from(payload)
    candidates.extend([prior_art, rejected])
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert (
        sum("non-selected candidates must not be active" in item for item in report.blockers) == 2
    )


def test_local_intent_candidates_reject_missing_prototype_gate(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate_at(payload, 1)["required_gates"] = ["license"]
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any("prototype candidate is missing required gates" in item for item in report.blockers)


def test_local_intent_candidates_reject_dynamic_dependency(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate_at(payload, 1)["dependency_coordinate"] = (
        "org.tensorflow:tensorflow-lite-task-text:latest.release"
    )
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any("must not use a dynamic version" in item for item in report.blockers)


def test_local_intent_candidates_reject_external_http_source(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate_at(payload, 1)["source_urls"] = ["http://example.com/model"]
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any("source URLs must be https" in item for item in report.blockers)


def test_local_intent_candidates_reject_duplicate_ids(tmp_path: Path) -> None:
    path = write_registry(tmp_path)
    payload = read_json(path)
    candidate_at(payload, 1)["id"] = candidate_at(payload, 0)["id"]
    write_json(path, payload)

    report = verify_local_intent_candidates(path)

    assert not report.ok
    assert any("duplicate candidate id" in item for item in report.blockers)


def test_local_intent_candidates_cli_reports_json(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    path = write_registry(tmp_path)

    exit_code = main(["--json", "--candidates-json", str(path)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["schema_version"] == JSON_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["prototype_candidate_ids"] == [
        "tflite_task_text_nlclassifier",
    ]


def write_registry(tmp_path: Path) -> Path:
    path = tmp_path / "candidates.json"
    write_json(
        path,
        {
            "schema_version": JSON_SCHEMA_VERSION,
            "reviewed_at": "2026-07-22",
            "default_policy": {
                "default_build_must_remain_model_free": True,
                "observations_must_remain_non_authoritative": True,
                "max_candidate_model_bytes": HARD_MAX_CANDIDATE_MODEL_BYTES,
                "max_default_apk_delta_bytes": 2 * 1024 * 1024,
                "max_single_inference_millis": HARD_MAX_SINGLE_INFERENCE_MILLIS,
                "max_idle_pss_kb": HARD_MAX_IDLE_PSS_KB,
            },
            "required_prototype_gates": sorted(REQUIRED_PROTOTYPE_GATES),
            "candidates": [
                {
                    "id": "goffy_micro_intent_fallback",
                    "name": "GOFFY micro intent fallback",
                    "source_kind": "internal",
                    "source_urls": ["internal:android/app/src/main/java/dev/goffy.kt"],
                    "license": "Apache-2.0",
                    "decision": "current_baseline",
                    "production_status": "active_non_executable",
                    "default_build_inclusion": "allowed",
                    "model_file_required": False,
                    "execution_authority": "observe_only",
                    "candidate_model_budget_bytes": 0,
                    "max_inference_millis": 0,
                    "max_idle_pss_kb": 0,
                    "required_gates": ["routing_quality", "audit_non_authoritative"],
                    "reasons": ["model-free"],
                    "risks": ["limited vocabulary"],
                    "next_action": "keep as baseline",
                },
                {
                    "id": "tflite_task_text_nlclassifier",
                    "name": "TensorFlow Lite Task Text NLClassifier",
                    "source_kind": "official_runtime",
                    "source_urls": ["https://central.sonatype.com/artifact/org.tensorflow"],
                    "license": "Apache-2.0",
                    "decision": "prototype_candidate",
                    "production_status": "blocked_until_physical_benchmark",
                    "default_build_inclusion": "blocked",
                    "model_file_required": True,
                    "execution_authority": "observe_only",
                    "candidate_model_budget_bytes": HARD_MAX_CANDIDATE_MODEL_BYTES,
                    "max_inference_millis": HARD_MAX_SINGLE_INFERENCE_MILLIS,
                    "max_idle_pss_kb": HARD_MAX_IDLE_PSS_KB,
                    "dependency_coordinate": "org.tensorflow:tensorflow-lite-task-text:0.4.4",
                    "required_gates": sorted(REQUIRED_PROTOTYPE_GATES),
                    "reasons": ["purpose-built classifier"],
                    "risks": ["needs benchmark"],
                    "next_action": "probe modelDebug only",
                },
            ],
        },
    )
    return path


def read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def candidate_at(payload: dict[str, object], index: int) -> dict[str, object]:
    candidates = candidates_from(payload)
    candidate = candidates[index]
    assert isinstance(candidate, dict)
    return cast("dict[str, object]", candidate)


def candidates_from(payload: dict[str, object]) -> list[object]:
    candidates = payload["candidates"]
    assert isinstance(candidates, list)
    return candidates


def default_policy_from(payload: dict[str, object]) -> dict[str, object]:
    default_policy = payload["default_policy"]
    assert isinstance(default_policy, dict)
    return cast("dict[str, object]", default_policy)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
