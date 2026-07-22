from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_local_intent_router_corpus import (  # noqa: E402
    ALLOWED_LABELS,
    DEFAULT_CORPUS_PATH,
    CorpusExample,
    load_json_object,
    mapping_items,
    string_items,
    verify_local_intent_router_corpus,
)

JSON_SCHEMA_VERSION = "goffy.tflite-task-text-training-package.v1"
DEFAULT_OUTPUT_ROOT = ROOT / ".goffy-validation" / "tflite-task-text-training-package"
MODEL_MAKER_MODEL_SPEC = "average_word_vec"
MAX_TINY_CLASSIFIER_BYTES = 8 * 1024 * 1024
TRAIN_CSV = "train.csv"
DEV_CSV = "dev.csv"
LABELS_TXT = "labels.txt"
TRAINING_SCRIPT = "train_with_model_maker.py"
PACKAGE_README = "README.md"
MANIFEST = "training-package-manifest.json"


@dataclass(frozen=True)
class PackageFile:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class TrainingPackageReport:
    schema_version: str
    ok: bool
    status: str
    output_directory: str
    corpus_path: str
    corpus_sha256: str | None
    model_spec: str
    labels: tuple[str, ...]
    train_rows: int
    eval_rows: int
    files: tuple[PackageFile, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def default_output_directory(root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return root / timestamp


def build_report(
    *,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    output_directory: Path | None = None,
) -> TrainingPackageReport:
    resolved_corpus = corpus_path.expanduser().resolve()
    output_root = (output_directory or default_output_directory()).expanduser().resolve()
    blockers: list[str] = []
    warnings: list[str] = []

    corpus_report = verify_local_intent_router_corpus(resolved_corpus)
    warnings.extend(f"corpus: {warning}" for warning in corpus_report.warnings)
    if not corpus_report.ok:
        blockers.extend(f"corpus: {blocker}" for blocker in corpus_report.blockers)

    blockers.extend(output_directory_blockers(output_root))
    if blockers:
        blocked_corpus_sha256, sha_blockers = safe_sha256_file(resolved_corpus)
        blockers.extend(sha_blockers)
        return TrainingPackageReport(
            schema_version=JSON_SCHEMA_VERSION,
            ok=False,
            status="BLOCKED",
            output_directory=str(output_root),
            corpus_path=str(resolved_corpus),
            corpus_sha256=blocked_corpus_sha256,
            model_spec=MODEL_MAKER_MODEL_SPEC,
            labels=(),
            train_rows=0,
            eval_rows=0,
            files=(),
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    examples = load_verified_examples(resolved_corpus)
    train_examples = tuple(example for example in examples if example.split == "train")
    eval_examples = tuple(example for example in examples if example.split == "eval")
    labels = tuple(sorted(ALLOWED_LABELS))

    output_root.mkdir(parents=True, exist_ok=True)
    write_model_maker_csv(output_root / TRAIN_CSV, train_examples)
    write_model_maker_csv(output_root / DEV_CSV, eval_examples)
    write_labels(output_root / LABELS_TXT, labels)
    write_training_script(output_root / TRAINING_SCRIPT)
    write_package_readme(output_root / PACKAGE_README)

    package_files = tuple(
        package_file(output_root, output_root / name)
        for name in (TRAIN_CSV, DEV_CSV, LABELS_TXT, TRAINING_SCRIPT, PACKAGE_README)
    )
    manifest_file = write_manifest(
        output_root=output_root,
        corpus_path=resolved_corpus,
        labels=labels,
        train_examples=train_examples,
        eval_examples=eval_examples,
        package_files=package_files,
    )
    all_files = (*package_files, package_file(output_root, manifest_file))
    return TrainingPackageReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=True,
        status="CREATED",
        output_directory=str(output_root),
        corpus_path=str(resolved_corpus),
        corpus_sha256=sha256_file(resolved_corpus),
        model_spec=MODEL_MAKER_MODEL_SPEC,
        labels=labels,
        train_rows=len(train_examples),
        eval_rows=len(eval_examples),
        files=all_files,
        blockers=(),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def output_directory_blockers(output_root: Path) -> tuple[str, ...]:
    if not output_root.exists():
        return ()
    if not output_root.is_dir():
        return ("output path exists and is not a directory",)
    try:
        next(output_root.iterdir())
    except StopIteration:
        return ()
    except OSError as exc:
        return (f"output directory cannot be inspected: {exc}",)
    return ("output directory must be empty to avoid mixing stale training artifacts",)


def load_verified_examples(corpus_path: Path) -> tuple[CorpusExample, ...]:
    payload = load_json_object(corpus_path)
    examples: list[CorpusExample] = []
    for item in mapping_items(payload.get("examples")):
        examples.append(
            CorpusExample(
                id=str(item.get("id", "")),
                text=str(item.get("text", "")),
                label=str(item.get("label", "")),
                split=str(item.get("split", "")),
                capability=str(item.get("capability", "")),
                risk_tags=tuple(string_items(item.get("risk_tags"))),
            )
        )
    return tuple(examples)


def write_model_maker_csv(path: Path, examples: Sequence[CorpusExample]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("sentence", "label"))
        writer.writeheader()
        for example in examples:
            writer.writerow({"sentence": example.text, "label": example.label})


def write_labels(path: Path, labels: Sequence[str]) -> None:
    path.write_text("".join(f"{label}\n" for label in labels), encoding="utf-8")


def write_training_script(path: Path) -> None:
    path.write_text(TRAINING_SCRIPT_TEXT, encoding="utf-8")


def write_package_readme(path: Path) -> None:
    path.write_text(PACKAGE_README_TEXT, encoding="utf-8")


def write_manifest(
    *,
    output_root: Path,
    corpus_path: Path,
    labels: Sequence[str],
    train_examples: Sequence[CorpusExample],
    eval_examples: Sequence[CorpusExample],
    package_files: Sequence[PackageFile],
) -> Path:
    manifest_path = output_root / MANIFEST
    payload = {
        "schema_version": JSON_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_corpus": {
            "path": str(corpus_path),
            "sha256": sha256_file(corpus_path),
        },
        "reuse_first_source": {
            "library": "TensorFlow Lite Model Maker",
            "model_spec": MODEL_MAKER_MODEL_SPEC,
            "android_runtime": "TensorFlow Lite Task Text NLClassifier",
            "license": "Apache-2.0",
            "source_urls": [
                "https://developers.google.com/edge/litert/libraries/modify/text_classification",
                "https://github.com/tensorflow/tflite-support",
            ],
        },
        "policy": {
            "default_build_must_remain_model_free": True,
            "observations_must_remain_non_authoritative": True,
            "max_model_bytes": MAX_TINY_CLASSIFIER_BYTES,
            "required_physical_gate": "scripts/run_moto_g_tflite_task_text_eval_suite.py",
        },
        "dataset": {
            "text_column": "sentence",
            "label_column": "label",
            "labels": list(labels),
            "train_rows": len(train_examples),
            "eval_rows": len(eval_examples),
            "train_counts": label_counts(train_examples),
            "eval_counts": label_counts(eval_examples),
        },
        "files": [asdict(file) for file in package_files],
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def label_counts(examples: Sequence[CorpusExample]) -> dict[str, int]:
    counts = Counter(example.label for example in examples)
    return {label: counts[label] for label in sorted(ALLOWED_LABELS)}


def package_file(output_root: Path, path: Path) -> PackageFile:
    return PackageFile(
        path=str(path.relative_to(output_root)),
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_sha256_file(path: Path) -> tuple[str | None, tuple[str, ...]]:
    if not path.is_file():
        return None, ()
    try:
        return sha256_file(path), ()
    except OSError as exc:
        return None, (f"corpus hash could not be read: {exc}",)


def render_text(report: TrainingPackageReport) -> str:
    lines = [
        "GOFFY TFLite Task Text Model Maker training package",
        f"status: {report.status}",
        f"ok: {str(report.ok).lower()}",
        f"output: {report.output_directory}",
        f"model_spec: {report.model_spec}",
        f"train rows: {report.train_rows}",
        f"eval rows: {report.eval_rows}",
    ]
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    if report.files:
        lines.append("files:")
        lines.extend(
            f"- {file.path} sha256={file.sha256} bytes={file.bytes}" for file in report.files
        )
    return "\n".join(lines)


def render_json(report: TrainingPackageReport) -> str:
    return json.dumps(asdict(report), indent=2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a GOFFY local intent-router dataset package for TensorFlow Lite "
            "Model Maker average_word_vec training."
        ),
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


TRAINING_SCRIPT_TEXT = '''\
"""Train GOFFY's tiny Task Text intent router with TensorFlow Lite Model Maker.

Run this generated script in an isolated ML environment or Colab. Do not add
TensorFlow, Model Maker, or generated model files to GOFFY's normal dev venv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tflite_model_maker import model_spec, text_classifier
from tflite_model_maker.text_classifier import DataLoader

MAX_MODEL_BYTES = 8 * 1024 * 1024
MODEL_SPEC = "average_word_vec"
MANIFEST = "training-package-manifest.json"
VERIFIED_INPUTS = ("train.csv", "dev.csv", "labels.txt")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=8)
    return parser.parse_args()


def resolve_export_dir(dataset_dir: Path, export_dir: Path | None) -> Path:
    if export_dir is None:
        return dataset_dir / "average_word_vec"
    candidate = export_dir.expanduser()
    if not candidate.is_absolute():
        candidate = dataset_dir / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(dataset_dir)
    except ValueError as exc:
        raise ValueError("export dir must stay under the generated training package") from exc
    if resolved.exists():
        if not resolved.is_dir():
            raise ValueError("export dir exists and is not a directory")
        if any(resolved.iterdir()):
            raise ValueError("export dir must be empty before training")
    return resolved


def load_verified_manifest(dataset_dir: Path) -> dict[str, str]:
    manifest_path = dataset_dir / MANIFEST
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "goffy.tflite-task-text-training-package.v1":
        raise ValueError("training package manifest schema mismatch")
    file_items = payload.get("files")
    if not isinstance(file_items, list):
        raise ValueError("training package manifest files must be a list")
    hashes: dict[str, str] = {}
    for item in file_items:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        digest = item.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            hashes[path] = digest
    for relative_path in VERIFIED_INPUTS:
        actual = sha256_file(dataset_dir / relative_path)
        expected = hashes.get(relative_path)
        if actual != expected:
            raise ValueError(f"{relative_path} does not match training package manifest")
    return {relative_path: hashes[relative_path] for relative_path in VERIFIED_INPUTS}


def main() -> int:
    args = parse_args()
    dataset_dir = args.dataset_dir.expanduser().resolve()
    input_hashes = load_verified_manifest(dataset_dir)
    export_dir = resolve_export_dir(dataset_dir, args.export_dir)
    spec = model_spec.get(MODEL_SPEC)
    train_data = DataLoader.from_csv(
        filename=str(dataset_dir / "train.csv"),
        text_column="sentence",
        label_column="label",
        model_spec=spec,
        is_training=True,
    )
    eval_data = DataLoader.from_csv(
        filename=str(dataset_dir / "dev.csv"),
        text_column="sentence",
        label_column="label",
        model_spec=spec,
        is_training=False,
    )
    model = text_classifier.create(
        train_data,
        model_spec=spec,
        epochs=args.epochs,
        batch_size=args.batch_size,
    )
    loss, accuracy = model.evaluate(eval_data)
    export_dir.mkdir(parents=True, exist_ok=True)
    model.export(export_dir=str(export_dir))
    model_file = export_dir / "model.tflite"
    if not model_file.is_file():
        raise FileNotFoundError("Model Maker did not write model.tflite")
    model_bytes = model_file.stat().st_size
    if model_bytes <= 0 or model_bytes > MAX_MODEL_BYTES:
        raise ValueError(f"model.tflite must be 1..{MAX_MODEL_BYTES} bytes")
    report = {
        "schema_version": "goffy.tflite-task-text-model-maker-training.v1",
        "model_spec": MODEL_SPEC,
        "loss": float(loss),
        "accuracy": float(accuracy),
        "model_file": str(model_file),
        "model_sha256": sha256_file(model_file),
        "model_bytes": model_bytes,
        "input_hashes": input_hashes,
        "next_gate": "run scripts/run_moto_g_tflite_task_text_eval_suite.py on the Moto",
    }
    (export_dir / "goffy-training-report.json").write_text(
        json.dumps(report, indent=2) + "\\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


PACKAGE_README_TEXT = f"""\
# GOFFY Task Text Training Package

This package is generated from the verified GOFFY local intent-router corpus.

Files:

- `{TRAIN_CSV}`: Model Maker training rows with `sentence,label` columns.
- `{DEV_CSV}`: Model Maker eval rows with `sentence,label` columns.
- `{LABELS_TXT}`: Expected labels, including `UNKNOWN`.
- `{TRAINING_SCRIPT}`: Optional isolated/Colab training script.
- `{MANIFEST}`: Corpus hash, file hashes, counts, source links, and safety policy.

From the GOFFY repo, verify this package and the local training environment:

```bash
.venv/bin/python scripts/verify_tflite_task_text_training_environment.py \\
  --package-dir /path/to/this/generated/package
```

Audited Docker export flow from the GOFFY repo:

```bash
.venv/bin/python scripts/run_tflite_task_text_model_maker_docker.py \\
  --package-dir /path/to/this/generated/package \\
  --image ghcr.io/goffy/task-text-export@sha256:<audited-image-digest> \\
  --image-audit-evidence /path/to/image-audit.json \\
  --execute \\
  --confirm-docker-run
```

The Docker helper fails closed until the export image is immutable
`@sha256:`-pinned and accompanied by audit evidence reporting zero critical,
high, or medium findings. The image must contain the required Model Maker export
stack ahead of time; the runner does not perform live `apt-get` or `pip install`
during execution. Generated `.tflite` models must not be committed or packaged
into default GOFFY LITE builds. The runner defaults to 20 epochs to match this
package helper and avoid repeating the failed one-epoch baseline.

Minimum audit evidence shape:

```json
{{
  "schema_version": "goffy.tflite-task-text-export-image-audit.v1",
  "image": "ghcr.io/goffy/task-text-export@sha256:<audited-image-digest>",
  "ok": true,
  "vulnerability_counts": {{
    "critical": 0,
    "high": 0,
    "medium": 0
  }}
}}
```

Manual isolated fallback, for investigation only:

```bash
python3.10 -m venv /tmp/goffy-model-maker-venv
source /tmp/goffy-model-maker-venv/bin/activate
pip install tflite-model-maker==0.4.3
cd /path/to/this/generated/package
python {TRAINING_SCRIPT} --dataset-dir . --export-dir average_word_vec
```

The manual fallback is not the production-safe path and may fail on macOS arm64
or current Python versions because Model Maker's legacy dependency graph is not
part of the normal GOFFY Python 3.12 verifier. Do not install TensorFlow or
Model Maker into the repo venv.
The training helper verifies this package's manifest before training, rejects
non-empty export directories, and keeps exports under the generated package
directory. After training, run the physical Moto gate from the GOFFY repo:

```bash
.venv/bin/python scripts/run_moto_g_tflite_task_text_eval_suite.py \\
  --execute \\
  --confirm-device-mutation \\
  --model /path/to/average_word_vec/model.tflite
```
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        corpus_path=args.corpus,
        output_directory=args.output_directory,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
