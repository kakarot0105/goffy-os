from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.create_tflite_task_text_training_package as package
import scripts.run_tflite_task_text_model_maker_docker as docker_runner
from scripts.verify_tflite_task_text_training_environment import CommandResult, sha256_file

AUDITED_IMAGE = (
    "ghcr.io/goffy/task-text-export@sha256:"
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)


def test_plan_prepares_fixed_docker_model_maker_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)

    report = docker_runner.build_report(
        package_dir=package_dir,
        export_dir="planned_export",
        image=AUDITED_IMAGE,
        runner=fake_successful_runner,
        root=tmp_path,
    )

    assert report.ok
    assert report.status == "PLANNED"
    assert not report.executed
    command = prepared_command(report)
    assert command[:5] == ("/opt/docker", "run", "--rm", "--platform", "linux/amd64")
    assert "--network" in command
    assert "none" in command
    assert "--cap-drop" in command
    assert "ALL" in command
    assert "--security-opt" in command
    assert "no-new-privileges" in command
    assert AUDITED_IMAGE in command
    assert "bash" not in command
    assert "apt-get" not in command
    assert "pip" not in command
    assert f"type=bind,src={package_dir.resolve()},dst=/work,readonly" in command
    assert (
        f"type=bind,src={(package_dir / 'planned_export').resolve()},dst=/work/planned_export"
        in command
    )
    assert report.epochs == 20
    assert report.batch_size == 8
    assert command[-6:] == ("--export-dir", "planned_export", "--epochs", "20", "--batch-size", "8")


def test_execute_requires_explicit_docker_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)

    report = docker_runner.build_report(
        package_dir=package_dir,
        export_dir="docker_export",
        execute=True,
        image=AUDITED_IMAGE,
        image_audit_evidence=write_audit_evidence(tmp_path, AUDITED_IMAGE),
        runner=fake_successful_runner,
        root=tmp_path,
    )

    assert not report.ok
    assert not report.executed
    assert "missing explicit --confirm-docker-run" in report.blockers


def test_json_report_shape_includes_additive_training_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)

    report = docker_runner.build_report(
        package_dir=package_dir,
        image=AUDITED_IMAGE,
        runner=fake_successful_runner,
        root=tmp_path,
    )
    payload = json.loads(docker_runner.render_json(report))

    assert payload["schema_version"] == docker_runner.JSON_SCHEMA_VERSION
    assert payload["epochs"] == 20
    assert payload["batch_size"] == 8
    assert payload["docker_image"] == AUDITED_IMAGE


def test_plan_blocks_when_docker_daemon_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)

    report = docker_runner.build_report(
        package_dir=package_dir,
        image=AUDITED_IMAGE,
        runner=lambda command, cwd, timeout_seconds: CommandResult(1, "", "Cannot connect"),
        root=tmp_path,
    )

    assert not report.ok
    assert "Cannot connect" in report.blockers


def test_rejects_non_empty_export_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    export_dir = package_dir / "average_word_vec"
    export_dir.mkdir()
    (export_dir / "model.tflite").write_bytes(b"stale model")
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)

    report = docker_runner.build_report(
        package_dir=package_dir,
        image=AUDITED_IMAGE,
        runner=fake_successful_runner,
        root=tmp_path,
    )

    assert not report.ok
    assert "export dir must be empty before Docker training" in report.blockers


def test_rejects_unpinned_or_unsafe_docker_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)

    report = docker_runner.build_report(
        package_dir=package_dir,
        export_dir="../escape",
        image="python:latest",
        platform="linux/arm64",
        epochs=0,
        batch_size=0,
        timeout_seconds=0,
        runner=fake_successful_runner,
        root=tmp_path,
    )

    assert not report.ok
    assert "docker image must be immutable and pinned by sha256 digest" in report.blockers
    assert "docker platform must stay pinned to linux/amd64" in report.blockers
    assert "epochs must be greater than zero" in report.blockers
    assert "batch size must be greater than zero" in report.blockers
    assert "timeout seconds must be greater than zero" in report.blockers
    assert any("export dir must be one safe path segment" in blocker for blocker in report.blockers)
    assert not has_prepared_command(report)


def test_execute_requires_matching_clean_image_audit_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)
    audit = write_audit_evidence(
        tmp_path,
        "ghcr.io/goffy/task-text-export@sha256:"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )

    report = docker_runner.build_report(
        package_dir=package_dir,
        execute=True,
        confirm_docker_run=True,
        image=AUDITED_IMAGE,
        image_audit_evidence=audit,
        runner=fake_successful_runner,
        root=tmp_path,
    )

    assert not report.ok
    assert "image audit evidence does not match the requested Docker image" in report.blockers


def test_execute_verifies_exported_model_and_training_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)

    def fake_runner(command: Sequence[str], cwd: Path, timeout_seconds: int) -> CommandResult:
        assert cwd == tmp_path.resolve()
        assert command[0] == "/opt/docker"
        if command[1] == "info":
            assert timeout_seconds == 30
            return CommandResult(0, "29.2.1 x86_64\n", "")
        assert timeout_seconds == docker_runner.DEFAULT_TIMEOUT_SECONDS
        export_dir = package_dir / "average_word_vec"
        export_dir.mkdir(exist_ok=True)
        model = export_dir / docker_runner.MODEL_FILENAME
        model.write_bytes(b"goffy fake task text model")
        training_report = {
            "schema_version": "goffy.tflite-task-text-model-maker-training.v1",
            "model_sha256": sha256_file(model),
            "model_bytes": model.stat().st_size,
        }
        (export_dir / docker_runner.TRAINING_REPORT_FILENAME).write_text(
            json.dumps(training_report) + "\n",
            encoding="utf-8",
        )
        return CommandResult(0, "trained\n", "")

    report = docker_runner.build_report(
        package_dir=package_dir,
        execute=True,
        confirm_docker_run=True,
        image=AUDITED_IMAGE,
        image_audit_evidence=write_audit_evidence(tmp_path, AUDITED_IMAGE),
        runner=fake_runner,
        root=tmp_path,
    )

    assert report.ok
    assert report.status == "EXPORTED"
    assert report.executed
    assert report.model_file == str(package_dir / "average_word_vec" / docker_runner.MODEL_FILENAME)
    assert report.model_sha256 == sha256_file(Path(report.model_file))
    assert report.model_bytes == len(b"goffy fake task text model")


def test_execute_blocks_when_docker_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_training_package(tmp_path)
    monkeypatch.setattr(docker_runner, "which_executable", fake_which_executable)

    report = docker_runner.build_report(
        package_dir=package_dir,
        export_dir="failed_export",
        execute=True,
        confirm_docker_run=True,
        image=AUDITED_IMAGE,
        image_audit_evidence=write_audit_evidence(tmp_path, AUDITED_IMAGE),
        runner=fake_failed_training_runner,
        root=tmp_path,
    )

    assert not report.ok
    assert report.status == "BLOCKED"
    assert "dependency resolution failed" in report.blockers
    assert "Docker training did not produce model.tflite" in report.blockers


def test_verify_exported_model_rejects_malformed_training_report(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / docker_runner.MODEL_FILENAME).write_bytes(b"model")
    (export_dir / docker_runner.TRAINING_REPORT_FILENAME).write_text("{bad json", encoding="utf-8")

    blockers = docker_runner.verify_exported_model(export_dir)

    assert any("training report could not be read" in blocker for blocker in blockers)


def test_verify_exported_model_rejects_report_hash_and_size_mismatch(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / docker_runner.MODEL_FILENAME).write_bytes(b"model")
    (export_dir / docker_runner.TRAINING_REPORT_FILENAME).write_text(
        json.dumps({"model_sha256": "0" * 64, "model_bytes": 999}) + "\n",
        encoding="utf-8",
    )

    blockers = docker_runner.verify_exported_model(export_dir)

    assert "training report model_sha256 does not match model.tflite" in blockers
    assert "training report model_bytes does not match model.tflite" in blockers


def create_training_package(tmp_path: Path) -> Path:
    package_dir = tmp_path / "training-package"
    report = package.build_report(output_directory=package_dir)
    assert report.ok
    return package_dir


def fake_which_executable(name: str) -> str | None:
    return "/opt/docker" if name == "docker" else None


def fake_successful_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
    if command[1] == "info":
        return CommandResult(0, "29.2.1 x86_64\n", "")
    return CommandResult(0, "ok\n", "")


def fake_failed_training_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
    if command[1] == "info":
        return CommandResult(0, "29.2.1 x86_64\n", "")
    return CommandResult(1, "", "dependency resolution failed")


def write_audit_evidence(tmp_path: Path, image: str) -> Path:
    path = tmp_path / "image-audit.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": docker_runner.IMAGE_AUDIT_SCHEMA_VERSION,
                "image": image,
                "ok": True,
                "vulnerability_counts": {
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 4,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def prepared_command(report: docker_runner.DockerTrainingReport) -> tuple[str, ...]:
    for step in report.steps:
        if step.name == "Prepare Docker Model Maker command":
            return step.command
    raise AssertionError("prepared Docker command step missing")


def has_prepared_command(report: docker_runner.DockerTrainingReport) -> bool:
    return any(step.name == "Prepare Docker Model Maker command" for step in report.steps)
