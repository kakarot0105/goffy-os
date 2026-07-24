from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

from scripts.verify_local_intent_router_corpus import (
    ALLOWED_LABELS,
    DEFAULT_CORPUS_PATH,
    JSON_SCHEMA_VERSION,
    verify_local_intent_router_corpus,
)


def test_default_local_intent_router_corpus_passes() -> None:
    report = verify_local_intent_router_corpus(DEFAULT_CORPUS_PATH)

    assert report.ok
    assert report.schema_version == JSON_SCHEMA_VERSION
    assert report.example_count == 52
    assert report.eval_counts == {"CLOUD": 4, "MAC": 6, "PHONE": 4, "UNKNOWN": 4}
    assert report.train_counts == {"CLOUD": 8, "MAC": 10, "PHONE": 8, "UNKNOWN": 8}


def test_corpus_blocks_executable_tool_for_unknown(tmp_path: Path) -> None:
    corpus = load_default_corpus()
    unknown = next(example for example in corpus_examples(corpus) if example["label"] == "UNKNOWN")
    unknown["capability"] = "mac.files.read"
    path = write_corpus(tmp_path, corpus)

    report = verify_local_intent_router_corpus(path)

    assert not report.ok
    assert any(
        "UNKNOWN examples must not point at executable tools" in item for item in report.blockers
    )


def test_corpus_blocks_blocked_tags_on_route_label(tmp_path: Path) -> None:
    corpus = load_default_corpus()
    phone = next(example for example in corpus_examples(corpus) if example["label"] == "PHONE")
    phone["risk_tags"] = ["blocked"]
    path = write_corpus(tmp_path, corpus)

    report = verify_local_intent_router_corpus(path)

    assert not report.ok
    assert any("routed labels must not carry blocked risk tags" in item for item in report.blockers)


def test_corpus_blocks_unbalanced_eval_split(tmp_path: Path) -> None:
    corpus = load_default_corpus()
    for example in corpus_examples(corpus):
        if example["label"] == "CLOUD" and example["split"] == "eval":
            example["split"] = "train"
    path = write_corpus(tmp_path, corpus)

    report = verify_local_intent_router_corpus(path)

    assert not report.ok
    assert "CLOUD: at least 4 eval examples are required" in report.blockers


def test_corpus_blocks_missing_train_split(tmp_path: Path) -> None:
    corpus = load_default_corpus()
    for example in corpus_examples(corpus):
        if example["label"] == "PHONE" and example["split"] == "train":
            example["split"] = "eval"
    path = write_corpus(tmp_path, corpus)

    report = verify_local_intent_router_corpus(path)

    assert not report.ok
    assert "PHONE: at least 8 train examples are required" in report.blockers


def load_default_corpus() -> dict[str, object]:
    payload = json.loads(DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    labels = payload.get("labels")
    assert isinstance(labels, list)
    assert {str(label) for label in labels} == ALLOWED_LABELS
    return cast("dict[str, object]", copy.deepcopy(payload))


def corpus_examples(payload: dict[str, object]) -> list[dict[str, Any]]:
    examples = payload.get("examples")
    assert isinstance(examples, list)
    return [example for example in examples if isinstance(example, dict)]


def write_corpus(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
