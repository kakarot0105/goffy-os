from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_moto_g_tflite_task_text_benchmark as benchmark  # noqa: E402
from scripts.run_moto_g_device_smoke import (  # noqa: E402
    CommandRunner,
    DeviceTarget,
    adb_command,
    default_command_runner,
    display_adb_command,
    resolve_device_target,
    trusted_adb_path,
)
from scripts.verify_local_intent_router_corpus import (  # noqa: E402
    DEFAULT_CORPUS_PATH,
    CorpusExample,
    verify_local_intent_router_corpus,
)
from scripts.verify_tflite_task_text_routing_quality import (  # noqa: E402
    EVIDENCE_SCHEMA_VERSION,
    build_routing_quality_report,
    load_corpus_examples,
    sha256_file,
)
from scripts.verify_tflite_task_text_routing_quality import (  # noqa: E402
    render_text as render_quality_text,
)

JSON_SCHEMA_VERSION = "goffy.tflite-task-text-eval-suite.v1"
DEFAULT_SPLIT = "eval"
EVAL_RESULT_FILENAME = "tflite-task-text-classifier.json"


class StepStatus(StrEnum):
    PLANNED = "PLANNED"
    OK = "OK"
    FAIL = "FAIL"


@dataclass(frozen=True)
class EvalExampleReport:
    example_id: str
    expected_label: str
    command_chars: int
    status: StepStatus
    artifact: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class EvalSuiteReport:
    schema_version: str
    executed: bool
    ok: bool
    status: str
    split: str
    example_count: int
    model_source: str | None
    evidence_manifest: str | None
    quality_status: str | None
    quality_ok: bool | None
    setup_steps: tuple[benchmark.BenchmarkStep, ...]
    examples: tuple[EvalExampleReport, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def default_output_directory(root: Path = ROOT) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return root / ".goffy-validation" / "tflite-task-text-eval-suite" / timestamp


def build_report(
    *,
    root: Path = ROOT,
    execute: bool = False,
    confirm_device_mutation: bool = False,
    model: Path | None = None,
    corpus_path: Path = DEFAULT_CORPUS_PATH,
    split: str = DEFAULT_SPLIT,
    output_directory: Path | None = None,
    device_serial: str | None = None,
    timeout_seconds: int = 180,
    runner: CommandRunner = default_command_runner,
) -> EvalSuiteReport:
    resolved_root = root.resolve()
    resolved_corpus = corpus_path.expanduser().resolve()
    resolved_model = model.expanduser().resolve() if model is not None else None
    output_root = (output_directory or default_output_directory(resolved_root)).resolve()

    blockers: list[str] = []
    warnings: list[str] = []
    corpus_report = verify_local_intent_router_corpus(resolved_corpus)
    warnings.extend(f"corpus: {warning}" for warning in corpus_report.warnings)
    if not corpus_report.ok:
        blockers.extend(f"corpus: {blocker}" for blocker in corpus_report.blockers)
        examples: dict[str, CorpusExample] = {}
    else:
        try:
            examples = load_corpus_examples(resolved_corpus, split=split)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            examples = {}
            blockers.append(f"corpus: {exc}")

    if resolved_model is None:
        blockers.append("provide --model so evidence can be bound to a local .tflite file")
    elif model_blockers := benchmark.validate_host_model(resolved_model):
        blockers.extend(model_blockers)

    if not execute:
        planned = tuple(
            EvalExampleReport(
                example_id=example.id,
                expected_label=example.label,
                command_chars=len(example.text),
                status=StepStatus.PLANNED,
                artifact=str(example_artifact_path(output_root, example.id)),
                detail="would run one bounded modelDebug Task Text benchmark",
            )
            for example in examples.values()
        )
        return EvalSuiteReport(
            schema_version=JSON_SCHEMA_VERSION,
            executed=False,
            ok=not blockers,
            status="PLANNED" if not blockers else "BLOCKED",
            split=split,
            example_count=len(examples),
            model_source=str(resolved_model) if resolved_model else None,
            evidence_manifest=str(output_root / "routing-quality-evidence.json"),
            quality_status=None,
            quality_ok=None,
            setup_steps=planned_setup_steps(
                root=resolved_root,
                host_model=resolved_model,
                device_model_path=benchmark.resolve_device_model_path(resolved_model, None),
            ),
            examples=planned,
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=tuple(warnings),
        )

    if not confirm_device_mutation:
        blockers.append("missing explicit --confirm-device-mutation")
    blockers.extend(output_directory_blockers(output_root))
    if blockers:
        return blocked_report(
            executed=False,
            split=split,
            examples=examples,
            model=resolved_model,
            evidence_manifest=output_root / "routing-quality-evidence.json",
            blockers=blockers,
        )

    output_root.mkdir(parents=True, exist_ok=True)
    if resolved_model is None:
        return blocked_report(
            executed=False,
            split=split,
            examples=examples,
            model=None,
            evidence_manifest=output_root / "routing-quality-evidence.json",
            blockers=["provide --model so evidence can be bound to a local .tflite file"],
        )
    evidence_model = copy_model_into_evidence_tree(resolved_model, output_root)
    device_model_path = benchmark.require_device_model_path(
        benchmark.resolve_device_model_path(resolved_model, None)
    )
    setup_steps, adb, target = run_suite_setup(
        root=resolved_root,
        model=resolved_model,
        device_model_path=device_model_path,
        runner=runner,
        timeout_seconds=timeout_seconds,
        device_serial=device_serial,
    )
    setup_blockers = [
        f"setup {step.name}: {step.detail}"
        for step in setup_steps
        if step.status is benchmark.StepStatus.FAIL
    ]
    if adb is None or target is None or setup_blockers:
        return EvalSuiteReport(
            schema_version=JSON_SCHEMA_VERSION,
            executed=True,
            ok=False,
            status="BLOCKED",
            split=split,
            example_count=len(examples),
            model_source=str(resolved_model),
            evidence_manifest=str(output_root / "routing-quality-evidence.json"),
            quality_status=None,
            quality_ok=None,
            setup_steps=setup_steps,
            examples=(),
            blockers=tuple(dict.fromkeys(setup_blockers)),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    example_reports: list[EvalExampleReport] = []
    for example in examples.values():
        example_output = example_output_directory(output_root, example.id)
        example_output.mkdir(parents=True, exist_ok=False)
        example_report = run_eval_example(
            root=resolved_root,
            adb=adb,
            target=target,
            device_model_path=device_model_path,
            command_text=example.text,
            example_id=example.id,
            runner=runner,
            output_directory=example_output,
            timeout_seconds=timeout_seconds,
        )
        example_reports.append(
            EvalExampleReport(
                example_id=example.id,
                expected_label=example.label,
                command_chars=len(example.text),
                status=StepStatus.OK if example_report.ok else StepStatus.FAIL,
                artifact=example_report.result_artifact,
                detail=benchmark_example_detail(example_report),
            )
        )

    manifest = write_evidence_manifest(
        output_root=output_root,
        model_file=evidence_model,
        examples=tuple(example_reports),
    )
    quality_report = build_routing_quality_report(
        corpus_path=resolved_corpus,
        evidence_manifest=manifest,
        split=split,
    )
    if not quality_report.ok:
        warnings.append(render_quality_text(quality_report))

    ok = all(example.status is StepStatus.OK for example in example_reports) and quality_report.ok
    failure_blockers = [
        f"{example.example_id}: {example.detail}"
        for example in example_reports
        if example.status is StepStatus.FAIL
    ]
    quality_blockers = [f"routing quality: {blocker}" for blocker in quality_report.blockers]
    quality_blockers.extend(
        f"routing quality: {result.example_id}: {result.reason}"
        for result in quality_report.rejected_results
    )
    return EvalSuiteReport(
        schema_version=JSON_SCHEMA_VERSION,
        executed=True,
        ok=ok,
        status="ACCEPTED" if ok else "BLOCKED",
        split=split,
        example_count=len(example_reports),
        model_source=str(resolved_model),
        evidence_manifest=str(manifest),
        quality_status=quality_report.status,
        quality_ok=quality_report.ok,
        setup_steps=setup_steps,
        examples=tuple(example_reports),
        blockers=tuple(dict.fromkeys([*failure_blockers, *quality_blockers])),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def blocked_report(
    *,
    executed: bool,
    split: str,
    examples: dict[str, CorpusExample],
    model: Path | None,
    evidence_manifest: Path,
    blockers: Sequence[str],
) -> EvalSuiteReport:
    return EvalSuiteReport(
        schema_version=JSON_SCHEMA_VERSION,
        executed=executed,
        ok=False,
        status="BLOCKED",
        split=split,
        example_count=len(examples),
        model_source=str(model) if model else None,
        evidence_manifest=str(evidence_manifest),
        quality_status=None,
        quality_ok=None,
        setup_steps=(),
        examples=(),
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=(),
    )


def output_directory_blockers(output_root: Path) -> tuple[str, ...]:
    if not output_root.exists():
        return ()
    if not output_root.is_dir():
        return ("output directory must be a directory",)
    try:
        next(output_root.iterdir())
    except StopIteration:
        return ()
    except OSError as exc:
        return (f"output directory cannot be inspected: {exc}",)
    return ("output directory must be empty before --execute to prevent stale benchmark evidence",)


def planned_setup_steps(
    *,
    root: Path,
    host_model: Path | None,
    device_model_path: str | None,
) -> tuple[benchmark.BenchmarkStep, ...]:
    model_debug_apk = root / benchmark.MODEL_DEBUG_APK_RELATIVE_PATH
    test_apk = root / benchmark.MODEL_DEBUG_TEST_APK_RELATIVE_PATH
    device_path = device_model_path or f"{benchmark.DEVICE_MODEL_DIR}/<model>.tflite"
    return (
        benchmark.BenchmarkStep(
            name="Build modelDebug classifier test APKs",
            status=benchmark.StepStatus.PLANNED,
            command=benchmark.modeldebug_build_command(root),
            detail="would compile the modelDebug app and Task Text instrumentation once",
        ),
        benchmark.BenchmarkStep(
            name="Verify Moto G target",
            status=benchmark.StepStatus.PLANNED,
            command=("adb", "devices", "-l"),
            detail="would require exactly one approved Moto G or --device-serial",
        ),
        benchmark.BenchmarkStep(
            name="Install modelDebug APK",
            status=benchmark.StepStatus.PLANNED,
            command=(
                "adb",
                "-s",
                benchmark.DEVICE_SERIAL_PLACEHOLDER,
                "install",
                "-r",
                str(model_debug_apk),
            ),
            mutates_device=True,
            detail="would install the GOFFY modelDebug APK once",
        ),
        benchmark.BenchmarkStep(
            name="Install modelDebug test APK",
            status=benchmark.StepStatus.PLANNED,
            command=(
                "adb",
                "-s",
                benchmark.DEVICE_SERIAL_PLACEHOLDER,
                "install",
                "-r",
                str(test_apk),
            ),
            mutates_device=True,
            detail="would install the modelDebug androidTest APK once",
        ),
        benchmark.BenchmarkStep(
            name="Prepare app-owned classifier model directory",
            status=benchmark.StepStatus.PLANNED,
            command=(
                "adb",
                "-s",
                benchmark.DEVICE_SERIAL_PLACEHOLDER,
                "shell",
                "mkdir",
                "-p",
                benchmark.DEVICE_MODEL_DIR,
            ),
            mutates_device=True,
            detail="would create the modelDebug app-owned external model directory once",
        ),
        benchmark.BenchmarkStep(
            name="Push TFLite classifier model",
            status=benchmark.StepStatus.PLANNED,
            command=(
                "adb",
                "-s",
                benchmark.DEVICE_SERIAL_PLACEHOLDER,
                "push",
                "<host-model>",
                device_path if host_model is not None else "<device-model-path>",
            ),
            mutates_device=True,
            detail="would push one .tflite model into app-owned storage once",
        ),
    )


def run_suite_setup(
    *,
    root: Path,
    model: Path,
    device_model_path: str,
    runner: CommandRunner,
    timeout_seconds: int,
    device_serial: str | None,
) -> tuple[tuple[benchmark.BenchmarkStep, ...], Path | None, DeviceTarget | None]:
    adb = trusted_adb_path()
    if adb is None:
        return (
            (
                benchmark.BenchmarkStep(
                    name="Resolve trusted adb",
                    status=benchmark.StepStatus.FAIL,
                    detail="trusted Android SDK adb executable is unavailable",
                ),
            ),
            None,
            None,
        )

    target, target_step = resolve_device_target(
        adb=adb,
        root=root,
        runner=runner,
        timeout_seconds=30,
        requested_serial=device_serial,
    )
    setup_steps: list[benchmark.BenchmarkStep] = [
        benchmark.BenchmarkStep(
            name=target_step.name,
            status=benchmark.StepStatus.OK if target is not None else benchmark.StepStatus.FAIL,
            command=target_step.command,
            detail=target_step.detail,
        )
    ]
    if target is None:
        return tuple(setup_steps), adb, None

    build_step = benchmark.run_step(
        name="Build modelDebug classifier test APKs",
        command=benchmark.modeldebug_build_command(root),
        display_command=benchmark.modeldebug_build_command(root),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    setup_steps.append(build_step)
    if build_step.status is benchmark.StepStatus.FAIL:
        return tuple(setup_steps), adb, target

    install_step = benchmark.run_step(
        name="Install modelDebug APK",
        command=adb_command(
            adb,
            target,
            "install",
            "-r",
            str(root / benchmark.MODEL_DEBUG_APK_RELATIVE_PATH),
        ),
        display_command=display_adb_command(adb, "install", "-r", "<modelDebug-apk>"),
        root=root,
        runner=runner,
        timeout_seconds=120,
        mutates_device=True,
    )
    setup_steps.append(install_step)
    if install_step.status is benchmark.StepStatus.FAIL:
        return tuple(setup_steps), adb, target

    test_install_step = benchmark.run_step(
        name="Install modelDebug test APK",
        command=adb_command(
            adb,
            target,
            "install",
            "-r",
            str(root / benchmark.MODEL_DEBUG_TEST_APK_RELATIVE_PATH),
        ),
        display_command=display_adb_command(
            adb,
            "install",
            "-r",
            "<modelDebug-android-test-apk>",
        ),
        root=root,
        runner=runner,
        timeout_seconds=120,
        mutates_device=True,
    )
    setup_steps.append(test_install_step)
    if test_install_step.status is benchmark.StepStatus.FAIL:
        return tuple(setup_steps), adb, target

    prepare_step = benchmark.run_step(
        name="Prepare app-owned classifier model directory",
        command=benchmark.adb_shell_command(adb, target, "mkdir", "-p", benchmark.DEVICE_MODEL_DIR),
        display_command=benchmark.display_adb_shell_command(
            adb,
            "mkdir",
            "-p",
            benchmark.DEVICE_MODEL_DIR,
        ),
        root=root,
        runner=runner,
        timeout_seconds=30,
        mutates_device=True,
    )
    setup_steps.append(prepare_step)
    if prepare_step.status is benchmark.StepStatus.FAIL:
        return tuple(setup_steps), adb, target

    push_step = benchmark.run_step(
        name="Push TFLite classifier model",
        command=adb_command(adb, target, "push", str(model), device_model_path),
        display_command=display_adb_command(adb, "push", "<host-model>", device_model_path),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
    )
    setup_steps.append(push_step)
    return tuple(setup_steps), adb, target


def run_eval_example(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    device_model_path: str,
    command_text: str,
    example_id: str,
    runner: CommandRunner,
    output_directory: Path,
    timeout_seconds: int,
) -> benchmark.BenchmarkReport:
    result_artifact = output_directory / EVAL_RESULT_FILENAME
    steps: list[benchmark.BenchmarkStep] = []
    instrument_step = benchmark.run_step(
        name="Run TFLite Task Text classifier benchmark",
        command=benchmark.adb_shell_command(
            adb,
            target,
            "am",
            "instrument",
            "-w",
            "-r",
            "-e",
            "class",
            benchmark.BENCHMARK_TEST_CLASS,
            "-e",
            "modelPath",
            device_model_path,
            "-e",
            "command",
            command_text,
            *benchmark.instrumentation_example_args(example_id),
            "-e",
            "resultPath",
            benchmark.DEVICE_RESULT_PATH,
            "-e",
            "timeoutMillis",
            str(timeout_seconds * 1000),
            benchmark.TEST_RUNNER,
        ),
        display_command=benchmark.display_adb_shell_command(
            adb,
            "am",
            "instrument",
            "-w",
            "-r",
            "-e",
            "class",
            benchmark.BENCHMARK_TEST_CLASS,
            "-e",
            "modelPath",
            device_model_path,
            "-e",
            "command",
            "<command>",
            *benchmark.instrumentation_example_args("<example-id>"),
            "-e",
            "resultPath",
            benchmark.DEVICE_RESULT_PATH,
            "-e",
            "timeoutMillis",
            str(timeout_seconds * 1000),
            benchmark.TEST_RUNNER,
        ),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
    )
    steps.append(instrument_step)
    if instrument_step.status is benchmark.StepStatus.FAIL:
        return benchmark.BenchmarkReport(
            executed=True,
            ok=False,
            model_source=None,
            device_model_path=device_model_path,
            result_artifact=None,
            command_chars=len(command_text),
            steps=tuple(steps),
        )

    pull_step = benchmark.run_step(
        name="Pull classifier benchmark JSON",
        command=adb_command(
            adb,
            target,
            "pull",
            benchmark.DEVICE_RESULT_PATH,
            str(result_artifact),
        ),
        display_command=display_adb_command(
            adb,
            "pull",
            benchmark.DEVICE_RESULT_PATH,
            "<artifact-dir>/tflite-task-text-classifier.json",
        ),
        root=root,
        runner=runner,
        timeout_seconds=60,
        artifact=str(result_artifact),
    )
    steps.append(pull_step)
    if pull_step.status is benchmark.StepStatus.OK:
        steps.append(benchmark.classifier_json_step(result_artifact))

    ok = all(step.status is benchmark.StepStatus.OK for step in steps)
    verified_artifact = (
        str(result_artifact)
        if any(
            step.name == "Verify classifier benchmark JSON"
            and step.status is benchmark.StepStatus.OK
            for step in steps
        )
        else None
    )
    return benchmark.BenchmarkReport(
        executed=True,
        ok=ok,
        model_source=None,
        device_model_path=device_model_path,
        result_artifact=verified_artifact,
        command_chars=len(command_text),
        steps=tuple(steps),
    )


def copy_model_into_evidence_tree(model: Path, output_root: Path) -> Path:
    model_dir = output_root / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    destination = model_dir / model.name
    shutil.copy2(model, destination)
    return destination


def example_output_directory(output_root: Path, example_id: str) -> Path:
    results_root = (output_root / "results").resolve(strict=False)
    candidate = (results_root / example_id).resolve(strict=False)
    try:
        candidate.relative_to(results_root)
    except ValueError as exc:
        raise ValueError("example artifact path must stay under the results directory") from exc
    return candidate


def example_artifact_path(output_root: Path, example_id: str) -> Path:
    return example_output_directory(output_root, example_id) / EVAL_RESULT_FILENAME


def write_evidence_manifest(
    *,
    output_root: Path,
    model_file: Path,
    examples: Sequence[EvalExampleReport],
) -> Path:
    manifest = output_root / "routing-quality-evidence.json"
    payload = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "model_file": str(model_file.relative_to(output_root)),
        "model_sha256": sha256_file(model_file),
        "model_bytes": model_file.stat().st_size,
        "results": [
            {
                "example_id": example.example_id,
                "artifact": str(Path(example.artifact).relative_to(output_root)),
            }
            for example in examples
            if example.artifact is not None
        ],
    }
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest


def benchmark_example_detail(report: benchmark.BenchmarkReport) -> str:
    if report.ok:
        return "benchmark artifact passed single-example validation"
    failing = next(
        (step for step in report.steps if step.status is benchmark.StepStatus.FAIL),
        None,
    )
    return failing.detail if failing is not None else "benchmark did not pass"


def render_text(report: EvalSuiteReport) -> str:
    lines = [
        "GOFFY Moto G TFLite Task Text eval suite",
        f"executed: {report.executed}",
        f"status: {report.status}",
        f"ok: {str(report.ok).lower()}",
        f"split: {report.split}",
        f"examples: {report.example_count}",
    ]
    if report.evidence_manifest:
        lines.append(f"evidence manifest: {report.evidence_manifest}")
    if report.quality_status is not None:
        lines.append(f"quality status: {report.quality_status}")
    if report.blockers:
        lines.append("blockers:")
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    if report.warnings:
        lines.append("warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    if report.setup_steps:
        lines.append("setup:")
        for step in report.setup_steps:
            lines.append(f"[{step.status}] {step.name}")
            if step.command:
                lines.append(f"       command: {' '.join(step.command)}")
            if step.detail:
                lines.append(f"       detail: {step.detail}")
    for example in report.examples:
        lines.append(
            f"[{example.status}] {example.example_id} expected={example.expected_label} "
            f"chars={example.command_chars}"
        )
        if example.artifact:
            lines.append(f"       artifact: {example.artifact}")
        if example.detail:
            lines.append(f"       detail: {example.detail}")
    return "\n".join(lines)


def render_json(report: EvalSuiteReport) -> str:
    return json.dumps(asdict(report), indent=2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the GOFFY Task Text classifier benchmark across a corpus split.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually mutate the connected phone.",
    )
    parser.add_argument(
        "--confirm-device-mutation",
        action="store_true",
        help="Required with --execute because this installs APKs and pushes a model.",
    )
    parser.add_argument("--model", type=Path, help="Host .tflite classifier model to benchmark.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--split", default=DEFAULT_SPLIT, choices=("train", "eval"))
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--device-serial", help="ADB serial when more than one device is attached.")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        execute=args.execute,
        confirm_device_mutation=args.confirm_device_mutation,
        model=args.model,
        corpus_path=args.corpus,
        split=args.split,
        output_directory=args.output_directory,
        device_serial=args.device_serial,
        timeout_seconds=args.timeout_seconds,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
