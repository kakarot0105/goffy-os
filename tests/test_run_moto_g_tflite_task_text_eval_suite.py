from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.run_moto_g_tflite_task_text_benchmark as benchmark
import scripts.run_moto_g_tflite_task_text_eval_suite as suite
from scripts.run_moto_g_device_smoke import CommandResult
from scripts.run_moto_g_tflite_task_text_benchmark import command_sha256
from scripts.verify_local_intent_router_corpus import DEFAULT_CORPUS_PATH
from scripts.verify_tflite_task_text_routing_quality import (
    EVIDENCE_SCHEMA_VERSION,
    load_corpus_examples,
    sha256_file,
)

SERIAL = "ZY32LBQLMQ"
ADB_DEVICES = (
    "List of devices attached\n"
    f"{SERIAL} device usb:2-1.2 product:kansas_g_sys model:moto_g___2025 device:kansas\n"
)


def test_plan_mode_does_not_execute_eval_commands(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = write_model(tmp_path)
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: Path("/opt/android/adb"))
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = suite.build_report(
        root=tmp_path,
        model=model,
        runner=runner,
    )

    assert report.ok
    assert not report.executed
    assert report.status == "PLANNED"
    assert report.example_count == 16
    assert all(example.status is suite.StepStatus.PLANNED for example in report.examples)
    assert seen == []


def test_execute_requires_device_mutation_confirmation(tmp_path: Path) -> None:
    model = write_model(tmp_path)

    report = suite.build_report(
        root=tmp_path,
        execute=True,
        model=model,
    )

    assert not report.ok
    assert not report.executed
    assert "missing explicit --confirm-device-mutation" in report.blockers


def test_execute_runs_eval_split_and_writes_quality_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = write_model(tmp_path)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    adb.parent.mkdir(parents=True)
    adb.write_text("", encoding="utf-8")
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: adb)
    fake_runner = FakeEvalRunner(model=model)

    report = suite.build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        model=model,
        runner=fake_runner,
        output_directory=tmp_path / "evidence",
    )

    assert report.ok
    assert report.executed
    assert report.quality_ok is True
    assert fake_runner.build_count == 1
    assert fake_runner.install_count == 2
    assert fake_runner.prepare_count == 1
    assert fake_runner.push_count == 1
    assert fake_runner.instrument_count == 16
    assert report.evidence_manifest is not None

    manifest = json.loads(Path(report.evidence_manifest).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert manifest["model_file"] == "models/tiny-router.tflite"
    assert manifest["model_sha256"] == sha256_file(tmp_path / "evidence/models/tiny-router.tflite")
    assert manifest["model_bytes"] == model.stat().st_size
    assert len(manifest["results"]) == 16


def test_execute_reports_quality_failure_for_unknown_false_positive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = write_model(tmp_path)
    adb = tmp_path / "sdk" / "platform-tools" / "adb"
    adb.parent.mkdir(parents=True)
    adb.write_text("", encoding="utf-8")
    monkeypatch.setattr(benchmark, "trusted_adb_path", lambda: adb)
    fake_runner = FakeEvalRunner(model=model, unknown_as_candidate=True)

    report = suite.build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        model=model,
        runner=fake_runner,
        output_directory=tmp_path / "evidence",
    )

    assert not report.ok
    assert report.quality_ok is False
    assert any("UNKNOWN rejection rate" in blocker for blocker in report.blockers)


def test_execute_rejects_non_empty_output_directory_before_adb(tmp_path: Path) -> None:
    model = write_model(tmp_path)
    output_directory = tmp_path / "evidence"
    stale_artifact = output_directory / "results" / "phone_ocr_009" / suite.EVAL_RESULT_FILENAME
    stale_artifact.parent.mkdir(parents=True)
    stale_artifact.write_text("{}\n", encoding="utf-8")
    seen: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path, timeout: int) -> CommandResult:
        seen.append(tuple(command))
        return CommandResult(0, "", "")

    report = suite.build_report(
        root=tmp_path,
        execute=True,
        confirm_device_mutation=True,
        model=model,
        runner=runner,
        output_directory=output_directory,
    )

    assert not report.ok
    assert not report.executed
    assert any("stale benchmark evidence" in blocker for blocker in report.blockers)
    assert seen == []


def test_invalid_corpus_id_blocks_before_artifact_path_planning(
    tmp_path: Path,
) -> None:
    model = write_model(tmp_path)
    corpus = tmp_path / "unsafe-corpus.json"
    corpus.write_text(json.dumps(unsafe_corpus_payload()) + "\n", encoding="utf-8")

    report = suite.build_report(
        root=tmp_path,
        model=model,
        corpus_path=corpus,
        output_directory=tmp_path / "evidence",
    )

    assert not report.ok
    assert report.status == "BLOCKED"
    assert report.examples == ()
    assert any("id must be safe lower snake case" in blocker for blocker in report.blockers)


class FakeEvalRunner:
    def __init__(self, *, model: Path, unknown_as_candidate: bool = False) -> None:
        self.model = model
        self.unknown_as_candidate = unknown_as_candidate
        self.examples = load_corpus_examples(DEFAULT_CORPUS_PATH, split="eval")
        self.current_example_id: str | None = None
        self.current_command: str | None = None
        self.build_count = 0
        self.install_count = 0
        self.prepare_count = 0
        self.push_count = 0
        self.instrument_count = 0

    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout: int,
    ) -> CommandResult:
        normalized = tuple(str(part) for part in command)
        if normalized == modeldebug_build_command(cwd):
            self.build_count += 1
            return CommandResult(0, "BUILD SUCCESSFUL\n", "")
        if normalized == (str(Path(normalized[0])), "devices", "-l"):
            return CommandResult(0, ADB_DEVICES, "")
        if normalized[-3:] == ("shell", "getprop", "ro.product.model"):
            return CommandResult(0, "moto g - 2025\n", "")
        if normalized[-3:-1] == ("install", "-r"):
            self.install_count += 1
            return CommandResult(0, "Success\n", "")
        if normalized[-3] == "push":
            self.push_count += 1
            return CommandResult(0, "1 file pushed\n", "")
        if normalized[-2:] == (
            "shell",
            "mkdir -p /sdcard/Android/data/dev.goffy.os.model/files/models",
        ):
            self.prepare_count += 1
            return CommandResult(0, "", "")
        if any("instrument" in part for part in normalized):
            remote_parts = shlex.split(normalized[-1])
            self.current_example_id = remote_parts[remote_parts.index("exampleId") + 1]
            self.current_command = remote_parts[remote_parts.index("command") + 1]
            self.instrument_count += 1
            return CommandResult(0, "OK (1 test)\n", "")
        if "pull" in normalized:
            destination = Path(normalized[-1])
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(self.artifact_payload()) + "\n",
                encoding="utf-8",
            )
            return CommandResult(0, "1 file pulled\n", "")
        return CommandResult(1, "", f"unexpected command: {normalized}")

    def artifact_payload(self) -> dict[str, object]:
        assert self.current_example_id is not None
        assert self.current_command is not None
        example = self.examples[self.current_example_id]
        label = example.label
        route = "PHONE" if self.unknown_as_candidate and label == "UNKNOWN" else label
        payload: dict[str, object] = {
            "status": "PASS",
            "categoryCount": 1,
            "topLabel": route,
            "topScore": 0.91,
            "modelBytes": self.model.stat().st_size,
            "modelSha256": sha256_file(self.model),
            "exampleId": self.current_example_id,
            "commandSha256": command_sha256(self.current_command),
            "inferenceMillis": 12,
            "nonAuthoritative": True,
        }
        if label == "UNKNOWN" and not self.unknown_as_candidate:
            payload.update(
                {
                    "observationType": "Rejected",
                    "observationRoute": None,
                    "observationConfidence": None,
                    "observationReason": (
                        "TFLite Task Text classifier top label is not a GOFFY route."
                    ),
                }
            )
        else:
            payload.update(
                {
                    "observationType": "Candidate",
                    "observationRoute": route,
                    "observationConfidence": 0.91,
                }
            )
        return payload


def write_model(tmp_path: Path) -> Path:
    model = tmp_path / "tiny-router.tflite"
    model.write_bytes(b"goffy tiny eval suite model".ljust(4096, b"\0"))
    return model


def modeldebug_build_command(root: Path) -> tuple[str, ...]:
    return (
        str(root / "android" / "gradlew"),
        "-p",
        "android",
        "-Pgoffy.testBuildType=modelDebug",
        ":app:assembleModelDebug",
        ":app:assembleModelDebugAndroidTest",
        "--no-daemon",
    )


def unsafe_corpus_payload() -> dict[str, object]:
    return {
        "schema_version": "goffy.local-intent-router-corpus.v1",
        "reviewed_at": "2026-07-22",
        "labels": ["PHONE", "MAC", "CLOUD", "UNKNOWN"],
        "policy": {
            "default_build_must_remain_model_free": True,
            "observations_must_remain_non_authoritative": True,
            "execution_authority": "observe_only",
            "allowed_splits": ["train", "eval"],
            "max_command_chars": 160,
            "min_examples_per_label": 12,
            "min_train_examples_per_label": 4,
            "min_eval_examples_per_label": 4,
        },
        "examples": [
            {
                "id": "../escape",
                "text": "show battery",
                "label": "PHONE",
                "split": "eval",
                "capability": "phone.battery.status",
                "risk_tags": ["safe"],
            }
        ],
    }
