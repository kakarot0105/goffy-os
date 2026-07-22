from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_tflite_task_text_training_environment import (  # noqa: E402
    CommandResult,
    sha256_file,
    verify_training_package,
)

JSON_SCHEMA_VERSION = "goffy.tflite-task-text-model-maker-docker.v1"
IMAGE_AUDIT_SCHEMA_VERSION = "goffy.tflite-task-text-export-image-audit.v1"
DEFAULT_IMAGE = ""
AUDITED_IMAGE_EXAMPLE = "ghcr.io/goffy/task-text-export@sha256:<audited-image-digest>"
DEFAULT_PLATFORM = "linux/amd64"
DEFAULT_EXPORT_DIR = "average_word_vec"
DEFAULT_EPOCHS = 20
DEFAULT_BATCH_SIZE = 8
DEFAULT_TIMEOUT_SECONDS = 1800
IMAGE_DIGEST = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
SAFE_EXPORT_DIR_PART = re.compile(r"^[A-Za-z0-9._-]+$")
MODEL_FILENAME = "model.tflite"
TRAINING_REPORT_FILENAME = "goffy-training-report.json"


class StepStatus(StrEnum):
    OK = "OK"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class DockerTrainingStep:
    name: str
    status: StepStatus
    command: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class DockerTrainingReport:
    schema_version: str
    executed: bool
    ok: bool
    status: str
    package_dir: str
    export_dir: str
    model_file: str | None
    model_sha256: str | None
    model_bytes: int | None
    docker_image: str
    docker_platform: str
    epochs: int
    batch_size: int
    image_audit_evidence: str | None
    steps: tuple[DockerTrainingStep, ...]
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
    package_dir: Path,
    export_dir: str = DEFAULT_EXPORT_DIR,
    execute: bool = False,
    confirm_docker_run: bool = False,
    image: str = DEFAULT_IMAGE,
    platform: str = DEFAULT_PLATFORM,
    image_audit_evidence: Path | None = None,
    epochs: int = DEFAULT_EPOCHS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    runner: CommandRunner = default_command_runner,
    root: Path = ROOT,
) -> DockerTrainingReport:
    resolved_root = root.resolve()
    resolved_package = package_dir.expanduser().resolve()
    steps: list[DockerTrainingStep] = []
    blockers: list[str] = []
    warnings: list[str] = []

    package_blockers, package_steps = verify_training_package(resolved_package)
    blockers.extend(package_blockers)
    steps.extend(
        DockerTrainingStep(
            name=step.name,
            status=StepStatus.OK if step.status.value == "OK" else StepStatus.FAIL,
            command=step.command,
            detail=step.detail,
        )
        for step in package_steps
    )

    blockers.extend(
        validate_docker_options(
            image=image,
            platform=platform,
            epochs=epochs,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
        )
    )
    export_path, export_blockers = resolve_export_path(resolved_package, export_dir)
    blockers.extend(export_blockers)
    docker = which_executable("docker")
    command: tuple[str, ...] = ()
    if docker is None:
        blockers.append("docker CLI is required for the Linux/x86_64 Model Maker export path")
    else:
        docker_step = check_docker(docker=docker, runner=runner, root=resolved_root)
        steps.append(docker_step)
        if docker_step.status is StepStatus.FAIL:
            blockers.append(docker_step.detail)
        if not blockers:
            command = docker_command(
                docker=docker,
                package_dir=resolved_package,
                export_path=export_path,
                export_dir=export_dir,
                image=image,
                platform=platform,
                epochs=epochs,
                batch_size=batch_size,
            )
            steps.append(
                DockerTrainingStep(
                    name="Prepare Docker Model Maker command",
                    status=StepStatus.OK,
                    command=command,
                    detail="digest-pinned audited image command with read-only package mount",
                )
            )

    if not execute:
        if image and image_audit_evidence is None:
            warnings.append("execution requires --image-audit-evidence for the digest-pinned image")
        return final_report(
            executed=False,
            package_dir=resolved_package,
            export_dir=export_dir,
            export_path=export_path,
            image=image,
            platform=platform,
            epochs=epochs,
            batch_size=batch_size,
            image_audit_evidence=image_audit_evidence,
            steps=steps,
            blockers=blockers,
            warnings=warnings,
            status_if_ok="PLANNED",
        )

    if not confirm_docker_run:
        blockers.append("missing explicit --confirm-docker-run")
    blockers.extend(
        verify_image_audit_evidence(
            image=image,
            evidence_path=image_audit_evidence,
        )
    )
    if blockers:
        return final_report(
            executed=False,
            package_dir=resolved_package,
            export_dir=export_dir,
            export_path=export_path,
            image=image,
            platform=platform,
            epochs=epochs,
            batch_size=batch_size,
            image_audit_evidence=image_audit_evidence,
            steps=steps,
            blockers=blockers,
            warnings=warnings,
            status_if_ok="PLANNED",
        )

    export_path.mkdir(parents=True, exist_ok=True)
    result = runner(command, resolved_root, timeout_seconds)
    steps.append(
        DockerTrainingStep(
            name="Run Docker Model Maker export",
            status=StepStatus.OK if result.exit_code == 0 else StepStatus.FAIL,
            command=command,
            detail=command_detail(result),
        )
    )
    if result.exit_code != 0:
        blockers.append(command_detail(result))

    model_blockers = verify_exported_model(export_path)
    blockers.extend(model_blockers)
    return final_report(
        executed=True,
        package_dir=resolved_package,
        export_dir=export_dir,
        export_path=export_path,
        image=image,
        platform=platform,
        epochs=epochs,
        batch_size=batch_size,
        image_audit_evidence=image_audit_evidence,
        steps=steps,
        blockers=blockers,
        warnings=warnings,
        status_if_ok="EXPORTED",
    )


def resolve_export_path(package_dir: Path, export_dir: str) -> tuple[Path, tuple[str, ...]]:
    blockers: list[str] = []
    if not export_dir or export_dir.startswith("/"):
        blockers.append("export dir must be a relative path under the training package")
        return package_dir / DEFAULT_EXPORT_DIR, tuple(blockers)
    if len(Path(export_dir).parts) != 1 or not SAFE_EXPORT_DIR_PART.fullmatch(export_dir):
        blockers.append("export dir must be one safe path segment under the training package")
        return package_dir / DEFAULT_EXPORT_DIR, tuple(blockers)
    export_path = (package_dir / export_dir).resolve(strict=False)
    try:
        export_path.relative_to(package_dir)
    except ValueError:
        blockers.append("export dir must stay under the training package")
    if export_path.exists():
        if not export_path.is_dir():
            blockers.append("export dir exists and is not a directory")
        elif any(export_path.iterdir()):
            blockers.append("export dir must be empty before Docker training")
    return export_path, tuple(blockers)


def validate_docker_options(
    *,
    image: str,
    platform: str,
    epochs: int,
    batch_size: int,
    timeout_seconds: int,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not image:
        blockers.append(
            f"audited Docker image digest is required; pass --image {AUDITED_IMAGE_EXAMPLE}"
        )
    elif not IMAGE_DIGEST.fullmatch(image):
        blockers.append("docker image must be immutable and pinned by sha256 digest")
    if platform != DEFAULT_PLATFORM:
        blockers.append(f"docker platform must stay pinned to {DEFAULT_PLATFORM}")
    if epochs <= 0:
        blockers.append("epochs must be greater than zero")
    if batch_size <= 0:
        blockers.append("batch size must be greater than zero")
    if timeout_seconds <= 0:
        blockers.append("timeout seconds must be greater than zero")
    return tuple(blockers)


def verify_image_audit_evidence(*, image: str, evidence_path: Path | None) -> tuple[str, ...]:
    if evidence_path is None:
        return ("image audit evidence is required before Docker execution",)
    try:
        payload = json.loads(evidence_path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (f"image audit evidence could not be read: {exc}",)
    blockers: list[str] = []
    if payload.get("schema_version") != IMAGE_AUDIT_SCHEMA_VERSION:
        blockers.append("image audit evidence schema mismatch")
    if payload.get("image") != image:
        blockers.append("image audit evidence does not match the requested Docker image")
    if payload.get("ok") is not True:
        blockers.append("image audit evidence must report ok=true")
    vulnerability_counts = payload.get("vulnerability_counts")
    if not isinstance(vulnerability_counts, dict):
        blockers.append("image audit evidence must include vulnerability_counts")
    else:
        for severity in ("critical", "high", "medium"):
            count = vulnerability_counts.get(severity)
            if not isinstance(count, int) or count != 0:
                blockers.append(f"image audit evidence must report zero {severity} findings")
    return tuple(blockers)


def docker_command(
    *,
    docker: str,
    package_dir: Path,
    export_path: Path,
    export_dir: str,
    image: str,
    platform: str,
    epochs: int,
    batch_size: int,
) -> tuple[str, ...]:
    host_user = f"{os.getuid()}:{os.getgid()}"
    return (
        docker,
        "run",
        "--rm",
        "--platform",
        platform,
        "--user",
        host_user,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--network",
        "none",
        "-e",
        "TF_CPP_MIN_LOG_LEVEL=1",
        "--mount",
        f"type=bind,src={package_dir},dst=/work,readonly",
        "--mount",
        f"type=bind,src={export_path},dst=/work/{export_dir}",
        "-w",
        "/work",
        image,
        "python",
        "/work/train_with_model_maker.py",
        "--dataset-dir",
        "/work",
        "--export-dir",
        export_dir,
        "--epochs",
        str(epochs),
        "--batch-size",
        str(batch_size),
    )


def check_docker(*, docker: str, runner: CommandRunner, root: Path) -> DockerTrainingStep:
    command = (docker, "info", "--format", "{{.ServerVersion}} {{.Architecture}}")
    result = runner(command, root, 30)
    return DockerTrainingStep(
        name="Check Docker daemon",
        status=StepStatus.OK if result.exit_code == 0 else StepStatus.FAIL,
        command=command,
        detail=command_detail(result),
    )


def verify_exported_model(export_path: Path) -> tuple[str, ...]:
    blockers: list[str] = []
    model = export_path / MODEL_FILENAME
    report = export_path / TRAINING_REPORT_FILENAME
    if not model.is_file():
        blockers.append("Docker training did not produce model.tflite")
        return tuple(blockers)
    if not report.is_file():
        blockers.append("Docker training did not produce goffy-training-report.json")
        return tuple(blockers)
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        blockers.append(f"training report could not be read: {exc}")
        return tuple(blockers)
    model_sha = sha256_file(model)
    model_bytes = model.stat().st_size
    if payload.get("model_sha256") != model_sha:
        blockers.append("training report model_sha256 does not match model.tflite")
    if payload.get("model_bytes") != model_bytes:
        blockers.append("training report model_bytes does not match model.tflite")
    if model_bytes <= 0 or model_bytes > 8 * 1024 * 1024:
        blockers.append("model.tflite must be between 1 byte and 8 MiB")
    return tuple(blockers)


def final_report(
    *,
    executed: bool,
    package_dir: Path,
    export_dir: str,
    export_path: Path,
    image: str,
    platform: str,
    epochs: int,
    batch_size: int,
    image_audit_evidence: Path | None,
    steps: list[DockerTrainingStep],
    blockers: list[str],
    warnings: list[str],
    status_if_ok: str,
) -> DockerTrainingReport:
    model = export_path / MODEL_FILENAME
    model_file = str(model) if model.is_file() else None
    model_sha = sha256_file(model) if model.is_file() else None
    model_bytes = model.stat().st_size if model.is_file() else None
    deduped_blockers = tuple(dict.fromkeys(blockers))
    return DockerTrainingReport(
        schema_version=JSON_SCHEMA_VERSION,
        executed=executed,
        ok=not deduped_blockers,
        status=status_if_ok if not deduped_blockers else "BLOCKED",
        package_dir=str(package_dir),
        export_dir=export_dir,
        model_file=model_file,
        model_sha256=model_sha,
        model_bytes=model_bytes,
        docker_image=image or AUDITED_IMAGE_EXAMPLE,
        docker_platform=platform,
        epochs=epochs,
        batch_size=batch_size,
        image_audit_evidence=str(image_audit_evidence) if image_audit_evidence else None,
        steps=tuple(steps),
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def which_executable(name: str) -> str | None:
    return shutil.which(name)


def command_detail(result: CommandResult, max_chars: int = 2000) -> str:
    if result.timed_out:
        return "command timed out"
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return output[-max_chars:] if output else "ok"


def render_json(report: DockerTrainingReport) -> str:
    return json.dumps(asdict(report), indent=2)


def render_text(report: DockerTrainingReport) -> str:
    lines = [
        "GOFFY TFLite Task Text Docker Model Maker export",
        f"status: {report.status}",
        f"ok: {str(report.ok).lower()}",
        f"executed: {str(report.executed).lower()}",
        f"package: {report.package_dir}",
        f"export dir: {report.export_dir}",
        f"docker: {report.docker_image} on {report.docker_platform}",
        f"training: epochs={report.epochs}, batch_size={report.batch_size}",
    ]
    if report.model_file:
        lines.append(f"model: {report.model_file}")
        lines.append(f"model sha256: {report.model_sha256}")
        lines.append(f"model bytes: {report.model_bytes}")
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


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run GOFFY's tiny Task Text Model Maker export in Docker.",
    )
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--export-dir", default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-docker-run", action="store_true")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--platform", default=DEFAULT_PLATFORM)
    parser.add_argument(
        "--image-audit-evidence",
        type=Path,
        help=(
            "JSON evidence that the digest-pinned export image was scanned and has zero "
            "critical/high/medium findings."
        ),
    )
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        package_dir=args.package_dir,
        export_dir=args.export_dir,
        execute=args.execute,
        confirm_docker_run=args.confirm_docker_run,
        image=args.image,
        platform=args.platform,
        image_audit_evidence=args.image_audit_evidence,
        epochs=args.epochs,
        batch_size=args.batch_size,
        timeout_seconds=args.timeout_seconds,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
