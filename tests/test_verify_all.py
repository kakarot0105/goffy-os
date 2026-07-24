from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from scripts.android_preflight import Check
from scripts.verify_all import (
    CommandRunner,
    PreflightCollector,
    StepStatus,
    android_apk_budget_command,
    android_gradle_command,
    android_local_model_provider_command,
    android_tflite_task_text_classifier_command,
    merged_manifest_security_command,
    render_verification_report,
    rom_feature_payload_command,
    rom_gsi_metadata_freshness_command,
    rom_system_app_command,
    run_verification,
    tflite_task_text_dependency_command,
)


def passing_runner(
    seen: list[tuple[str, ...]],
) -> CommandRunner:
    def run(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        return subprocess.CompletedProcess(normalized, 0, stdout="ok\n", stderr="")

    return run


def failing_runner(
    failed_command_name: str,
) -> CommandRunner:
    def run(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        normalized = tuple(str(part) for part in command)
        if failed_command_name in normalized:
            return subprocess.CompletedProcess(normalized, 1, stdout="", stderr="failed\n")
        return subprocess.CompletedProcess(normalized, 0, stdout="ok\n", stderr="")

    return run


def preflight(ok: bool, *, name: str = "JDK") -> PreflightCollector:
    def collect(root: Path) -> list[Check]:
        return [
            Check(
                name=name,
                ok=ok,
                detail="ready" if ok else "missing",
                remediation="" if ok else "install JDK",
            )
        ]

    return collect


def test_verifier_skips_android_gradle_when_preflight_is_blocked_and_allowed(
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, ...]] = []

    report = run_verification(
        root=tmp_path,
        python="python",
        runner=passing_runner(seen),
        preflight_collector=preflight(False),
        allow_missing_android=True,
    )

    assert report.ok
    assert any(
        step.name == "android preflight" and step.status is StepStatus.BLOCKED
        for step in report.steps
    )
    assert report.steps[-5].name == "android gradle"
    assert report.steps[-5].status is StepStatus.SKIP
    assert report.steps[-4].name == "android APK budget"
    assert report.steps[-4].status is StepStatus.SKIP
    assert report.steps[-3].name == "android local model provider"
    assert report.steps[-3].status is StepStatus.SKIP
    assert report.steps[-2].name == "android TFLite Task Text classifier"
    assert report.steps[-2].status is StepStatus.SKIP
    assert report.steps[-1].name == "merged manifest security scan"
    assert report.steps[-1].status is StepStatus.SKIP
    assert all(":app:testDebugUnitTest" not in command for command in seen)
    assert tflite_task_text_dependency_command("python") in seen


def test_verifier_runs_tflite_dependency_when_android_is_missing_and_allowed(
    tmp_path: Path,
) -> None:
    seen: list[tuple[str, ...]] = []

    report = run_verification(
        root=tmp_path,
        python="python",
        runner=passing_runner(seen),
        preflight_collector=preflight(False),
        allow_missing_android=True,
    )

    assert report.ok
    assert tflite_task_text_dependency_command("python") in seen
    assert any(
        step.name == "TFLite Task Text dependency" and step.status is StepStatus.OK
        for step in report.steps
    )


def test_verifier_fails_when_android_preflight_is_blocked_by_default(tmp_path: Path) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=passing_runner([]),
        preflight_collector=preflight(False),
    )

    assert not report.ok
    assert report.steps[-1].status is StepStatus.SKIP


def test_verifier_does_not_allow_repo_owned_android_preflight_failures(
    tmp_path: Path,
) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=passing_runner([]),
        preflight_collector=preflight(False, name="Gradle wrapper"),
        allow_missing_android=True,
    )

    assert not report.ok
    assert any(
        step.name == "android preflight" and step.status is StepStatus.FAIL for step in report.steps
    )


def test_verifier_runs_android_gradle_when_preflight_passes(tmp_path: Path) -> None:
    seen: list[tuple[str, ...]] = []

    report = run_verification(
        root=tmp_path,
        python="python",
        runner=passing_runner(seen),
        preflight_collector=preflight(True),
    )

    assert report.ok
    assert tflite_task_text_dependency_command("python") in seen
    assert seen[-5] == android_gradle_command(tmp_path)
    assert ":app:lintDebug" in seen[-5]
    assert ":app:assembleDebugAndroidTest" in seen[-5]
    assert ":app:assembleRelease" in seen[-5]
    assert seen[-4] == android_apk_budget_command("python")
    assert seen[-3] == android_local_model_provider_command(tmp_path)
    assert seen[-2] == android_tflite_task_text_classifier_command(tmp_path)
    assert "-Pgoffy.testBuildType=modelDebug" in seen[-2]
    assert ":app:testModelDebugUnitTest" in seen[-2]
    assert ":app:assembleModelDebugAndroidTest" in seen[-2]
    assert seen[-1] == merged_manifest_security_command("python")


def test_verifier_runs_rom_system_app_validation(tmp_path: Path) -> None:
    seen: list[tuple[str, ...]] = []

    report = run_verification(
        root=tmp_path,
        python="python",
        runner=passing_runner(seen),
        preflight_collector=preflight(False),
        allow_missing_android=True,
    )

    assert report.ok
    assert rom_system_app_command("python") in seen
    assert rom_feature_payload_command("python") in seen
    assert rom_gsi_metadata_freshness_command("python") in seen
    assert ("python", "scripts/verify_local_intent_router_corpus.py") in seen


def test_verifier_fails_when_android_gradle_is_skipped_on_ready_toolchain(
    tmp_path: Path,
) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=passing_runner([]),
        preflight_collector=preflight(True),
        allow_missing_android=True,
        skip_android_gradle=True,
    )

    assert not report.ok
    assert report.steps[-5].name == "android gradle"
    assert report.steps[-5].status is StepStatus.SKIP
    assert report.steps[-4].name == "android APK budget"
    assert report.steps[-4].status is StepStatus.SKIP
    assert report.steps[-3].name == "android local model provider"
    assert report.steps[-3].status is StepStatus.SKIP
    assert report.steps[-2].name == "android TFLite Task Text classifier"
    assert report.steps[-2].status is StepStatus.SKIP
    assert report.steps[-1].name == "merged manifest security scan"
    assert report.steps[-1].status is StepStatus.SKIP


def test_verifier_records_command_failures_and_keeps_running(tmp_path: Path) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=failing_runner("pytest"),
        preflight_collector=preflight(True),
    )

    failed = [step for step in report.steps if step.status is StepStatus.FAIL]

    assert not report.ok
    assert failed[0].name == "pytest"
    assert report.steps[-5].name == "android gradle"
    assert report.steps[-4].name == "android APK budget"
    assert report.steps[-3].name == "android local model provider"
    assert report.steps[-2].name == "android TFLite Task Text classifier"
    assert report.steps[-1].name == "merged manifest security scan"


def test_verifier_fails_when_android_apk_budget_fails(tmp_path: Path) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=failing_runner("scripts/verify_android_apk_budget.py"),
        preflight_collector=preflight(True),
    )

    apk_budget_matches = [step for step in report.steps if step.name == "android APK budget"]

    assert len(apk_budget_matches) == 1
    apk_budget = apk_budget_matches[0]
    assert not report.ok
    assert apk_budget.status is StepStatus.FAIL
    assert any(
        step.name == "TFLite Task Text dependency" and step.status is StepStatus.OK
        for step in report.steps
    )
    assert report.steps[-3].name == "android local model provider"
    assert report.steps[-3].status is StepStatus.OK
    assert report.steps[-2].name == "android TFLite Task Text classifier"
    assert report.steps[-2].status is StepStatus.OK
    assert report.steps[-1].name == "merged manifest security scan"
    assert report.steps[-1].status is StepStatus.OK


def test_verifier_fails_when_android_local_model_provider_fails(tmp_path: Path) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=failing_runner(":app:compileModelDebugKotlin"),
        preflight_collector=preflight(True),
    )

    provider_matches = [
        step for step in report.steps if step.name == "android local model provider"
    ]

    assert len(provider_matches) == 1
    assert not report.ok
    assert provider_matches[0].status is StepStatus.FAIL
    assert report.steps[-2].name == "android TFLite Task Text classifier"
    assert report.steps[-2].status is StepStatus.OK
    assert report.steps[-1].name == "merged manifest security scan"
    assert report.steps[-1].status is StepStatus.OK


def test_verifier_fails_when_tflite_task_text_dependency_fails(tmp_path: Path) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=failing_runner("scripts/verify_tflite_task_text_android_dependency.py"),
        preflight_collector=preflight(True),
    )

    dependency_matches = [
        step for step in report.steps if step.name == "TFLite Task Text dependency"
    ]

    assert len(dependency_matches) == 1
    assert not report.ok
    assert dependency_matches[0].status is StepStatus.FAIL
    assert report.steps[-4].name == "android APK budget"
    assert report.steps[-4].status is StepStatus.OK


def test_verifier_fails_when_android_tflite_task_text_classifier_fails(tmp_path: Path) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=failing_runner(":app:assembleModelDebugAndroidTest"),
        preflight_collector=preflight(True),
    )

    classifier_matches = [
        step for step in report.steps if step.name == "android TFLite Task Text classifier"
    ]

    assert len(classifier_matches) == 1
    assert not report.ok
    assert classifier_matches[0].status is StepStatus.FAIL
    assert report.steps[-1].name == "merged manifest security scan"
    assert report.steps[-1].status is StepStatus.OK


def test_render_verification_report_includes_overall_status(tmp_path: Path) -> None:
    report = run_verification(
        root=tmp_path,
        python="python",
        runner=passing_runner([]),
        preflight_collector=preflight(False),
    )

    rendered = render_verification_report(report)

    assert "GOFFY verification" in rendered
    assert "[BLOCKED] android preflight" in rendered
    assert "Overall: FAIL" in rendered
