from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.create_tflite_task_text_training_package import (  # noqa: E402
    DEV_CSV,
    LABELS_TXT,
    MANIFEST,
    TRAIN_CSV,
    TRAINING_SCRIPT,
)
from scripts.create_tflite_task_text_training_package import (  # noqa: E402
    JSON_SCHEMA_VERSION as TRAINING_PACKAGE_SCHEMA_VERSION,
)

JSON_SCHEMA_VERSION = "goffy.tflite-task-text-training-environment.v1"
MODEL_MAKER_REQUIREMENT = "tflite-model-maker==0.4.3"
SUPPORTED_PYTHON_MINORS = frozenset({9, 10})
DEFAULT_TIMEOUT_SECONDS = 180
REQUIRED_PACKAGE_FILES = frozenset({TRAIN_CSV, DEV_CSV, LABELS_TXT, TRAINING_SCRIPT})
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class StepStatus(StrEnum):
    OK = "OK"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass(frozen=True)
class PreflightStep:
    name: str
    status: StepStatus
    command: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class TrainingEnvironmentReport:
    schema_version: str
    ok: bool
    status: str
    package_dir: str | None
    python_executable: str | None
    python_version: str | None
    pip_resolve_checked: bool
    docker_available: bool | None
    steps: tuple[PreflightStep, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


CommandRunner = Callable[[Sequence[str], Path, int], CommandResult]


def default_command_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> CommandResult:
    try:
        completed = subprocess.run(  # noqa: S603
            list(command),
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(124, stdout, stderr, timed_out=True)
    except OSError as exc:
        return CommandResult(127, "", f"{exc.__class__.__name__}: {exc}")
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def build_report(
    *,
    package_dir: Path | None = None,
    python_executable: Path | None = None,
    check_pip_resolve: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    runner: CommandRunner = default_command_runner,
    root: Path = ROOT,
) -> TrainingEnvironmentReport:
    resolved_root = root.resolve()
    steps: list[PreflightStep] = []
    blockers: list[str] = []
    warnings: list[str] = []

    resolved_package = package_dir.expanduser().resolve() if package_dir is not None else None
    if resolved_package is None:
        detail = (
            "training package directory is required; pass --package-dir from the generated "
            "Task Text training package"
        )
        blockers.append(detail)
        steps.append(PreflightStep("Verify training package", StepStatus.FAIL, detail=detail))
    else:
        package_blockers, package_steps = verify_training_package(resolved_package)
        blockers.extend(package_blockers)
        steps.extend(package_steps)

    python_path = resolve_python_executable(python_executable)
    python_version: str | None = None
    python_supported = False
    if python_path is None:
        blockers.append("Python 3.9 or 3.10 executable is required for the pinned Model Maker path")
        steps.append(
            PreflightStep(
                name="Resolve training Python",
                status=StepStatus.FAIL,
                detail="searched explicit --python, python3.10, then python3.9",
            )
        )
    else:
        python_step, python_version = check_python_version(
            python=python_path,
            runner=runner,
            root=resolved_root,
            timeout_seconds=30,
        )
        steps.append(python_step)
        if python_step.status is StepStatus.FAIL:
            blockers.append(python_step.detail)
        else:
            python_supported = True

    pip_resolve_checked = False
    if check_pip_resolve:
        if python_path is None or not python_supported:
            steps.append(
                PreflightStep(
                    name="Resolve Model Maker requirement",
                    status=StepStatus.SKIP,
                    detail="skipped because supported training Python is unavailable",
                )
            )
        else:
            pip_step = check_model_maker_resolution(
                python=python_path,
                runner=runner,
                root=resolved_root,
                timeout_seconds=timeout_seconds,
            )
            pip_resolve_checked = True
            steps.append(pip_step)
            if pip_step.status is StepStatus.FAIL:
                blockers.append(pip_step.detail)
    else:
        warnings.append(
            "pip dry-run was not executed; pass --check-pip-resolve for compatibility proof"
        )
        steps.append(
            PreflightStep(
                name="Resolve Model Maker requirement",
                status=StepStatus.SKIP,
                detail="pip dry-run compatibility check not requested",
            )
        )

    docker_step = check_docker(runner=runner, root=resolved_root)
    steps.append(docker_step)
    docker_available = docker_step.status is StepStatus.OK
    if not docker_available:
        warnings.append(
            "Docker fallback is unavailable; local training depends on a supported Python env"
        )

    deduped_blockers = tuple(dict.fromkeys(blockers))
    return TrainingEnvironmentReport(
        schema_version=JSON_SCHEMA_VERSION,
        ok=not deduped_blockers,
        status="READY" if not deduped_blockers else "BLOCKED",
        package_dir=str(resolved_package) if resolved_package else None,
        python_executable=str(python_path) if python_path else None,
        python_version=python_version,
        pip_resolve_checked=pip_resolve_checked,
        docker_available=docker_available,
        steps=tuple(steps),
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def verify_training_package(package_dir: Path) -> tuple[tuple[str, ...], tuple[PreflightStep, ...]]:
    blockers: list[str] = []
    steps: list[PreflightStep] = []
    if not package_dir.is_dir():
        detail = "training package directory is missing"
        return (
            (detail,),
            (PreflightStep("Verify training package", StepStatus.FAIL, detail=detail),),
        )

    manifest = package_dir / MANIFEST
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        detail = f"training package manifest could not be read: {exc}"
        return (
            (detail,),
            (PreflightStep("Verify training package", StepStatus.FAIL, detail=detail),),
        )

    if payload.get("schema_version") != TRAINING_PACKAGE_SCHEMA_VERSION:
        blockers.append("training package manifest schema mismatch")

    files = payload.get("files")
    if not isinstance(files, list):
        blockers.append("training package manifest files must be a list")
        files = []

    seen_paths: set[str] = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            blockers.append(f"files[{index}] must be an object")
            continue
        relative_path = item.get("path")
        expected_sha = item.get("sha256")
        expected_bytes = item.get("bytes")
        if not isinstance(relative_path, str) or not relative_path:
            blockers.append(f"files[{index}].path is required")
            continue
        seen_paths.add(relative_path)
        if not isinstance(expected_sha, str) or SHA256.fullmatch(expected_sha) is None:
            blockers.append(f"{relative_path}: sha256 is missing or invalid")
            continue
        path = resolve_package_file(package_dir, relative_path)
        if path is None:
            blockers.append(f"{relative_path}: package file must stay under package dir")
            continue
        if not path.is_file():
            blockers.append(f"{relative_path}: package file is missing")
            continue
        try:
            actual_bytes = path.stat().st_size
            actual_sha = sha256_file(path)
        except OSError as exc:
            blockers.append(f"{relative_path}: package file could not be read: {exc}")
            continue
        if not isinstance(expected_bytes, int) or actual_bytes != expected_bytes:
            blockers.append(f"{relative_path}: byte count does not match manifest")
        if actual_sha != expected_sha:
            blockers.append(f"{relative_path}: sha256 does not match manifest")

    missing = sorted(REQUIRED_PACKAGE_FILES - seen_paths)
    if missing:
        blockers.append(f"training package is missing required files: {missing}")

    status = StepStatus.OK if not blockers else StepStatus.FAIL
    detail = "training package manifest and file hashes are valid" if not blockers else blockers[0]
    steps.append(PreflightStep("Verify training package", status, detail=detail))
    return tuple(dict.fromkeys(blockers)), tuple(steps)


def resolve_package_file(package_dir: Path, relative_path: str) -> Path | None:
    candidate = (package_dir / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(package_dir)
    except ValueError:
        return None
    return candidate


def resolve_python_executable(python_executable: Path | None) -> Path | None:
    if python_executable is not None:
        return python_executable.expanduser().resolve()
    for name in ("python3.10", "python3.9"):
        found = which_executable(name)
        if found:
            return Path(found).resolve()
    return None


def check_python_version(
    *,
    python: Path,
    runner: CommandRunner,
    root: Path,
    timeout_seconds: int,
) -> tuple[PreflightStep, str | None]:
    command = (str(python), "--version")
    result = runner(command, root, timeout_seconds)
    output = " ".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.exit_code != 0:
        return (
            PreflightStep(
                name="Verify training Python",
                status=StepStatus.FAIL,
                command=command,
                detail=output or "python --version failed",
            ),
            None,
        )
    version = parse_python_version(output)
    if version is None:
        return (
            PreflightStep(
                name="Verify training Python",
                status=StepStatus.FAIL,
                command=command,
                detail=f"could not parse Python version from {output!r}",
            ),
            None,
        )
    major, minor, patch = version
    rendered = f"{major}.{minor}.{patch}"
    if major != 3 or minor not in SUPPORTED_PYTHON_MINORS:
        return (
            PreflightStep(
                name="Verify training Python",
                status=StepStatus.FAIL,
                command=command,
                detail=(
                    f"Model Maker training requires Python 3.9 or 3.10; found Python {rendered}"
                ),
            ),
            rendered,
        )
    return (
        PreflightStep(
            name="Verify training Python",
            status=StepStatus.OK,
            command=command,
            detail=f"Python {rendered} is within the pinned Model Maker training range",
        ),
        rendered,
    )


def parse_python_version(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"Python\s+(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def check_model_maker_resolution(
    *,
    python: Path,
    runner: CommandRunner,
    root: Path,
    timeout_seconds: int,
) -> PreflightStep:
    with tempfile.TemporaryDirectory(prefix="goffy-model-maker-resolve-") as temp_dir:
        venv = Path(temp_dir) / "venv"
        venv_command = (str(python), "-m", "venv", str(venv))
        venv_result = runner(venv_command, root, timeout_seconds)
        if venv_result.exit_code != 0:
            return PreflightStep(
                name="Create isolated training resolver venv",
                status=StepStatus.FAIL,
                command=venv_command,
                detail=command_detail(venv_result),
            )
        pip = venv / "bin" / "python"
        pip_command = (
            str(pip),
            "-m",
            "pip",
            "install",
            "--dry-run",
            "--only-binary=:all:",
            MODEL_MAKER_REQUIREMENT,
        )
        pip_result = runner(pip_command, root, timeout_seconds)
        return PreflightStep(
            name="Resolve Model Maker requirement",
            status=StepStatus.OK if pip_result.exit_code == 0 else StepStatus.FAIL,
            command=pip_command,
            detail=command_detail(pip_result),
        )


def check_docker(*, runner: CommandRunner, root: Path) -> PreflightStep:
    docker = which_executable("docker")
    if docker is None:
        return PreflightStep(
            name="Check Docker fallback",
            status=StepStatus.FAIL,
            detail="docker CLI is unavailable",
        )
    command = (docker, "info", "--format", "{{.ServerVersion}} {{.Architecture}}")
    result = runner(command, root, 30)
    return PreflightStep(
        name="Check Docker fallback",
        status=StepStatus.OK if result.exit_code == 0 else StepStatus.FAIL,
        command=command,
        detail=command_detail(result),
    )


def which_executable(name: str) -> str | None:
    return shutil.which(name)


def command_detail(result: CommandResult, max_chars: int = 1000) -> str:
    if result.timed_out:
        return "command timed out"
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return output[-max_chars:] if output else "ok"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def render_text(report: TrainingEnvironmentReport) -> str:
    lines = [
        "GOFFY TFLite Task Text training environment",
        f"status: {report.status}",
        f"ok: {str(report.ok).lower()}",
    ]
    if report.package_dir:
        lines.append(f"package: {report.package_dir}")
    if report.python_executable:
        lines.append(f"python: {report.python_executable}")
    if report.python_version:
        lines.append(f"python version: {report.python_version}")
    lines.append(f"pip resolve checked: {str(report.pip_resolve_checked).lower()}")
    lines.append(f"docker available: {report.docker_available}")
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    for step in report.steps:
        lines.append(f"[{step.status}] {step.name}")
        if step.command:
            lines.append(f"       command: {' '.join(step.command)}")
        if step.detail:
            lines.append(f"       detail: {step.detail}")
    return "\n".join(lines)


def render_json(report: TrainingEnvironmentReport) -> str:
    return json.dumps(asdict(report), indent=2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify readiness to train GOFFY's tiny Task Text router.",
    )
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--python", type=Path, dest="python_executable")
    parser.add_argument("--check-pip-resolve", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        package_dir=args.package_dir,
        python_executable=args.python_executable,
        check_pip_resolve=args.check_pip_resolve,
        timeout_seconds=args.timeout_seconds,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
