from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.android_preflight import Check, collect_checks, render_report  # noqa: E402

REPO_OWNED_ANDROID_PREFLIGHT_CHECKS = frozenset({"Gradle wrapper"})
ANDROID_DEPENDENT_STEPS = frozenset(
    {
        "android gradle",
        "android APK budget",
        "android local model provider",
        "merged manifest security scan",
    }
)


class StepStatus(StrEnum):
    OK = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    SKIP = "SKIP"


@dataclass(frozen=True)
class StepResult:
    name: str
    status: StepStatus
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class VerificationReport:
    steps: tuple[StepResult, ...]
    allow_missing_android: bool

    @property
    def ok(self) -> bool:
        android_blocked = any(
            step.name == "android preflight" and step.status is StepStatus.BLOCKED
            for step in self.steps
        )
        for step in self.steps:
            if step.status is StepStatus.FAIL:
                return False
            if step.status is StepStatus.BLOCKED and not self.allow_missing_android:
                return False
            if step.status is StepStatus.SKIP:
                if step.name in ANDROID_DEPENDENT_STEPS:
                    if not (self.allow_missing_android and android_blocked):
                        return False
                else:
                    return False
        return True


CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
PreflightCollector = Callable[[Path], Sequence[Check]]


def default_runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603,S607
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def python_steps(python: str) -> list[tuple[str, tuple[str, ...]]]:
    return [
        ("ruff format", (python, "-m", "ruff", "format", "--check", ".")),
        ("ruff check", (python, "-m", "ruff", "check", ".")),
        ("mypy", (python, "-m", "mypy", "hub/src", "protocol/python")),
        ("pytest", (python, "-m", "pytest", "-q")),
        ("security scan", (python, "scripts/security_scan.py")),
        ("package build", (python, "-m", "build")),
        ("pairing smoke", (python, "scripts/verify_pairing_flow.py")),
    ]


def merged_manifest_security_command(python: str) -> tuple[str, ...]:
    return (python, "scripts/security_scan.py", "--require-merged-manifests")


def android_apk_budget_command(python: str) -> tuple[str, ...]:
    return (python, "scripts/verify_android_apk_budget.py")


def android_local_model_provider_command(root: Path) -> tuple[str, ...]:
    wrapper = root / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    return (
        str(wrapper),
        "-p",
        "android",
        ":app:compileModelDebugKotlin",
        "--no-daemon",
    )


def android_gradle_command(root: Path) -> tuple[str, ...]:
    wrapper = root / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    return (
        str(wrapper),
        "-p",
        "android",
        ":app:lintDebug",
        ":app:testDebugUnitTest",
        ":app:assembleDebugAndroidTest",
        ":app:assembleDebug",
        ":app:assembleRelease",
        "--no-daemon",
    )


def run_command_step(
    name: str,
    command: Sequence[str],
    root: Path,
    runner: CommandRunner,
) -> StepResult:
    completed = runner(command, root)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    return StepResult(
        name=name,
        status=StepStatus.OK if completed.returncode == 0 else StepStatus.FAIL,
        command=tuple(command),
        exit_code=completed.returncode,
        detail=tail(output),
    )


def android_preflight_step(
    root: Path,
    preflight_collector: PreflightCollector,
) -> tuple[StepResult, bool]:
    checks = tuple(preflight_collector(root))
    report = render_report(checks)
    ok = all(check.ok for check in checks)
    repo_owned_failure = any(
        check.name in REPO_OWNED_ANDROID_PREFLIGHT_CHECKS and not check.ok for check in checks
    )
    status = StepStatus.OK if ok else StepStatus.FAIL if repo_owned_failure else StepStatus.BLOCKED
    return (
        StepResult(
            name="android preflight",
            status=status,
            command=("python", "scripts/android_preflight.py"),
            exit_code=0 if ok else 1,
            detail=report,
        ),
        ok,
    )


def run_verification(
    *,
    root: Path = ROOT,
    python: str = sys.executable,
    runner: CommandRunner = default_runner,
    preflight_collector: PreflightCollector = lambda root: collect_checks(root=root),
    allow_missing_android: bool = False,
    skip_android_gradle: bool = False,
    fail_fast: bool = False,
) -> VerificationReport:
    results: list[StepResult] = []
    for name, command in python_steps(python):
        result = run_command_step(name, command, root, runner)
        results.append(result)
        if fail_fast and result.status is StepStatus.FAIL:
            return VerificationReport(tuple(results), allow_missing_android)

    preflight_result, android_ready = android_preflight_step(root, preflight_collector)
    results.append(preflight_result)
    if fail_fast and preflight_result.status is StepStatus.BLOCKED and not allow_missing_android:
        return VerificationReport(tuple(results), allow_missing_android)
    if fail_fast and preflight_result.status is StepStatus.FAIL:
        return VerificationReport(tuple(results), allow_missing_android)

    if skip_android_gradle:
        results.append(
            StepResult(
                name="android gradle",
                status=StepStatus.SKIP,
                detail="Skipped by --skip-android-gradle.",
            )
        )
        results.append(
            StepResult(
                name="android APK budget",
                status=StepStatus.SKIP,
                command=android_apk_budget_command(python),
                detail="Skipped because Android Gradle did not run.",
            )
        )
        results.append(
            StepResult(
                name="android local model provider",
                status=StepStatus.SKIP,
                command=android_local_model_provider_command(root),
                detail="Skipped because Android Gradle did not run.",
            )
        )
        results.append(
            StepResult(
                name="merged manifest security scan",
                status=StepStatus.SKIP,
                command=merged_manifest_security_command(python),
                detail="Skipped because Android Gradle did not run.",
            )
        )
    elif android_ready:
        result = run_command_step(
            "android gradle",
            android_gradle_command(root),
            root,
            runner,
        )
        results.append(result)
        if result.status is StepStatus.OK:
            results.append(
                run_command_step(
                    "android APK budget",
                    android_apk_budget_command(python),
                    root,
                    runner,
                )
            )
            results.append(
                run_command_step(
                    "android local model provider",
                    android_local_model_provider_command(root),
                    root,
                    runner,
                )
            )
            results.append(
                run_command_step(
                    "merged manifest security scan",
                    merged_manifest_security_command(python),
                    root,
                    runner,
                )
            )
        else:
            results.append(
                StepResult(
                    name="android APK budget",
                    status=StepStatus.SKIP,
                    command=android_apk_budget_command(python),
                    detail="Skipped because Android Gradle did not complete successfully.",
                )
            )
            results.append(
                StepResult(
                    name="android local model provider",
                    status=StepStatus.SKIP,
                    command=android_local_model_provider_command(root),
                    detail="Skipped because Android Gradle did not complete successfully.",
                )
            )
            results.append(
                StepResult(
                    name="merged manifest security scan",
                    status=StepStatus.SKIP,
                    command=merged_manifest_security_command(python),
                    detail="Skipped because Android Gradle did not complete successfully.",
                )
            )
    else:
        results.append(
            StepResult(
                name="android gradle",
                status=StepStatus.SKIP,
                command=android_gradle_command(root),
                detail="Skipped because Android preflight did not pass.",
            )
        )
        results.append(
            StepResult(
                name="android APK budget",
                status=StepStatus.SKIP,
                command=android_apk_budget_command(python),
                detail="Skipped because Android Gradle did not run.",
            )
        )
        results.append(
            StepResult(
                name="android local model provider",
                status=StepStatus.SKIP,
                command=android_local_model_provider_command(root),
                detail="Skipped because Android Gradle did not run.",
            )
        )
        results.append(
            StepResult(
                name="merged manifest security scan",
                status=StepStatus.SKIP,
                command=merged_manifest_security_command(python),
                detail="Skipped because Android Gradle did not run.",
            )
        )

    return VerificationReport(tuple(results), allow_missing_android)


def render_verification_report(report: VerificationReport) -> str:
    lines = ["GOFFY verification"]
    for step in report.steps:
        lines.append(f"[{step.status}] {step.name}")
        if step.command:
            lines.append(f"       command: {format_command(step.command)}")
        if step.exit_code is not None:
            lines.append(f"       exit: {step.exit_code}")
        if step.detail:
            for line in step.detail.splitlines():
                lines.append(f"       {line}")
    lines.append("Overall: PASS" if report.ok else "Overall: FAIL")
    return "\n".join(lines)


def format_command(command: Sequence[str]) -> str:
    return " ".join(command)


def tail(text: str, max_lines: int = 24) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    omitted = len(lines) - max_lines
    return "\n".join([f"... {omitted} earlier lines omitted ...", *lines[-max_lines:]])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--allow-missing-android",
        action="store_true",
        help="Return success when only Android preflight/Gradle is blocked by missing local tools.",
    )
    parser.add_argument(
        "--skip-android-gradle",
        action="store_true",
        help=(
            "Skip Gradle after preflight; overall success still requires "
            "--allow-missing-android and a blocked Android preflight."
        ),
    )
    parser.add_argument("--fail-fast", action="store_true")
    args = parser.parse_args(argv)

    report = run_verification(
        root=Path(args.repo_root).resolve(),
        python=args.python,
        allow_missing_android=args.allow_missing_android,
        skip_android_gradle=args.skip_android_gradle,
        fail_fast=args.fail_fast,
    )
    print(render_verification_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
