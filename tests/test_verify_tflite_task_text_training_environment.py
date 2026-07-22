from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
import scripts.create_tflite_task_text_training_package as package
import scripts.verify_tflite_task_text_training_environment as preflight


def test_preflight_accepts_valid_package_and_supported_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)
    monkeypatch.setattr(preflight, "which_executable", fake_which)
    runner = FakeRunner()

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=Path("/opt/python3.10"),
        runner=runner,
    )

    assert report.ok
    assert report.status == "READY"
    assert report.python_version == "3.10.14"
    assert report.pip_resolve_checked is False
    assert report.docker_available is True
    assert any(step.name == "Verify training package" for step in report.steps)
    assert any("pip dry-run was not executed" in warning for warning in report.warnings)


def test_preflight_blocks_missing_package_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "which_executable", fake_which)

    report = preflight.build_report(
        package_dir=None,
        python_executable=Path("/opt/python3.10"),
        runner=FakeRunner(),
    )

    assert not report.ok
    assert report.status == "BLOCKED"
    assert any("training package directory is required" in blocker for blocker in report.blockers)


def test_preflight_blocks_tampered_package(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)
    monkeypatch.setattr(preflight, "which_executable", fake_which)
    with (package_dir / package.TRAIN_CSV).open("a", encoding="utf-8") as handle:
        handle.write("tampered,PHONE\n")

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=Path("/opt/python3.10"),
        runner=FakeRunner(),
    )

    assert not report.ok
    assert report.status == "BLOCKED"
    assert f"{package.TRAIN_CSV}: sha256 does not match manifest" in report.blockers


def test_preflight_blocks_unreadable_package_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)
    monkeypatch.setattr(preflight, "which_executable", fake_which)
    original_sha256 = preflight.sha256_file

    def unreadable_sha256(path: Path) -> str:
        if path.name == package.TRAIN_CSV:
            raise OSError("permission denied")
        return original_sha256(path)

    monkeypatch.setattr(preflight, "sha256_file", unreadable_sha256)

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=Path("/opt/python3.10"),
        runner=FakeRunner(),
    )

    assert not report.ok
    assert any(
        f"{package.TRAIN_CSV}: package file could not be read" in blocker
        for blocker in report.blockers
    )


def test_preflight_blocks_unsupported_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)
    monkeypatch.setattr(preflight, "which_executable", fake_which)

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=Path("/opt/python3.11"),
        runner=FakeRunner(python_version="Python 3.11.15"),
    )

    assert not report.ok
    assert report.python_version == "3.11.15"
    assert any("requires Python 3.9 or 3.10" in blocker for blocker in report.blockers)


def test_preflight_reports_pip_dry_run_unchecked_when_python_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)
    monkeypatch.setattr(preflight, "which_executable", fake_which)

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=Path("/opt/python3.11"),
        check_pip_resolve=True,
        runner=FakeRunner(python_version="Python 3.11.15"),
    )

    assert not report.ok
    assert report.pip_resolve_checked is False
    assert any(
        step.name == "Resolve Model Maker requirement" and step.status is preflight.StepStatus.SKIP
        for step in report.steps
    )


def test_preflight_reports_missing_explicit_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)

    def which(name: str) -> str | None:
        return None if name == "docker" else f"/opt/{name}"

    monkeypatch.setattr(preflight, "which_executable", which)

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=tmp_path / "missing-python3.10",
    )

    assert not report.ok
    assert any("FileNotFoundError" in blocker for blocker in report.blockers)


def test_preflight_can_run_optional_pip_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)
    monkeypatch.setattr(preflight, "which_executable", fake_which)
    runner = FakeRunner()

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=Path("/opt/python3.10"),
        check_pip_resolve=True,
        runner=runner,
    )

    assert report.ok
    assert report.pip_resolve_checked is True
    assert any(
        command[-2:] == ("--only-binary=:all:", preflight.MODEL_MAKER_REQUIREMENT)
        for command in runner.commands
    )


def test_preflight_reports_pip_resolution_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)
    monkeypatch.setattr(preflight, "which_executable", fake_which)

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=Path("/opt/python3.10"),
        check_pip_resolve=True,
        runner=FakeRunner(pip_resolves=False),
    )

    assert not report.ok
    assert any("No matching distribution" in blocker for blocker in report.blockers)


def test_preflight_warns_when_docker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    package_dir = create_package(tmp_path)

    def which(name: str) -> str | None:
        return None if name == "docker" else f"/opt/{name}"

    monkeypatch.setattr(preflight, "which_executable", which)

    report = preflight.build_report(
        package_dir=package_dir,
        python_executable=Path("/opt/python3.10"),
        runner=FakeRunner(),
    )

    assert report.ok
    assert report.docker_available is False
    assert any("Docker fallback is unavailable" in warning for warning in report.warnings)


class FakeRunner:
    def __init__(
        self,
        *,
        python_version: str = "Python 3.10.14",
        pip_resolves: bool = True,
    ) -> None:
        self.python_version = python_version
        self.pip_resolves = pip_resolves
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: int,
    ) -> preflight.CommandResult:
        normalized = tuple(str(part) for part in command)
        self.commands.append(normalized)
        if normalized[-1] == "--version":
            return preflight.CommandResult(0, f"{self.python_version}\n", "")
        if len(normalized) >= 4 and normalized[-3:-1] == ("-m", "venv"):
            return preflight.CommandResult(0, "", "")
        if "pip" in normalized and "install" in normalized:
            if self.pip_resolves:
                return preflight.CommandResult(0, "Would install tflite-model-maker-0.4.3\n", "")
            return preflight.CommandResult(
                1,
                "",
                "ERROR: No matching distribution found for tflite-support>=0.4.2\n",
            )
        if normalized[:2] == ("/opt/docker", "info"):
            return preflight.CommandResult(0, "29.3.0 aarch64\n", "")
        return preflight.CommandResult(1, "", f"unexpected command: {normalized}")


def create_package(tmp_path: Path) -> Path:
    output = tmp_path / "training-package"
    report = package.build_report(output_directory=output)
    assert report.ok
    manifest = json.loads((output / package.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == package.JSON_SCHEMA_VERSION
    return output


def fake_which(name: str) -> str | None:
    if name in {"python3.10", "python3.9", "docker"}:
        return f"/opt/{name}"
    return None
