from __future__ import annotations

import argparse
import json
import posixpath
import re
import shlex
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_moto_g_device_smoke import (  # noqa: E402
    CommandRunner,
    DeviceTarget,
    adb_command,
    default_command_runner,
    display_adb_command,
    resolve_device_target,
    trusted_adb_path,
)
from scripts.verify_moto_g_readiness import DEBUG_APK_RELATIVE_PATH  # noqa: E402

DEBUG_TEST_APK_RELATIVE_PATH = Path(
    "android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk",
)
PACKAGE_NAME = "dev.goffy.os"
TEST_RUNNER = f"{PACKAGE_NAME}.test/androidx.test.runner.AndroidJUnitRunner"
BENCHMARK_TEST_CLASS = (
    "dev.goffy.os.localmodel.LiteRtLmMotoBenchmarkInstrumentedTest#benchmarkOnePromptOnCpu"
)
ADAPTER_SMOKE_TEST_CLASS = (
    "dev.goffy.os.localmodel.LiteRtLmRoutingAdapterInstrumentedTest"
    "#smokeRealLiteRtLmThroughAdapterGate"
)
DEVICE_MODEL_DIR = "/sdcard/Android/data/dev.goffy.os/files/models"
DEVICE_BENCHMARK_RESULT_PATH = (
    "/sdcard/Android/data/dev.goffy.os/files/benchmarks/litertlm-benchmark.json"
)
DEVICE_ADAPTER_SMOKE_RESULT_PATH = (
    "/sdcard/Android/data/dev.goffy.os/files/benchmarks/litertlm-adapter-smoke.json"
)
DEVICE_RESULT_PATH = DEVICE_BENCHMARK_RESULT_PATH
DEFAULT_PROMPT = "Classify this GOFFY command: show my battery status"
MAX_MODEL_BYTES = 512 * 1024 * 1024
MAX_PROMPT_CHARS = 512
SAFE_MODEL_BASENAME = re.compile(r"^[A-Za-z0-9._-]+\.litertlm$")
ALLOWED_DEVICE_MODEL_PREFIXES = (
    "/sdcard/Android/data/dev.goffy.os/files/models/",
    "/storage/emulated/0/Android/data/dev.goffy.os/files/models/",
)
DEVICE_SERIAL_PLACEHOLDER = "<device-serial>"


class StepStatus(StrEnum):
    PLANNED = "PLANNED"
    OK = "OK"
    FAIL = "FAIL"
    SKIP = "SKIP"


class InstrumentationMode(StrEnum):
    BENCHMARK = "benchmark"
    ADAPTER_SMOKE = "adapter-smoke"


@dataclass(frozen=True)
class InstrumentationSpec:
    mode: InstrumentationMode
    test_class: str
    device_result_path: str
    artifact_name: str
    run_step_name: str
    planned_detail: str


INSTRUMENTATION_SPECS = {
    InstrumentationMode.BENCHMARK: InstrumentationSpec(
        mode=InstrumentationMode.BENCHMARK,
        test_class=BENCHMARK_TEST_CLASS,
        device_result_path=DEVICE_BENCHMARK_RESULT_PATH,
        artifact_name="litertlm-benchmark.json",
        run_step_name="Run LiteRT-LM benchmark",
        planned_detail="would run one CPU LiteRT-LM prompt and write JSON metrics",
    ),
    InstrumentationMode.ADAPTER_SMOKE: InstrumentationSpec(
        mode=InstrumentationMode.ADAPTER_SMOKE,
        test_class=ADAPTER_SMOKE_TEST_CLASS,
        device_result_path=DEVICE_ADAPTER_SMOKE_RESULT_PATH,
        artifact_name="litertlm-adapter-smoke.json",
        run_step_name="Run LiteRT-LM adapter smoke",
        planned_detail="would run LiteRT-LM through the generated-text adapter quality gate",
    ),
}


@dataclass(frozen=True)
class BenchmarkStep:
    name: str
    status: StepStatus
    command: tuple[str, ...] = ()
    mutates_device: bool = False
    detail: str = ""
    artifact: str | None = None


@dataclass(frozen=True)
class BenchmarkReport:
    executed: bool
    ok: bool
    instrumentation_mode: str
    model_source: str | None
    device_model_path: str | None
    result_artifact: str | None
    prompt_chars: int
    steps: tuple[BenchmarkStep, ...]


def default_output_directory(root: Path = ROOT) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / ".goffy-validation" / "litertlm-benchmark" / timestamp


def planned_steps(
    *,
    root: Path,
    host_model: Path | None,
    device_model_path: str | None,
    instrumentation_mode: InstrumentationMode = InstrumentationMode.BENCHMARK,
) -> tuple[BenchmarkStep, ...]:
    spec = INSTRUMENTATION_SPECS[instrumentation_mode]
    apk = root / DEBUG_APK_RELATIVE_PATH
    test_apk = root / DEBUG_TEST_APK_RELATIVE_PATH
    device_path = device_model_path or f"{DEVICE_MODEL_DIR}/<model>.litertlm"
    steps = [
        BenchmarkStep(
            name="Build benchmark test APK",
            status=StepStatus.PLANNED,
            command=(
                str(root / "android" / "gradlew"),
                "-p",
                "android",
                ":app:assembleDebug",
                ":app:assembleDebugAndroidTest",
                "--no-daemon",
            ),
            detail="would compile the GOFFY debug app and LiteRT-LM androidTest harness",
        ),
        BenchmarkStep(
            name="Verify Moto G target",
            status=StepStatus.PLANNED,
            command=("adb", "devices", "-l"),
            detail="would require exactly one approved Moto G or --device-serial",
        ),
        BenchmarkStep(
            name="Install debug APK",
            status=StepStatus.PLANNED,
            command=("adb", "-s", DEVICE_SERIAL_PLACEHOLDER, "install", "-r", str(apk)),
            mutates_device=True,
            detail="would install the GOFFY debug APK",
        ),
        BenchmarkStep(
            name="Install benchmark test APK",
            status=StepStatus.PLANNED,
            command=("adb", "-s", DEVICE_SERIAL_PLACEHOLDER, "install", "-r", str(test_apk)),
            mutates_device=True,
            detail="would install the androidTest APK containing the benchmark runner",
        ),
    ]
    if host_model is not None:
        steps.extend(
            [
                BenchmarkStep(
                    name="Prepare app-owned model directory",
                    status=StepStatus.PLANNED,
                    command=(
                        "adb",
                        "-s",
                        DEVICE_SERIAL_PLACEHOLDER,
                        "shell",
                        "mkdir",
                        "-p",
                        DEVICE_MODEL_DIR,
                    ),
                    mutates_device=True,
                    detail="would create the app-owned external model directory",
                ),
                BenchmarkStep(
                    name="Push local model",
                    status=StepStatus.PLANNED,
                    command=(
                        "adb",
                        "-s",
                        DEVICE_SERIAL_PLACEHOLDER,
                        "push",
                        "<host-model>",
                        device_path,
                    ),
                    mutates_device=True,
                    detail="would push one .litertlm model into the app-owned model directory",
                ),
            ]
        )
    steps.extend(
        [
            BenchmarkStep(
                name=spec.run_step_name,
                status=StepStatus.PLANNED,
                command=(
                    "adb",
                    "-s",
                    DEVICE_SERIAL_PLACEHOLDER,
                    "shell",
                    "am",
                    "instrument",
                    "-w",
                    "-r",
                    "-e",
                    "class",
                    spec.test_class,
                    "-e",
                    "modelPath",
                    device_path,
                    "-e",
                    "resultPath",
                    spec.device_result_path,
                    TEST_RUNNER,
                ),
                mutates_device=True,
                detail=spec.planned_detail,
            ),
            BenchmarkStep(
                name="Pull benchmark JSON",
                status=StepStatus.PLANNED,
                command=(
                    "adb",
                    "-s",
                    DEVICE_SERIAL_PLACEHOLDER,
                    "pull",
                    spec.device_result_path,
                    f"<artifact-dir>/{spec.artifact_name}",
                ),
                detail="would pull the JSON metrics artifact from the Moto",
            ),
            BenchmarkStep(
                name="Verify benchmark JSON",
                status=StepStatus.PLANNED,
                detail=json_validation_goal(instrumentation_mode),
            ),
        ]
    )
    return tuple(steps)


def build_report(
    *,
    root: Path = ROOT,
    execute: bool = False,
    confirm_device_mutation: bool = False,
    model: Path | None = None,
    device_model_path: str | None = None,
    prompt: str = DEFAULT_PROMPT,
    instrumentation_mode: InstrumentationMode = InstrumentationMode.BENCHMARK,
    runner: CommandRunner = default_command_runner,
    output_directory: Path | None = None,
    device_serial: str | None = None,
    timeout_seconds: int = 300,
) -> BenchmarkReport:
    resolved_root = root.resolve()
    resolved_model = model.expanduser().resolve() if model is not None else None
    planned_device_path = resolve_device_model_path(resolved_model, device_model_path)
    if not execute:
        return BenchmarkReport(
            executed=False,
            ok=True,
            instrumentation_mode=instrumentation_mode.value,
            model_source=str(resolved_model) if resolved_model else None,
            device_model_path=planned_device_path,
            result_artifact=None,
            prompt_chars=len(prompt),
            steps=planned_steps(
                root=resolved_root,
                host_model=resolved_model,
                device_model_path=planned_device_path,
                instrumentation_mode=instrumentation_mode,
            ),
        )

    blockers = execution_blockers(
        confirm_device_mutation=confirm_device_mutation,
        model=resolved_model,
        device_model_path=device_model_path,
        prompt=prompt,
    )
    if blockers:
        return BenchmarkReport(
            executed=False,
            ok=False,
            instrumentation_mode=instrumentation_mode.value,
            model_source=str(resolved_model) if resolved_model else None,
            device_model_path=planned_device_path,
            result_artifact=None,
            prompt_chars=len(prompt),
            steps=tuple(
                BenchmarkStep(
                    name="Execution gate",
                    status=StepStatus.FAIL,
                    detail=blocker,
                )
                for blocker in blockers
            ),
        )

    adb = trusted_adb_path()
    if adb is None:
        return failed_gate(
            model=resolved_model,
            device_model_path=planned_device_path,
            prompt=prompt,
            instrumentation_mode=instrumentation_mode,
            blocker="trusted Android SDK adb executable is unavailable",
        )

    target, target_step = resolve_device_target(
        adb=adb,
        root=resolved_root,
        runner=runner,
        timeout_seconds=30,
        requested_serial=device_serial,
    )
    if target is None:
        return BenchmarkReport(
            executed=False,
            ok=False,
            instrumentation_mode=instrumentation_mode.value,
            model_source=str(resolved_model) if resolved_model else None,
            device_model_path=planned_device_path,
            result_artifact=None,
            prompt_chars=len(prompt),
            steps=(
                BenchmarkStep(
                    name=target_step.name,
                    status=StepStatus.FAIL,
                    command=target_step.command,
                    detail=target_step.detail,
                ),
            ),
        )

    artifacts = output_directory or default_output_directory(resolved_root)
    artifacts.mkdir(parents=True, exist_ok=True)
    spec = INSTRUMENTATION_SPECS[instrumentation_mode]
    result_artifact = artifacts / spec.artifact_name

    steps: list[BenchmarkStep] = [
        BenchmarkStep(
            name=target_step.name,
            status=StepStatus.OK,
            command=target_step.command,
            detail=target_step.detail,
        )
    ]
    steps.extend(
        run_benchmark_steps(
            root=resolved_root,
            adb=adb,
            target=target,
            model=resolved_model,
            device_model_path=require_device_model_path(planned_device_path),
            prompt=prompt,
            instrumentation_mode=instrumentation_mode,
            runner=runner,
            timeout_seconds=timeout_seconds,
            result_artifact=result_artifact,
        )
    )
    ok = all(step.status is StepStatus.OK for step in steps)
    return BenchmarkReport(
        executed=True,
        ok=ok,
        instrumentation_mode=instrumentation_mode.value,
        model_source=str(resolved_model) if resolved_model else None,
        device_model_path=planned_device_path,
        result_artifact=str(result_artifact) if result_artifact.exists() else None,
        prompt_chars=len(prompt),
        steps=tuple(steps),
    )


def failed_gate(
    *,
    model: Path | None,
    device_model_path: str | None,
    prompt: str,
    instrumentation_mode: InstrumentationMode = InstrumentationMode.BENCHMARK,
    blocker: str,
) -> BenchmarkReport:
    return BenchmarkReport(
        executed=False,
        ok=False,
        instrumentation_mode=instrumentation_mode.value,
        model_source=str(model) if model else None,
        device_model_path=device_model_path,
        result_artifact=None,
        prompt_chars=len(prompt),
        steps=(BenchmarkStep(name="Execution gate", status=StepStatus.FAIL, detail=blocker),),
    )


def execution_blockers(
    *,
    confirm_device_mutation: bool,
    model: Path | None,
    device_model_path: str | None,
    prompt: str,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not confirm_device_mutation:
        blockers.append("missing explicit --confirm-device-mutation")
    if model is None and device_model_path is None:
        blockers.append("provide --model or --device-model-path")
    if is_blank_or_too_long(prompt):
        blockers.append(f"prompt must be 1..{MAX_PROMPT_CHARS} characters")

    if model is not None:
        blockers.extend(validate_host_model(model))
    if device_model_path is not None and not is_allowed_device_model_path(device_model_path):
        blockers.append("device model path must be app-owned and end with .litertlm")
    return tuple(blockers)


def validate_host_model(model: Path) -> tuple[str, ...]:
    blockers: list[str] = []
    if not model.is_file():
        blockers.append("host model file missing")
    elif model.stat().st_size > MAX_MODEL_BYTES:
        blockers.append("host model file exceeds the GOFFY LITE 512 MB benchmark budget")
    if not SAFE_MODEL_BASENAME.fullmatch(model.name):
        blockers.append("host model basename must be safe and end with .litertlm")
    return tuple(blockers)


def resolve_device_model_path(model: Path | None, device_model_path: str | None) -> str | None:
    if device_model_path is not None:
        return normalize_device_model_path(device_model_path) or device_model_path
    if model is None:
        return None
    return f"{DEVICE_MODEL_DIR}/{model.name}"


def require_device_model_path(device_model_path: str | None) -> str:
    if device_model_path is None:
        raise ValueError("device model path is required")
    return device_model_path


def is_allowed_device_model_path(path: str) -> bool:
    return normalize_device_model_path(path) is not None


def normalize_device_model_path(path: str) -> str | None:
    if not path.endswith(".litertlm") or "\x00" in path or "\\" in path:
        return None
    parts = path.split("/")
    if ".." in parts:
        return None
    normalized = posixpath.normpath(path)
    return (
        normalized
        if any(normalized.startswith(prefix) for prefix in ALLOWED_DEVICE_MODEL_PREFIXES)
        else None
    )


def run_benchmark_steps(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    model: Path | None,
    device_model_path: str,
    prompt: str,
    instrumentation_mode: InstrumentationMode,
    runner: CommandRunner,
    timeout_seconds: int,
    result_artifact: Path,
) -> tuple[BenchmarkStep, ...]:
    spec = INSTRUMENTATION_SPECS[instrumentation_mode]
    steps: list[BenchmarkStep] = []
    build_step = run_step(
        name="Build benchmark test APK",
        command=(
            str(root / "android" / "gradlew"),
            "-p",
            "android",
            ":app:assembleDebug",
            ":app:assembleDebugAndroidTest",
            "--no-daemon",
        ),
        display_command=(
            str(root / "android" / "gradlew"),
            "-p",
            "android",
            ":app:assembleDebug",
            ":app:assembleDebugAndroidTest",
            "--no-daemon",
        ),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    steps.append(build_step)
    if build_step.status is StepStatus.FAIL:
        return tuple(steps)

    install_step = run_step(
        name="Install debug APK",
        command=adb_command(adb, target, "install", "-r", str(root / DEBUG_APK_RELATIVE_PATH)),
        display_command=display_adb_command(adb, "install", "-r", "<debug-apk>"),
        root=root,
        runner=runner,
        timeout_seconds=120,
        mutates_device=True,
    )
    steps.append(install_step)
    if install_step.status is StepStatus.FAIL:
        return tuple(steps)

    test_install_step = run_step(
        name="Install benchmark test APK",
        command=adb_command(
            adb,
            target,
            "install",
            "-r",
            str(root / DEBUG_TEST_APK_RELATIVE_PATH),
        ),
        display_command=display_adb_command(adb, "install", "-r", "<android-test-apk>"),
        root=root,
        runner=runner,
        timeout_seconds=120,
        mutates_device=True,
    )
    steps.append(test_install_step)
    if test_install_step.status is StepStatus.FAIL:
        return tuple(steps)

    if model is not None:
        prepare_step = run_step(
            name="Prepare app-owned model directory",
            command=adb_shell_command(adb, target, "mkdir", "-p", DEVICE_MODEL_DIR),
            display_command=display_adb_shell_command(
                adb,
                "mkdir",
                "-p",
                DEVICE_MODEL_DIR,
            ),
            root=root,
            runner=runner,
            timeout_seconds=30,
            mutates_device=True,
        )
        steps.append(prepare_step)
        if prepare_step.status is StepStatus.FAIL:
            return tuple(steps)
        push_step = run_step(
            name="Push local model",
            command=adb_command(adb, target, "push", str(model), device_model_path),
            display_command=display_adb_command(
                adb,
                "push",
                "<host-model>",
                device_model_path,
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
        )
        steps.append(push_step)
        if push_step.status is StepStatus.FAIL:
            return tuple(steps)

    instrument_command = adb_shell_command(
        adb,
        target,
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        spec.test_class,
        "-e",
        "modelPath",
        device_model_path,
        "-e",
        "prompt",
        prompt,
        "-e",
        "resultPath",
        spec.device_result_path,
        "-e",
        "timeoutMillis",
        str(timeout_seconds * 1000),
        TEST_RUNNER,
    )
    instrument_display = display_adb_shell_command(
        adb,
        "am",
        "instrument",
        "-w",
        "-r",
        "-e",
        "class",
        spec.test_class,
        "-e",
        "modelPath",
        device_model_path,
        "-e",
        "prompt",
        "<prompt>",
        "-e",
        "resultPath",
        spec.device_result_path,
        "-e",
        "timeoutMillis",
        str(timeout_seconds * 1000),
        TEST_RUNNER,
    )
    instrument_step = run_step(
        name=spec.run_step_name,
        command=instrument_command,
        display_command=instrument_display,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
    )
    steps.append(instrument_step)
    if instrument_step.status is StepStatus.FAIL:
        return tuple(steps)

    pull_step = run_step(
        name="Pull benchmark JSON",
        command=adb_command(adb, target, "pull", spec.device_result_path, str(result_artifact)),
        display_command=display_adb_command(
            adb,
            "pull",
            spec.device_result_path,
            f"<artifact-dir>/{spec.artifact_name}",
        ),
        root=root,
        runner=runner,
        timeout_seconds=60,
        artifact=str(result_artifact),
    )
    steps.append(pull_step)
    if pull_step.status is StepStatus.OK:
        steps.append(benchmark_json_step(result_artifact, instrumentation_mode))
    return tuple(steps)


def adb_shell_command(adb: Path, target: DeviceTarget, *remote_args: str) -> tuple[str, ...]:
    return adb_command(adb, target, "shell", quote_remote_args(remote_args))


def display_adb_shell_command(adb: Path, *remote_args: str) -> tuple[str, ...]:
    return display_adb_command(adb, "shell", quote_remote_args(remote_args))


def quote_remote_args(remote_args: Sequence[str]) -> str:
    return " ".join(shlex.quote(arg) for arg in remote_args)


def run_step(
    *,
    name: str,
    command: Sequence[str],
    display_command: Sequence[str],
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    mutates_device: bool = False,
    artifact: str | None = None,
) -> BenchmarkStep:
    result = runner(command, root, timeout_seconds)
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return BenchmarkStep(
        name=name,
        status=StepStatus.OK if result.exit_code == 0 else StepStatus.FAIL,
        command=tuple(display_command),
        mutates_device=mutates_device,
        detail=tail(output) if output else "ok",
        artifact=artifact if result.exit_code == 0 else None,
    )


def benchmark_json_step(
    path: Path,
    instrumentation_mode: InstrumentationMode = InstrumentationMode.BENCHMARK,
) -> BenchmarkStep:
    if not path.is_file():
        return BenchmarkStep(
            name="Verify benchmark JSON",
            status=StepStatus.FAIL,
            detail="benchmark JSON artifact was not pulled",
        )
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return BenchmarkStep(
            name="Verify benchmark JSON",
            status=StepStatus.FAIL,
            detail=f"benchmark JSON is invalid: {exc.msg}",
            artifact=str(path),
        )
    if not isinstance(payload, dict):
        return BenchmarkStep(
            name="Verify benchmark JSON",
            status=StepStatus.FAIL,
            detail="benchmark JSON root must be an object",
            artifact=str(path),
        )
    payload_dict = cast("dict[str, object]", payload)
    validation_failure = validate_benchmark_json_payload(
        payload_dict,
        instrumentation_mode,
    )
    if validation_failure is None:
        return BenchmarkStep(
            name="Verify benchmark JSON",
            status=StepStatus.OK,
            detail=benchmark_json_summary(payload_dict, instrumentation_mode),
            artifact=str(path),
        )
    return BenchmarkStep(
        name="Verify benchmark JSON",
        status=StepStatus.FAIL,
        detail=f"{validation_failure}: {benchmark_json_failure_summary(payload_dict)}",
        artifact=str(path),
    )


def validate_benchmark_json_payload(
    payload: dict[str, object],
    instrumentation_mode: InstrumentationMode,
) -> str | None:
    status = payload.get("status")
    output_chunk_count = payload.get("outputChunkCount")
    if status != "PASS":
        return "benchmark JSON did not report PASS"
    if not isinstance(output_chunk_count, int) or output_chunk_count <= 0:
        return "benchmark JSON did not report streamed output chunks"
    if instrumentation_mode is InstrumentationMode.ADAPTER_SMOKE:
        return validate_adapter_smoke_json_payload(payload)
    return None


def validate_adapter_smoke_json_payload(payload: dict[str, object]) -> str | None:
    if payload.get("nonAuthoritative") is not True:
        return "adapter smoke JSON did not prove non-authoritative output"
    observation_type = payload.get("observationType")
    if observation_type not in {"Candidate", "Rejected"}:
        return "adapter smoke JSON did not report a terminal adapter observation"
    if observation_type == "Rejected":
        observation_reason = payload.get("observationReason")
        if not isinstance(observation_reason, str) or not observation_reason:
            return "adapter smoke JSON did not explain the rejected observation"
    if observation_type == "Candidate":
        observation_route = payload.get("observationRoute")
        observation_confidence = payload.get("observationConfidence")
        if observation_route not in {"PHONE", "MAC", "CLOUD"}:
            return "adapter smoke JSON candidate did not include an allowed route"
        if (
            isinstance(observation_confidence, bool)
            or not isinstance(observation_confidence, int | float)
            or observation_confidence < 0.70
        ):
            return "adapter smoke JSON candidate did not meet the routing confidence gate"
    return None


def benchmark_json_summary(
    payload: dict[str, object],
    instrumentation_mode: InstrumentationMode = InstrumentationMode.BENCHMARK,
) -> str:
    summary = (
        "benchmark JSON PASS: "
        f"outputChunkCount={payload.get('outputChunkCount')}, "
        f"firstChunkMillis={payload.get('firstChunkMillis')}, "
        f"generationMillis={payload.get('generationMillis')}"
    )
    if instrumentation_mode is InstrumentationMode.ADAPTER_SMOKE:
        summary += (
            f", observationType={payload.get('observationType')}, "
            f"nonAuthoritative={payload.get('nonAuthoritative')}"
        )
    return summary


def benchmark_json_failure_summary(payload: dict[str, object]) -> str:
    parts = [
        f"status={payload.get('status')!r}",
        f"outputChunkCount={payload.get('outputChunkCount')!r}",
        f"observationType={payload.get('observationType')!r}",
        f"nonAuthoritative={payload.get('nonAuthoritative')!r}",
    ]
    error_class = payload.get("errorClass")
    if isinstance(error_class, str) and error_class:
        parts.append(f"errorClass={error_class}")
    error_message = payload.get("errorMessage")
    if isinstance(error_message, str) and error_message:
        parts.append(f"errorMessage={tail(error_message, max_chars=240)}")
    return "benchmark JSON FAIL: " + ", ".join(parts)


def json_validation_goal(instrumentation_mode: InstrumentationMode) -> str:
    if instrumentation_mode is InstrumentationMode.ADAPTER_SMOKE:
        return (
            "would require status PASS, output chunks, non-authoritative adapter output, "
            "and a terminal observation"
        )
    return "would require status PASS and at least one output chunk"


def tail(text: str, max_chars: int = 2000) -> str:
    return text[-max_chars:]


def render_text(report: BenchmarkReport) -> str:
    lines = [
        "GOFFY Moto G LiteRT-LM benchmark",
        f"executed: {report.executed}",
        f"overall: {'PASS' if report.ok else 'FAIL'}",
        f"instrumentation mode: {report.instrumentation_mode}",
        f"device model path: {report.device_model_path or '<not set>'}",
        f"prompt chars: {report.prompt_chars}",
    ]
    if report.result_artifact:
        lines.append(f"result artifact: {report.result_artifact}")
    for step in report.steps:
        lines.append(f"[{step.status}] {step.name}")
        if step.command:
            lines.append(f"       command: {' '.join(step.command)}")
        if step.detail:
            lines.append(f"       detail: {step.detail}")
        if step.artifact:
            lines.append(f"       artifact: {step.artifact}")
    return "\n".join(lines)


def render_json(report: BenchmarkReport) -> str:
    return json.dumps(asdict(report), indent=2)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the GOFFY LiteRT-LM benchmark instrumentation on the Moto G.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually mutate the connected phone.",
    )
    parser.add_argument(
        "--confirm-device-mutation",
        action="store_true",
        help="Required with --execute because this installs APKs and can push a model.",
    )
    parser.add_argument("--model", type=Path, help="Host .litertlm model to push to the Moto.")
    parser.add_argument(
        "--device-model-path",
        help="Use an already-pushed model under GOFFY's app-owned model directory.",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Short benchmark prompt.")
    parser.add_argument(
        "--instrumentation-mode",
        choices=[mode.value for mode in InstrumentationMode],
        default=InstrumentationMode.BENCHMARK.value,
        help="Instrumentation flow to run.",
    )
    parser.add_argument("--device-serial", help="ADB serial when more than one device is attached.")
    parser.add_argument("--output-directory", type=Path, help="Artifact output directory.")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        execute=args.execute,
        confirm_device_mutation=args.confirm_device_mutation,
        model=args.model,
        device_model_path=args.device_model_path,
        prompt=args.prompt,
        instrumentation_mode=InstrumentationMode(args.instrumentation_mode),
        output_directory=args.output_directory,
        device_serial=args.device_serial,
        timeout_seconds=args.timeout_seconds,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


def is_blank_or_too_long(value: str) -> bool:
    return not value.strip() or len(value) > MAX_PROMPT_CHARS


if __name__ == "__main__":
    raise SystemExit(main())
