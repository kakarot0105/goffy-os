from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS_PATH = ROOT / "docs" / "architecture" / "local-intent-router-corpus.json"

JSON_SCHEMA_VERSION = "goffy.local-intent-router-corpus.v1"
ALLOWED_LABELS = frozenset({"PHONE", "MAC", "CLOUD", "UNKNOWN"})
ALLOWED_SPLITS = frozenset({"train", "eval"})
ALLOWED_RISK_TAGS = frozenset(
    {
        "safe",
        "confirm",
        "cloud_external",
        "ambiguous",
        "blocked",
        "destructive",
        "surveillance",
        "secrets",
    }
)
ROUTE_LABELS = frozenset({"PHONE", "MAC", "CLOUD"})
ROUTE_BLOCKED_TAGS = frozenset({"blocked", "destructive", "surveillance", "secrets"})
UNKNOWN_REQUIRED_TAGS = frozenset({"ambiguous", "blocked"})

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_]{2,80}$")
SAFE_CAPABILITY = re.compile(r"^(none|blocked|[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SECRET_LIKE_TEXT = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)

DEFAULT_MIN_EXAMPLES_PER_LABEL = 12
DEFAULT_MIN_TRAIN_EXAMPLES_PER_LABEL = 4
DEFAULT_MIN_EVAL_EXAMPLES_PER_LABEL = 4
HARD_MAX_COMMAND_CHARS = 160


@dataclass(frozen=True)
class CorpusExample:
    id: str
    text: str
    label: str
    split: str
    capability: str
    risk_tags: tuple[str, ...]


@dataclass(frozen=True)
class LocalIntentRouterCorpusReport:
    schema_version: str
    ok: bool
    example_count: int
    labels: tuple[str, ...]
    train_counts: dict[str, int]
    eval_counts: dict[str, int]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def verify_local_intent_router_corpus(
    path: Path = DEFAULT_CORPUS_PATH,
) -> LocalIntentRouterCorpusReport:
    blockers: list[str] = []
    warnings: list[str] = []
    examples: list[CorpusExample] = []

    try:
        payload = load_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return LocalIntentRouterCorpusReport(
            schema_version=JSON_SCHEMA_VERSION,
            ok=False,
            example_count=0,
            labels=(),
            train_counts={},
            eval_counts={},
            blockers=(str(exc),),
            warnings=(),
        )

    if payload.get("schema_version") != JSON_SCHEMA_VERSION:
        blockers.append("local intent router corpus schema_version mismatch")
    reviewed_at = string_value(payload.get("reviewed_at"))
    if reviewed_at is None or DATE.match(reviewed_at) is None:
        blockers.append("reviewed_at must be an ISO date")

    declared_labels = tuple(string_items(payload.get("labels")))
    if frozenset(declared_labels) != ALLOWED_LABELS or len(declared_labels) != len(ALLOWED_LABELS):
        blockers.append(f"labels must be exactly {sorted(ALLOWED_LABELS)}")

    policy = mapping_value(payload.get("policy"))
    max_command_chars, min_examples, min_train_examples, min_eval_examples = validate_policy(
        policy,
        blockers,
    )

    raw_examples = mapping_items(payload.get("examples"))
    if not raw_examples:
        blockers.append("examples must be a non-empty list")

    seen_ids: set[str] = set()
    seen_texts: set[str] = set()
    for index, raw_example in enumerate(raw_examples):
        label = f"examples[{index}]"
        try:
            example = parse_example(raw_example, label=label)
        except ValueError as exc:
            blockers.append(str(exc))
            continue
        examples.append(example)
        blockers.extend(
            validate_example(
                example,
                label=label,
                seen_ids=seen_ids,
                seen_texts=seen_texts,
                max_command_chars=max_command_chars,
            )
        )

    train_counts = split_counts(examples, split="train")
    eval_counts = split_counts(examples, split="eval")
    total_counts = Counter(example.label for example in examples)
    for allowed_label in sorted(ALLOWED_LABELS):
        if total_counts[allowed_label] < min_examples:
            blockers.append(f"{allowed_label}: at least {min_examples} examples are required")
        if train_counts.get(allowed_label, 0) < min_train_examples:
            blockers.append(
                f"{allowed_label}: at least {min_train_examples} train examples are required"
            )
        if eval_counts.get(allowed_label, 0) < min_eval_examples:
            blockers.append(
                f"{allowed_label}: at least {min_eval_examples} eval examples are required"
            )

    if len(examples) < 40:
        warnings.append("corpus has fewer than 40 examples; routing quality evidence may be weak")

    deduped_blockers = tuple(dict.fromkeys(blockers))
    return LocalIntentRouterCorpusReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=not deduped_blockers,
        example_count=len(examples),
        labels=tuple(sorted(ALLOWED_LABELS)),
        train_counts=dict(sorted(train_counts.items())),
        eval_counts=dict(sorted(eval_counts.items())),
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def validate_policy(
    policy: dict[str, object],
    blockers: list[str],
) -> tuple[int, int, int, int]:
    if not policy:
        blockers.append("policy is required")
        return (
            HARD_MAX_COMMAND_CHARS,
            DEFAULT_MIN_EXAMPLES_PER_LABEL,
            DEFAULT_MIN_TRAIN_EXAMPLES_PER_LABEL,
            DEFAULT_MIN_EVAL_EXAMPLES_PER_LABEL,
        )
    if policy.get("default_build_must_remain_model_free") is not True:
        blockers.append("policy must keep the default build model-free")
    if policy.get("observations_must_remain_non_authoritative") is not True:
        blockers.append("policy must keep local classifier observations non-authoritative")
    if policy.get("execution_authority") != "observe_only":
        blockers.append("policy execution_authority must be observe_only")

    declared_splits = frozenset(string_items(policy.get("allowed_splits")))
    if declared_splits != ALLOWED_SPLITS:
        blockers.append(f"policy allowed_splits must be exactly {sorted(ALLOWED_SPLITS)}")

    max_command_chars = int_value(policy.get("max_command_chars"))
    if max_command_chars is None or max_command_chars <= 0:
        blockers.append("policy max_command_chars must be a positive integer")
        max_command_chars = HARD_MAX_COMMAND_CHARS
    elif max_command_chars > HARD_MAX_COMMAND_CHARS:
        blockers.append(f"policy max_command_chars must be at most {HARD_MAX_COMMAND_CHARS}")

    min_examples = int_value(policy.get("min_examples_per_label"))
    if min_examples is None or min_examples < DEFAULT_MIN_EXAMPLES_PER_LABEL:
        blockers.append(
            f"policy min_examples_per_label must be at least {DEFAULT_MIN_EXAMPLES_PER_LABEL}"
        )
        min_examples = DEFAULT_MIN_EXAMPLES_PER_LABEL

    min_train_examples = int_value(policy.get("min_train_examples_per_label"))
    if min_train_examples is None or min_train_examples < DEFAULT_MIN_TRAIN_EXAMPLES_PER_LABEL:
        blockers.append(
            "policy min_train_examples_per_label must be at least "
            f"{DEFAULT_MIN_TRAIN_EXAMPLES_PER_LABEL}"
        )
        min_train_examples = DEFAULT_MIN_TRAIN_EXAMPLES_PER_LABEL

    min_eval_examples = int_value(policy.get("min_eval_examples_per_label"))
    if min_eval_examples is None or min_eval_examples < DEFAULT_MIN_EVAL_EXAMPLES_PER_LABEL:
        blockers.append(
            "policy min_eval_examples_per_label must be at least "
            f"{DEFAULT_MIN_EVAL_EXAMPLES_PER_LABEL}"
        )
        min_eval_examples = DEFAULT_MIN_EVAL_EXAMPLES_PER_LABEL

    return max_command_chars, min_examples, min_train_examples, min_eval_examples


def parse_example(raw_example: dict[str, object], *, label: str) -> CorpusExample:
    example_id = string_value(raw_example.get("id"))
    text = string_value(raw_example.get("text"))
    route_label = string_value(raw_example.get("label"))
    split = string_value(raw_example.get("split"))
    capability = string_value(raw_example.get("capability"))
    risk_tags = tuple(string_items(raw_example.get("risk_tags")))
    missing = [
        name
        for name, value in (
            ("id", example_id),
            ("text", text),
            ("label", route_label),
            ("split", split),
            ("capability", capability),
        )
        if value is None
    ]
    if missing:
        raise ValueError(f"{label}: missing required fields {missing}")
    if not risk_tags:
        raise ValueError(f"{label}: risk_tags must be a non-empty list")
    return CorpusExample(
        id=example_id or "",
        text=text or "",
        label=route_label or "",
        split=split or "",
        capability=capability or "",
        risk_tags=risk_tags,
    )


def validate_example(
    example: CorpusExample,
    *,
    label: str,
    seen_ids: set[str],
    seen_texts: set[str],
    max_command_chars: int,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if SAFE_ID.match(example.id) is None:
        blockers.append(f"{label}: id must be safe lower snake case")
    elif example.id in seen_ids:
        blockers.append(f"{example.id}: duplicate example id")
    seen_ids.add(example.id)

    normalized_text = " ".join(example.text.split())
    if normalized_text != example.text:
        blockers.append(f"{example.id}: text must be normalized single-line text")
    if not normalized_text:
        blockers.append(f"{example.id}: text must not be blank")
    if len(normalized_text) > max_command_chars:
        blockers.append(f"{example.id}: text exceeds {max_command_chars} characters")
    if contains_unsafe_text(normalized_text):
        blockers.append(f"{example.id}: text contains unsafe control characters or secret patterns")
    text_key = normalized_text.casefold()
    if text_key in seen_texts:
        blockers.append(f"{example.id}: duplicate example text")
    seen_texts.add(text_key)

    if example.label not in ALLOWED_LABELS:
        blockers.append(f"{example.id}: label must be one of {sorted(ALLOWED_LABELS)}")
    if example.split not in ALLOWED_SPLITS:
        blockers.append(f"{example.id}: split must be one of {sorted(ALLOWED_SPLITS)}")
    if SAFE_CAPABILITY.match(example.capability) is None:
        blockers.append(f"{example.id}: capability must be none, blocked, or a dotted tool name")

    tag_set = frozenset(example.risk_tags)
    unknown_tags = tag_set - ALLOWED_RISK_TAGS
    if unknown_tags:
        blockers.append(f"{example.id}: risk_tags contains unsupported tags {sorted(unknown_tags)}")
    if "safe" in tag_set and len(tag_set) > 1:
        blockers.append(f"{example.id}: safe risk tag must not be combined with other tags")
    if example.label in ROUTE_LABELS and tag_set.intersection(ROUTE_BLOCKED_TAGS):
        blockers.append(f"{example.id}: routed labels must not carry blocked risk tags")
    if example.label == "CLOUD" and "cloud_external" not in tag_set:
        blockers.append(f"{example.id}: CLOUD examples must carry cloud_external risk")
    if example.label == "UNKNOWN" and not tag_set.intersection(UNKNOWN_REQUIRED_TAGS):
        blockers.append(f"{example.id}: UNKNOWN examples must be ambiguous or blocked")
    if example.label == "UNKNOWN" and example.capability not in {"none", "blocked"}:
        blockers.append(f"{example.id}: UNKNOWN examples must not point at executable tools")
    return tuple(blockers)


def split_counts(examples: Sequence[CorpusExample], *, split: str) -> Counter[str]:
    return Counter(example.label for example in examples if example.split == split)


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


def string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def contains_unsafe_text(value: str) -> bool:
    return any(char.isprintable() is False for char in value) or any(
        pattern.search(value) for pattern in SECRET_LIKE_TEXT
    )


def render_json(report: LocalIntentRouterCorpusReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_text(report: LocalIntentRouterCorpusReport) -> str:
    lines = [
        "GOFFY local intent router corpus",
        f"schema: {report.schema_version}",
        f"ok: {str(report.ok).lower()}",
        f"examples: {report.example_count}",
        f"labels: {', '.join(report.labels)}",
        f"train counts: {report.train_counts}",
        f"eval counts: {report.eval_counts}",
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
        description="Verify the GOFFY seed corpus for tiny local intent-router models.",
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = verify_local_intent_router_corpus(args.corpus)
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
