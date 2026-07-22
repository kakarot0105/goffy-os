from __future__ import annotations

import copy
import csv
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest
import scripts.create_tflite_task_text_training_package as package
from scripts.verify_local_intent_router_corpus import DEFAULT_CORPUS_PATH


def test_training_package_exports_model_maker_dataset_and_manifest(tmp_path: Path) -> None:
    output = tmp_path / "training-package"

    report = package.build_report(output_directory=output)

    assert report.ok
    assert report.status == "CREATED"
    assert report.train_rows == 33
    assert report.eval_rows == 17
    assert report.labels == ("CLOUD", "MAC", "PHONE", "UNKNOWN")

    train_rows = read_csv_rows(output / package.TRAIN_CSV)
    dev_rows = read_csv_rows(output / package.DEV_CSV)
    assert len(train_rows) == 33
    assert len(dev_rows) == 17
    assert set(train_rows[0]) == {"sentence", "label"}
    assert {row["label"] for row in train_rows + dev_rows} == set(report.labels)

    labels = (output / package.LABELS_TXT).read_text(encoding="utf-8").splitlines()
    assert labels == ["CLOUD", "MAC", "PHONE", "UNKNOWN"]

    training_script = (output / package.TRAINING_SCRIPT).read_text(encoding="utf-8")
    assert 'MODEL_SPEC = "average_word_vec"' in training_script
    assert 'text_column="sentence"' in training_script
    assert 'label_column="label"' in training_script
    assert "MAX_MODEL_BYTES = 8 * 1024 * 1024" in training_script
    assert "def load_verified_manifest" in training_script
    assert "def resolve_export_dir" in training_script
    assert "export dir must stay under the generated training package" in training_script
    assert "export dir must be empty before training" in training_script
    assert "input_hashes" in training_script

    manifest = json.loads((output / package.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == package.JSON_SCHEMA_VERSION
    assert manifest["source_corpus"]["sha256"] == package.sha256_file(DEFAULT_CORPUS_PATH)
    assert manifest["reuse_first_source"]["model_spec"] == "average_word_vec"
    assert manifest["policy"]["default_build_must_remain_model_free"] is True
    assert manifest["policy"]["observations_must_remain_non_authoritative"] is True
    assert manifest["policy"]["max_model_bytes"] == 8 * 1024 * 1024
    assert manifest["dataset"]["train_counts"] == {
        "CLOUD": 8,
        "MAC": 9,
        "PHONE": 8,
        "UNKNOWN": 8,
    }
    assert manifest["dataset"]["eval_counts"] == {
        "CLOUD": 4,
        "MAC": 5,
        "PHONE": 4,
        "UNKNOWN": 4,
    }

    manifest_files = {item["path"]: item for item in manifest["files"]}
    for file in report.files:
        written = output / file.path
        assert written.is_file()
        assert file.sha256 == package.sha256_file(written)
        assert file.bytes == written.stat().st_size
    assert set(manifest_files) == {
        package.TRAIN_CSV,
        package.DEV_CSV,
        package.LABELS_TXT,
        package.TRAINING_SCRIPT,
        package.PACKAGE_README,
    }


def test_training_package_rejects_non_empty_output_without_writing(tmp_path: Path) -> None:
    output = tmp_path / "training-package"
    output.mkdir()
    stale = output / "stale.txt"
    stale.write_text("old\n", encoding="utf-8")

    report = package.build_report(output_directory=output)

    assert not report.ok
    assert report.status == "BLOCKED"
    assert any("must be empty" in blocker for blocker in report.blockers)
    assert sorted(path.name for path in output.iterdir()) == ["stale.txt"]


def test_training_package_rejects_invalid_corpus_before_writing(tmp_path: Path) -> None:
    corpus = load_default_corpus()
    first = corpus_examples(corpus)[0]
    first["id"] = "../escape"
    output = tmp_path / "training-package"

    report = package.build_report(
        corpus_path=write_corpus(tmp_path, corpus),
        output_directory=output,
    )

    assert not report.ok
    assert report.status == "BLOCKED"
    assert any("id must be safe lower snake case" in blocker for blocker in report.blockers)
    assert not output.exists()


def test_training_package_reports_corpus_hash_read_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    corpus = load_default_corpus()
    first = corpus_examples(corpus)[0]
    first["id"] = "../escape"
    corpus_path = write_corpus(tmp_path, corpus)

    def failing_sha256(path: Path) -> str:
        raise PermissionError(f"cannot read {path}")

    monkeypatch.setattr(package, "sha256_file", failing_sha256)

    report = package.build_report(
        corpus_path=corpus_path,
        output_directory=tmp_path / "training-package",
    )

    assert not report.ok
    assert report.corpus_sha256 is None
    assert any("corpus hash could not be read" in blocker for blocker in report.blockers)


def test_generated_helper_accepts_existing_empty_export_and_reports_input_hashes(
    tmp_path: Path,
) -> None:
    output = tmp_path / "training-package"
    report = package.build_report(output_directory=output)
    assert report.ok
    fake_site = write_fake_model_maker(tmp_path)
    export_dir = output / "empty-export"
    export_dir.mkdir()

    completed = run_generated_helper(
        script=output / package.TRAINING_SCRIPT,
        fake_site=fake_site,
        args=("--dataset-dir", str(output), "--export-dir", "empty-export"),
    )

    assert completed.returncode == 0, completed.stderr
    training_report = json.loads((export_dir / "goffy-training-report.json").read_text())
    assert training_report["model_bytes"] == (export_dir / "model.tflite").stat().st_size
    assert training_report["input_hashes"] == {
        package.TRAIN_CSV: package.sha256_file(output / package.TRAIN_CSV),
        package.DEV_CSV: package.sha256_file(output / package.DEV_CSV),
        package.LABELS_TXT: package.sha256_file(output / package.LABELS_TXT),
    }


def test_generated_helper_rejects_non_empty_export_dir(tmp_path: Path) -> None:
    output = tmp_path / "training-package"
    report = package.build_report(output_directory=output)
    assert report.ok
    fake_site = write_fake_model_maker(tmp_path)
    export_dir = output / "stale-export"
    export_dir.mkdir()
    (export_dir / "model.tflite").write_bytes(b"stale")

    completed = run_generated_helper(
        script=output / package.TRAINING_SCRIPT,
        fake_site=fake_site,
        args=("--dataset-dir", str(output), "--export-dir", "stale-export"),
    )

    assert completed.returncode != 0
    assert "export dir must be empty before training" in completed.stderr
    assert (export_dir / "model.tflite").read_bytes() == b"stale"


def test_generated_helper_rejects_tampered_package_before_export(tmp_path: Path) -> None:
    output = tmp_path / "training-package"
    report = package.build_report(output_directory=output)
    assert report.ok
    fake_site = write_fake_model_maker(tmp_path)
    export_dir = output / "tampered-export"
    with (output / package.TRAIN_CSV).open("a", encoding="utf-8") as handle:
        handle.write("tampered,PHONE\n")

    completed = run_generated_helper(
        script=output / package.TRAINING_SCRIPT,
        fake_site=fake_site,
        args=("--dataset-dir", str(output), "--export-dir", "tampered-export"),
    )

    assert completed.returncode != 0
    assert "train.csv does not match training package manifest" in completed.stderr
    assert not export_dir.exists()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_default_corpus() -> dict[str, object]:
    payload = json.loads(DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast("dict[str, object]", copy.deepcopy(payload))


def corpus_examples(payload: dict[str, object]) -> list[dict[str, Any]]:
    examples = payload.get("examples")
    assert isinstance(examples, list)
    return [example for example in examples if isinstance(example, dict)]


def write_corpus(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def run_generated_helper(
    *,
    script: Path,
    fake_site: Path,
    args: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(script), *args],
        text=True,
        capture_output=True,
        check=False,
        env={"PYTHONPATH": str(fake_site)},
        timeout=30,
    )


def write_fake_model_maker(tmp_path: Path) -> Path:
    fake_site = tmp_path / "fake-site"
    package_root = fake_site / "tflite_model_maker"
    text_classifier_root = package_root / "text_classifier"
    text_classifier_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text(
        "from . import model_spec, text_classifier\n",
        encoding="utf-8",
    )
    (package_root / "model_spec.py").write_text(
        'def get(name):\n    return {"name": name}\n',
        encoding="utf-8",
    )
    (text_classifier_root / "__init__.py").write_text(
        """
from pathlib import Path


class DataLoader:
    @staticmethod
    def from_csv(*, filename, text_column, label_column, model_spec, is_training):
        return {
            "filename": filename,
            "text_column": text_column,
            "label_column": label_column,
            "model_spec": model_spec,
            "is_training": is_training,
        }


class FakeModel:
    def evaluate(self, eval_data):
        return 0.25, 0.875

    def export(self, *, export_dir):
        Path(export_dir, "model.tflite").write_bytes(b"goffy fake model")


def create(train_data, *, model_spec, epochs, batch_size):
    return FakeModel()
""".lstrip(),
        encoding="utf-8",
    )
    return fake_site
