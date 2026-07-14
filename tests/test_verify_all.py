from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from scripts.android_preflight import Check
from scripts.verify_all import (
    CommandRunner,
    PreflightCollector,
    StepStatus,
    android_gradle_command,
    merged_manifest_security_command,
    render_verification_report,
    run_verification,
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
    assert report.steps[-2].name == "android gradle"
    assert report.steps[-2].status is StepStatus.SKIP
    assert report.steps[-1].name == "merged manifest security scan"
    assert report.steps[-1].status is StepStatus.SKIP
    assert all(":app:testDebugUnitTest" not in command for command in seen)


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
    assert seen[-2] == android_gradle_command(tmp_path)
    assert ":app:lintDebug" in seen[-2]
    assert ":app:assembleRelease" in seen[-2]
    assert seen[-1] == merged_manifest_security_command("python")


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
    assert report.steps[-2].name == "android gradle"
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
    assert report.steps[-2].name == "android gradle"
    assert report.steps[-1].name == "merged manifest security scan"


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
