from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_moto_g_device_smoke import (  # noqa: E402
    CommandRunner,
    DeviceSmokeStep,
    DeviceTarget,
    StepStatus,
    adb_command,
    default_command_runner,
    display_adb_command,
    dump_ui,
    execute_step,
    find_command_field,
    find_node,
    latest_ui_text,
    resolve_device_target,
    submit_and_verify_command,
    tap_center,
    trusted_adb_path,
)

JSON_SCHEMA_VERSION = "goffy.moto-g-modeldebug-observation-smoke.v1"
MODEL_DEBUG_APK_RELATIVE_PATH = Path(
    "android/app/build/outputs/apk/modelDebug/app-modelDebug.apk",
)
MODEL_DEBUG_PACKAGE_NAME = "dev.goffy.os.model"
MODEL_DEBUG_MAIN_ACTIVITY = f"{MODEL_DEBUG_PACKAGE_NAME}/dev.goffy.os.MainActivity"
PRIVATE_MODEL_DIR = "no_backup/local-models"
PRIVATE_ROUTER_MODEL_PATH = f"{PRIVATE_MODEL_DIR}/router.litertlm"
DEFAULT_COMMAND = "open settings"
DEFAULT_WAIT_TIMEOUT_SECONDS = 45
REMOTE_UI_XML_PREFIX = "modeldebug-observation"
MAX_MODEL_BYTES = 512 * 1024 * 1024
MAX_COMMAND_CHARS = 120
SAFE_MODEL_BASENAME = re.compile(r"^[A-Za-z0-9._-]+\.litertlm$")
SAFE_COMMAND = re.compile(r"^[A-Za-z0-9 .,_:-]{1,120}$")
OBSERVATION_MARKERS = (
    "FAILED",
    "No safe deterministic route is available",
    "Model output exceeded the local routing output budget",
)
DEVICE_SERIAL_PLACEHOLDER = "<device-serial>"
MODEL_PLACEHOLDER = "<host-model>"


@dataclass(frozen=True)
class ModelDebugObservationReport:
    schema_version: str
    executed: bool
    ok: bool
    output_directory: str | None
    command: str
    model_source: str | None
    model_sha256: str | None
    observation_elapsed_millis: int | None
    steps: tuple[DeviceSmokeStep, ...]


def default_output_directory(root: Path = ROOT) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / ".goffy-validation" / "modeldebug-observation-smoke" / timestamp


def planned_steps(root: Path, model: Path | None, command: str) -> tuple[DeviceSmokeStep, ...]:
    apk = root / MODEL_DEBUG_APK_RELATIVE_PATH
    model_display = str(model) if model is not None else MODEL_PLACEHOLDER
    return (
        DeviceSmokeStep(
            name="Build modelDebug APK",
            status=StepStatus.PLANNED,
            command=(
                str(root / "android" / "gradlew"),
                "-p",
                "android",
                ":app:assembleModelDebug",
                "--no-daemon",
            ),
            detail="would compile the runtime-capable developer APK",
        ),
        DeviceSmokeStep(
            name="Verify Moto G target",
            status=StepStatus.PLANNED,
            command=("adb", "devices", "-l"),
            detail="would require exactly one approved Moto G or --device-serial",
        ),
        DeviceSmokeStep(
            name="Install modelDebug APK",
            status=StepStatus.PLANNED,
            command=("adb", "-s", DEVICE_SERIAL_PLACEHOLDER, "install", "-r", str(apk)),
            mutates_device=True,
            detail="would install or replace dev.goffy.os.model",
        ),
        DeviceSmokeStep(
            name="Stage local model",
            status=StepStatus.PLANNED,
            command=(
                "adb",
                "-s",
                DEVICE_SERIAL_PLACEHOLDER,
                "push",
                model_display,
                "/data/local/tmp/<safe-model>.litertlm",
            ),
            mutates_device=True,
            detail="would stage one approved .litertlm model for private app copy",
        ),
        DeviceSmokeStep(
            name="Seed private router model",
            status=StepStatus.PLANNED,
            command=(
                "adb",
                "-s",
                DEVICE_SERIAL_PLACEHOLDER,
                "shell",
                "run-as",
                MODEL_DEBUG_PACKAGE_NAME,
                "cp",
                "/data/local/tmp/<safe-model>.litertlm",
                PRIVATE_ROUTER_MODEL_PATH,
            ),
            mutates_device=True,
            detail="would copy the model to noBackupFilesDir/local-models/router.litertlm",
        ),
        DeviceSmokeStep(
            name="Launch modelDebug GOFFY",
            status=StepStatus.PLANNED,
            command=(
                "adb",
                "-s",
                DEVICE_SERIAL_PLACEHOLDER,
                "shell",
                "am",
                "start",
                "-W",
                "-n",
                MODEL_DEBUG_MAIN_ACTIVITY,
            ),
            mutates_device=True,
            detail="would launch the runtime-capable GOFFY app",
        ),
        DeviceSmokeStep(
            name="Enable local-model runtime setting",
            status=StepStatus.PLANNED,
            mutates_device=True,
            detail="would tap the foreground Enable setting button and verify OBSERVE ONLY",
        ),
        DeviceSmokeStep(
            name="Unsupported command observation smoke",
            status=StepStatus.PLANNED,
            mutates_device=True,
            detail=f"would submit `{command}` and verify a non-executable local-model timeline",
        ),
        DeviceSmokeStep(
            name="Capture final UI XML",
            status=StepStatus.PLANNED,
            detail="would save UIAutomator XML for the terminal timeline",
            artifact="final-ui.xml",
        ),
        DeviceSmokeStep(
            name="Capture battery snapshot",
            status=StepStatus.PLANNED,
            detail="would save bounded battery state after observation",
            artifact="battery-after.txt",
        ),
        DeviceSmokeStep(
            name="Capture memory snapshot",
            status=StepStatus.PLANNED,
            detail="would save bounded meminfo for dev.goffy.os.model after observation",
            artifact="meminfo-after.txt",
        ),
    )


def build_report(
    *,
    root: Path = ROOT,
    execute: bool = False,
    confirm_device_mutation: bool = False,
    model: Path | None = None,
    command: str = DEFAULT_COMMAND,
    output_directory: Path | None = None,
    device_serial: str | None = None,
    timeout_seconds: int = 300,
    wait_timeout_seconds: int = DEFAULT_WAIT_TIMEOUT_SECONDS,
    runner: CommandRunner = default_command_runner,
    env: Mapping[str, str] | None = None,
) -> ModelDebugObservationReport:
    resolved_root = root.resolve()
    resolved_model = model.expanduser().resolve() if model is not None else None
    model_digest = (
        sha256_file(resolved_model)
        if resolved_model is not None and resolved_model.is_file()
        else None
    )

    if not execute:
        return ModelDebugObservationReport(
            schema_version=JSON_SCHEMA_VERSION,
            executed=False,
            ok=True,
            output_directory=None,
            command=command,
            model_source=str(resolved_model) if resolved_model is not None else None,
            model_sha256=model_digest,
            observation_elapsed_millis=None,
            steps=planned_steps(resolved_root, resolved_model, command),
        )

    blockers = execution_blockers(
        confirm_device_mutation=confirm_device_mutation,
        model=resolved_model,
        command=command,
        timeout_seconds=timeout_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
    )
    if blockers:
        return failed_report(
            command=command,
            model=resolved_model,
            model_digest=model_digest,
            blockers=blockers,
        )

    adb = trusted_adb_path(env) if env is not None else trusted_adb_path()
    if adb is None:
        return failed_report(
            command=command,
            model=resolved_model,
            model_digest=model_digest,
            blockers=("trusted Android SDK adb executable is unavailable",),
        )

    target, target_step = resolve_device_target(
        adb=adb,
        root=resolved_root,
        runner=runner,
        timeout_seconds=30,
        requested_serial=device_serial,
    )
    if target is None:
        return ModelDebugObservationReport(
            schema_version=JSON_SCHEMA_VERSION,
            executed=False,
            ok=False,
            output_directory=None,
            command=command,
            model_source=str(resolved_model) if resolved_model is not None else None,
            model_sha256=model_digest,
            observation_elapsed_millis=None,
            steps=(target_step,),
        )

    artifacts = output_directory or default_output_directory(resolved_root)
    artifacts.mkdir(parents=True, exist_ok=True)
    steps: list[DeviceSmokeStep] = [
        replace(target_step, status=StepStatus.OK),
    ]
    elapsed_millis: int | None = None
    model_path = require_model(resolved_model)
    for step in run_smoke_steps(
        root=resolved_root,
        adb=adb,
        target=target,
        model=model_path,
        command=command,
        output_directory=artifacts,
        runner=runner,
        timeout_seconds=timeout_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
    ):
        steps.append(step)
        if step.name == "Unsupported command observation smoke" and step.status is StepStatus.OK:
            elapsed_millis = parse_elapsed_millis(step.detail)
        if step.status is StepStatus.FAIL:
            break
    ok = all(step.status is not StepStatus.FAIL for step in steps)
    return ModelDebugObservationReport(
        schema_version=JSON_SCHEMA_VERSION,
        executed=True,
        ok=ok,
        output_directory=str(artifacts),
        command=command,
        model_source=str(model_path),
        model_sha256=model_digest,
        observation_elapsed_millis=elapsed_millis,
        steps=tuple(steps),
    )


def failed_report(
    *,
    command: str,
    model: Path | None,
    model_digest: str | None,
    blockers: tuple[str, ...],
) -> ModelDebugObservationReport:
    return ModelDebugObservationReport(
        schema_version=JSON_SCHEMA_VERSION,
        executed=False,
        ok=False,
        output_directory=None,
        command=command,
        model_source=str(model) if model is not None else None,
        model_sha256=model_digest,
        observation_elapsed_millis=None,
        steps=tuple(
            DeviceSmokeStep(name="Execution gate", status=StepStatus.FAIL, detail=blocker)
            for blocker in blockers
        ),
    )


def execution_blockers(
    *,
    confirm_device_mutation: bool,
    model: Path | None,
    command: str,
    timeout_seconds: int,
    wait_timeout_seconds: int,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not confirm_device_mutation:
        blockers.append("missing explicit --confirm-device-mutation")
    if command != DEFAULT_COMMAND:
        blockers.append(
            f"execute mode only supports the fixed observe-only command `{DEFAULT_COMMAND}`"
        )
    if model is None:
        blockers.append("provide --model")
    elif not model.is_file():
        blockers.append("host model file missing")
    else:
        if model.stat().st_size > MAX_MODEL_BYTES:
            blockers.append("host model file exceeds the GOFFY LITE 512 MB budget")
        if SAFE_MODEL_BASENAME.fullmatch(model.name) is None:
            blockers.append("host model basename must be safe and end with .litertlm")
    if SAFE_COMMAND.fullmatch(command) is None:
        blockers.append(f"command must be 1..{MAX_COMMAND_CHARS} chars and ADB-input safe")
    if timeout_seconds < 30:
        blockers.append("timeout must be at least 30 seconds")
    if wait_timeout_seconds < 15:
        blockers.append("wait timeout must be at least 15 seconds")
    return tuple(blockers)


def require_model(model: Path | None) -> Path:
    if model is None:
        raise ValueError("model is required after execution blockers pass")
    return model


def run_smoke_steps(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    model: Path,
    command: str,
    output_directory: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    wait_timeout_seconds: int,
) -> tuple[DeviceSmokeStep, ...]:
    steps: list[DeviceSmokeStep] = []
    build_step = build_modeldebug_apk(root, runner, timeout_seconds)
    steps.append(build_step)
    if build_step.status is StepStatus.FAIL:
        return tuple(steps)
    install_step = install_modeldebug_apk(root, adb, target, runner, timeout_seconds)
    steps.append(install_step)
    if install_step.status is StepStatus.FAIL:
        return tuple(steps)
    seed_step = seed_private_model(root, adb, target, model, runner, timeout_seconds)
    steps.append(seed_step)
    if seed_step.status is StepStatus.FAIL:
        return tuple(steps)
    launch_step = launch_modeldebug(root, adb, target, runner, timeout_seconds)
    steps.append(launch_step)
    if launch_step.status is StepStatus.FAIL:
        return tuple(steps)

    for step in (
        verify_modeldebug_home(root, adb, target, output_directory, runner, timeout_seconds),
        enable_local_model_runtime(root, adb, target, output_directory, runner, timeout_seconds),
        reveal_command_surface(root, adb, target, runner, timeout_seconds),
    ):
        steps.append(step)
        if step.status is StepStatus.FAIL:
            return tuple(steps)

    started = time.monotonic()
    observation = submit_and_verify_command(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        wait_timeout_seconds=wait_timeout_seconds,
        command=command,
        expected_markers=OBSERVATION_MARKERS,
        step_name="Unsupported command observation smoke",
        artifact_prefix="modeldebug-observation-command",
        output_directory=output_directory,
    )
    elapsed = int((time.monotonic() - started) * 1000)
    if observation.status is StepStatus.OK:
        observation = replace(
            observation,
            detail=f"{observation.detail}; elapsedMillis={elapsed}",
        )
    steps.append(observation)
    if observation.status is StepStatus.FAIL:
        return tuple(steps)

    steps.extend(
        (
            dump_ui(
                adb=adb,
                target=target,
                root=root,
                runner=runner,
                timeout_seconds=timeout_seconds,
                artifact_path=output_directory / "final-ui.xml",
            ),
            capture_text_artifact(
                name="Capture battery snapshot",
                command=adb_command(adb, target, "shell", "dumpsys", "battery"),
                display_command=display_adb_command(adb, "shell", "dumpsys", "battery"),
                artifact_path=output_directory / "battery-after.txt",
                root=root,
                runner=runner,
                timeout_seconds=timeout_seconds,
            ),
            capture_text_artifact(
                name="Capture memory snapshot",
                command=adb_command(
                    adb,
                    target,
                    "shell",
                    "dumpsys",
                    "meminfo",
                    MODEL_DEBUG_PACKAGE_NAME,
                ),
                display_command=display_adb_command(
                    adb,
                    "shell",
                    "dumpsys",
                    "meminfo",
                    MODEL_DEBUG_PACKAGE_NAME,
                ),
                artifact_path=output_directory / "meminfo-after.txt",
                root=root,
                runner=runner,
                timeout_seconds=timeout_seconds,
            ),
            capture_modeldebug_logcat(
                root=root,
                adb=adb,
                target=target,
                output_directory=output_directory,
                runner=runner,
                timeout_seconds=timeout_seconds,
            ),
        )
    )
    return tuple(steps)


def build_modeldebug_apk(
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    return execute_step(
        name="Build modelDebug APK",
        command=(
            str(root / "android" / "gradlew"),
            "-p",
            "android",
            ":app:assembleModelDebug",
            "--no-daemon",
        ),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        display_command=(
            str(root / "android" / "gradlew"),
            "-p",
            "android",
            ":app:assembleModelDebug",
            "--no-daemon",
        ),
    )


def install_modeldebug_apk(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    apk = root / MODEL_DEBUG_APK_RELATIVE_PATH
    return execute_step(
        name="Install modelDebug APK",
        command=adb_command(adb, target, "install", "-r", str(apk)),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(adb, "install", "-r", str(apk)),
    )


def seed_private_model(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    model: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    stage_path = f"/data/local/tmp/goffy-modeldebug-{model.name}"
    stage_step = execute_step(
        name="Stage local model",
        command=adb_command(adb, target, "push", str(model), stage_path),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(adb, "push", MODEL_PLACEHOLDER, stage_path),
    )
    if stage_step.status is StepStatus.FAIL:
        return stage_step
    mkdir_step = execute_step(
        name="Create private router model directory",
        command=adb_command(
            adb,
            target,
            "shell",
            "run-as",
            MODEL_DEBUG_PACKAGE_NAME,
            "mkdir",
            "-p",
            PRIVATE_MODEL_DIR,
        ),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(
            adb,
            "shell",
            "run-as",
            MODEL_DEBUG_PACKAGE_NAME,
            "mkdir",
            "-p",
            PRIVATE_MODEL_DIR,
        ),
    )
    if mkdir_step.status is StepStatus.FAIL:
        return cleanup_after_post_push_failure(
            root,
            adb,
            target,
            stage_path,
            mkdir_step,
            runner,
            timeout_seconds,
        )
    copy_step = execute_step(
        name="Seed private router model",
        command=adb_command(
            adb,
            target,
            "shell",
            "run-as",
            MODEL_DEBUG_PACKAGE_NAME,
            "cp",
            stage_path,
            PRIVATE_ROUTER_MODEL_PATH,
        ),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(
            adb,
            "shell",
            "run-as",
            MODEL_DEBUG_PACKAGE_NAME,
            "cp",
            "/data/local/tmp/<safe-model>.litertlm",
            PRIVATE_ROUTER_MODEL_PATH,
        ),
    )
    if copy_step.status is StepStatus.FAIL:
        return cleanup_after_post_push_failure(
            root,
            adb,
            target,
            stage_path,
            copy_step,
            runner,
            timeout_seconds,
        )
    verify_step = execute_step(
        name="Verify private router model",
        command=adb_command(
            adb,
            target,
            "shell",
            "run-as",
            MODEL_DEBUG_PACKAGE_NAME,
            "ls",
            "-l",
            PRIVATE_ROUTER_MODEL_PATH,
        ),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(
            adb,
            "shell",
            "run-as",
            MODEL_DEBUG_PACKAGE_NAME,
            "ls",
            "-l",
            PRIVATE_ROUTER_MODEL_PATH,
        ),
    )
    if verify_step.status is StepStatus.FAIL:
        return cleanup_after_post_push_failure(
            root,
            adb,
            target,
            stage_path,
            verify_step,
            runner,
            timeout_seconds,
        )
    cleanup_step = remove_staged_model(root, adb, target, stage_path, runner, timeout_seconds)
    if cleanup_step.status is StepStatus.FAIL:
        return cleanup_step
    return DeviceSmokeStep(
        name="Seed private router model",
        status=StepStatus.OK,
        mutates_device=True,
        detail="copied approved model to noBackupFilesDir/local-models/router.litertlm",
    )


def cleanup_after_post_push_failure(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    stage_path: str,
    failure_step: DeviceSmokeStep,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    cleanup = remove_staged_model(root, adb, target, stage_path, runner, timeout_seconds)
    if cleanup.status is StepStatus.FAIL:
        return replace(
            failure_step,
            detail=f"{failure_step.detail}; staged model cleanup failed",
        )
    return replace(
        failure_step,
        detail=f"{failure_step.detail}; staged model cleanup attempted",
    )


def remove_staged_model(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    stage_path: str,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    return execute_step(
        name="Remove staged local model",
        command=adb_command(adb, target, "shell", "rm", "-f", stage_path),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(
            adb,
            "shell",
            "rm",
            "-f",
            "/data/local/tmp/<safe-model>.litertlm",
        ),
    )


def launch_modeldebug(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    stop = execute_step(
        name="Stop modelDebug GOFFY",
        command=adb_command(adb, target, "shell", "am", "force-stop", MODEL_DEBUG_PACKAGE_NAME),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(
            adb,
            "shell",
            "am",
            "force-stop",
            MODEL_DEBUG_PACKAGE_NAME,
        ),
    )
    if stop.status is StepStatus.FAIL:
        return stop
    launch = execute_step(
        name="Launch modelDebug GOFFY",
        command=adb_command(
            adb,
            target,
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            MODEL_DEBUG_MAIN_ACTIVITY,
        ),
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        mutates_device=True,
        display_command=display_adb_command(
            adb,
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            MODEL_DEBUG_MAIN_ACTIVITY,
        ),
    )
    if launch.status is StepStatus.OK:
        time.sleep(2)
    return launch


def verify_modeldebug_home(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    output_directory: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    step = dump_ui(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
        artifact_path=output_directory / "after-launch.xml",
    )
    if step.status is not StepStatus.OK:
        return step
    text = (output_directory / "after-launch.xml").read_text(encoding="utf-8")
    if "LOCAL MODEL RUNTIME" in text and MODEL_DEBUG_PACKAGE_NAME in text:
        return DeviceSmokeStep(
            name="Verify modelDebug home",
            status=StepStatus.OK,
            detail="modelDebug home shell and local-model runtime card are visible",
            artifact="after-launch.xml",
        )
    return DeviceSmokeStep(
        name="Verify modelDebug home",
        status=StepStatus.FAIL,
        detail="modelDebug local-model runtime card was not visible",
        remediation="Inspect after-launch.xml and confirm the modelDebug APK launched.",
        artifact="after-launch.xml",
    )


def enable_local_model_runtime(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    output_directory: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    ui_text = latest_ui_text(
        adb=adb,
        target=target,
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )
    if runtime_ready(ui_text):
        (output_directory / "local-model-enabled.xml").write_text(ui_text, encoding="utf-8")
        return DeviceSmokeStep(
            name="Enable local-model runtime setting",
            status=StepStatus.OK,
            mutates_device=True,
            detail="local-model runtime setting was already enabled and ready",
            artifact="local-model-enabled.xml",
        )

    enable = find_node(ui_text, text="Enable setting")
    if enable is None:
        (output_directory / "local-model-enable-missing.xml").write_text(ui_text, encoding="utf-8")
        return DeviceSmokeStep(
            name="Enable local-model runtime setting",
            status=StepStatus.FAIL,
            mutates_device=True,
            detail="Enable setting button was not visible",
            remediation="Inspect the local model card and private model file status.",
            artifact="local-model-enable-missing.xml",
        )

    tapped = tap_center(
        adb,
        target,
        root,
        runner,
        timeout_seconds,
        enable,
        step_name="Enable local-model runtime setting",
    )
    if tapped.status is not StepStatus.OK:
        return tapped

    deadline = time.monotonic() + 15
    last_text = ""
    while time.monotonic() <= deadline:
        last_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        if runtime_ready(last_text):
            (output_directory / "local-model-enabled.xml").write_text(
                last_text,
                encoding="utf-8",
            )
            return DeviceSmokeStep(
                name="Enable local-model runtime setting",
                status=StepStatus.OK,
                mutates_device=True,
                detail="foreground setting saved and status reports OBSERVE ONLY",
                artifact="local-model-enabled.xml",
            )
        time.sleep(1)

    (output_directory / "local-model-enable-timeout.xml").write_text(last_text, encoding="utf-8")
    return DeviceSmokeStep(
        name="Enable local-model runtime setting",
        status=StepStatus.FAIL,
        mutates_device=True,
        detail="runtime setting did not reach OBSERVE ONLY before timeout",
        remediation=(
            "Inspect private model seeding, settings persistence, and local-model status text."
        ),
        artifact="local-model-enable-timeout.xml",
    )


def runtime_ready(ui_text: str) -> bool:
    return "OBSERVE ONLY" in ui_text and "Local model ready for observe-only fallback" in ui_text


def reveal_command_surface(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    collapse = collapse_hub_setup_if_visible(root, adb, target, runner, timeout_seconds)
    if collapse.status is StepStatus.FAIL:
        return collapse
    for attempt in range(5):
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        if find_command_field(ui_text) is not None and "Development bearer token" not in ui_text:
            return DeviceSmokeStep(
                name="Reveal command surface",
                status=StepStatus.OK,
                mutates_device=True,
                detail="command input field is visible with Hub setup collapsed",
            )
        if attempt == 4:
            break
        scroll = execute_step(
            name="Reveal command surface",
            command=adb_command(
                adb,
                target,
                "shell",
                "input",
                "swipe",
                "360",
                "1450",
                "360",
                "650",
                "450",
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                "360",
                "1450",
                "360",
                "650",
                "450",
            ),
        )
        if scroll.status is StepStatus.FAIL:
            return scroll
        time.sleep(1)
    return DeviceSmokeStep(
        name="Reveal command surface",
        status=StepStatus.FAIL,
        mutates_device=True,
        detail="command input field was not visible after bounded scroll",
        remediation="Inspect after-launch/local-model XML for layout changes.",
    )


def collapse_hub_setup_if_visible(
    root: Path,
    adb: Path,
    target: DeviceTarget,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    for attempt in range(4):
        ui_text = latest_ui_text(
            adb=adb,
            target=target,
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        hide = find_node(ui_text, text="Hide")
        if hide is not None:
            step = tap_center(
                adb,
                target,
                root,
                runner,
                timeout_seconds,
                hide,
                step_name="Collapse Hub setup card",
            )
            if step.status is StepStatus.OK:
                time.sleep(1)
            return step
        if "Development bearer token" not in ui_text:
            return DeviceSmokeStep(
                name="Collapse Hub setup card",
                status=StepStatus.SKIP,
                detail="Hub setup card was already collapsed or not visible",
            )
        if attempt == 3:
            break
        scroll = execute_step(
            name="Collapse Hub setup card: Reveal Hide",
            command=adb_command(
                adb,
                target,
                "shell",
                "input",
                "swipe",
                "360",
                "1450",
                "360",
                "650",
                "450",
            ),
            root=root,
            runner=runner,
            timeout_seconds=timeout_seconds,
            mutates_device=True,
            display_command=display_adb_command(
                adb,
                "shell",
                "input",
                "swipe",
                "360",
                "1450",
                "360",
                "650",
                "450",
            ),
        )
        if scroll.status is StepStatus.FAIL:
            return scroll
        time.sleep(1)
    return DeviceSmokeStep(
        name="Collapse Hub setup card",
        status=StepStatus.FAIL,
        mutates_device=True,
        detail="Hub setup card remained expanded after bounded scroll",
        remediation="Inspect UI XML for setup-card layout changes.",
    )


def capture_text_artifact(
    *,
    name: str,
    command: Sequence[str],
    display_command: Sequence[str],
    artifact_path: Path,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    result = runner(command, root, timeout_seconds)
    if result.exit_code != 0:
        return DeviceSmokeStep(
            name=name,
            status=StepStatus.FAIL,
            command=tuple(display_command),
            detail="command failed",
        )
    artifact_path.write_text(result.stdout[-24_000:], encoding="utf-8")
    return DeviceSmokeStep(
        name=name,
        status=StepStatus.OK,
        command=tuple(display_command),
        detail="captured bounded diagnostic artifact",
        artifact=artifact_path.name,
    )


def capture_modeldebug_logcat(
    *,
    root: Path,
    adb: Path,
    target: DeviceTarget,
    output_directory: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> DeviceSmokeStep:
    pid_result = runner(
        adb_command(adb, target, "shell", "pidof", MODEL_DEBUG_PACKAGE_NAME),
        root,
        timeout_seconds,
    )
    pid = pid_result.stdout.strip().split()[0] if pid_result.exit_code == 0 else ""
    if not pid.isdigit():
        return DeviceSmokeStep(
            name="Capture bounded modelDebug logcat",
            status=StepStatus.SKIP,
            detail="modelDebug process pid unavailable",
        )
    return capture_text_artifact(
        name="Capture bounded modelDebug logcat",
        command=adb_command(adb, target, "logcat", "-d", "--pid", pid, "-t", "200"),
        display_command=display_adb_command(
            adb, "logcat", "-d", "--pid", "<goffy-pid>", "-t", "200"
        ),
        artifact_path=output_directory / "modeldebug-logcat.txt",
        root=root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )


def sha256_file(path: Path | None) -> str | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_elapsed_millis(detail: str) -> int | None:
    marker = "elapsedMillis="
    if marker not in detail:
        return None
    value = detail.rsplit(marker, 1)[-1].strip()
    return int(value) if value.isdigit() else None


def render_text(report: ModelDebugObservationReport) -> str:
    lines = [
        "GOFFY Moto G modelDebug observation smoke",
        f"schema: {report.schema_version}",
        f"executed: {report.executed}",
        f"overall: {'PASS' if report.ok else 'FAIL'}",
        f"command: {report.command}",
        f"model sha256: {report.model_sha256 or '<not available>'}",
    ]
    if report.output_directory:
        lines.append(f"output directory: {report.output_directory}")
    if report.observation_elapsed_millis is not None:
        lines.append(f"observation elapsed millis: {report.observation_elapsed_millis}")
    for step in report.steps:
        lines.append(f"[{step.status}] {step.name}")
        if step.command:
            lines.append(f"       command: {' '.join(step.command)}")
        if step.detail:
            lines.append(f"       detail: {step.detail}")
        if step.remediation:
            lines.append(f"       remediation: {step.remediation}")
        if step.artifact:
            lines.append(f"       artifact: {step.artifact}")
    return "\n".join(lines)


def render_json(report: ModelDebugObservationReport) -> str:
    return json.dumps(asdict(report), indent=2)


def write_report_artifact(report: ModelDebugObservationReport) -> Path | None:
    if report.output_directory is None:
        return None
    output_directory = Path(report.output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / "modeldebug-observation-report.json"
    report_path.write_text(f"{render_json(report)}\n", encoding="utf-8")
    return report_path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the GOFFY modelDebug local-model observation smoke on a Moto G.",
    )
    parser.add_argument(
        "--execute", action="store_true", help="Actually mutate the connected phone."
    )
    parser.add_argument(
        "--confirm-device-mutation",
        action="store_true",
        help="Required with --execute because this installs an APK and pushes a model.",
    )
    parser.add_argument(
        "--model", type=Path, help="Host .litertlm model to seed as router.litertlm."
    )
    parser.add_argument("--command", default=DEFAULT_COMMAND, help="Unsupported command to submit.")
    parser.add_argument("--device-serial", help="ADB serial when more than one device is attached.")
    parser.add_argument("--output-directory", type=Path, help="Artifact output directory.")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--wait-timeout-seconds", type=int, default=DEFAULT_WAIT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        execute=args.execute,
        confirm_device_mutation=args.confirm_device_mutation,
        model=args.model,
        command=args.command,
        output_directory=args.output_directory,
        device_serial=args.device_serial,
        timeout_seconds=args.timeout_seconds,
        wait_timeout_seconds=args.wait_timeout_seconds,
    )
    write_report_artifact(report)
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
