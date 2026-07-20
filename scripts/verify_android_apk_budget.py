from __future__ import annotations

import argparse
import json
import os
import subprocess
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_APK = (
    ROOT / "android" / "app" / "build" / "outputs" / "apk" / "release" / "app-release-unsigned.apk"
)
DEFAULT_MAX_RELEASE_APK_BYTES = 32 * 1024 * 1024
JSON_SCHEMA_VERSION = "goffy.android-apk-budget.v1"
FORBIDDEN_ENTRY_PATTERNS = (
    ".litertlm",
    "litertlm",
)
DEFAULT_RUNTIME_CLASSPATH_CONFIGURATIONS = (
    "debugRuntimeClasspath",
    "releaseRuntimeClasspath",
)
FORBIDDEN_RUNTIME_DEPENDENCY_PATTERNS = ("com.google.ai.edge.litertlm", "litertlm-android")
DEPENDENCY_REPORT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


CommandRunner = Callable[[Sequence[str], Path, int], CommandResult]


@dataclass(frozen=True)
class RuntimeClasspathCheck:
    configuration: str
    checked: bool
    command: tuple[str, ...] = ()
    forbidden_matches: tuple[str, ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.forbidden_matches

    @classmethod
    def passed(cls, configuration: str = "releaseRuntimeClasspath") -> RuntimeClasspathCheck:
        return cls(configuration=configuration, checked=True)


ReleaseDependencyCheck = RuntimeClasspathCheck


@dataclass(frozen=True)
class AndroidApkBudgetReport:
    apk_path: Path
    max_apk_bytes: int
    apk_bytes: int | None
    forbidden_entries: tuple[str, ...]
    runtime_classpaths: tuple[RuntimeClasspathCheck, ...] = tuple(
        RuntimeClasspathCheck.passed(configuration)
        for configuration in DEFAULT_RUNTIME_CLASSPATH_CONFIGURATIONS
    )
    error: str | None = None
    repo_root: Path = ROOT

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and self.apk_bytes is not None
            and self.apk_bytes <= self.max_apk_bytes
            and not self.forbidden_entries
            and all(check.ok for check in self.runtime_classpaths)
        )

    @property
    def size_ok(self) -> bool:
        return self.apk_bytes is not None and self.apk_bytes <= self.max_apk_bytes


def verify_android_apk_budget(
    *,
    apk_path: Path = DEFAULT_RELEASE_APK,
    max_apk_bytes: int = DEFAULT_MAX_RELEASE_APK_BYTES,
    repo_root: Path = ROOT,
    release_dependencies: ReleaseDependencyCheck | None = None,
    runtime_classpaths: tuple[RuntimeClasspathCheck, ...] | None = None,
) -> AndroidApkBudgetReport:
    dependency_checks = runtime_classpaths or (
        (release_dependencies,)
        if release_dependencies is not None
        else tuple(
            RuntimeClasspathCheck.passed(configuration)
            for configuration in DEFAULT_RUNTIME_CLASSPATH_CONFIGURATIONS
        )
    )
    if max_apk_bytes <= 0:
        return AndroidApkBudgetReport(
            apk_path=apk_path,
            max_apk_bytes=max_apk_bytes,
            apk_bytes=None,
            forbidden_entries=(),
            runtime_classpaths=dependency_checks,
            error="APK byte budget must be positive.",
            repo_root=repo_root,
        )
    if not apk_path.is_file():
        return AndroidApkBudgetReport(
            apk_path=apk_path,
            max_apk_bytes=max_apk_bytes,
            apk_bytes=None,
            forbidden_entries=(),
            runtime_classpaths=dependency_checks,
            error="Release APK is missing; run the Android release build first.",
            repo_root=repo_root,
        )
    try:
        with zipfile.ZipFile(apk_path) as apk:
            entries = tuple(entry.filename for entry in apk.infolist())
    except zipfile.BadZipFile:
        return AndroidApkBudgetReport(
            apk_path=apk_path,
            max_apk_bytes=max_apk_bytes,
            apk_bytes=apk_path.stat().st_size,
            forbidden_entries=(),
            runtime_classpaths=dependency_checks,
            error="Release APK is not a readable ZIP archive.",
            repo_root=repo_root,
        )
    forbidden_entries = tuple(sorted(entry for entry in entries if is_forbidden_apk_entry(entry)))
    return AndroidApkBudgetReport(
        apk_path=apk_path,
        max_apk_bytes=max_apk_bytes,
        apk_bytes=apk_path.stat().st_size,
        forbidden_entries=forbidden_entries,
        runtime_classpaths=dependency_checks,
        repo_root=repo_root,
    )


def is_forbidden_apk_entry(entry_name: str) -> bool:
    normalized = entry_name.replace("\\", "/").lower()
    return any(pattern in normalized for pattern in FORBIDDEN_ENTRY_PATTERNS)


def collect_runtime_classpath_checks(
    *,
    repo_root: Path = ROOT,
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEPENDENCY_REPORT_TIMEOUT_SECONDS,
) -> tuple[RuntimeClasspathCheck, ...]:
    return tuple(
        collect_runtime_classpath_check(
            configuration=configuration,
            repo_root=repo_root,
            runner=runner,
            timeout_seconds=timeout_seconds,
        )
        for configuration in DEFAULT_RUNTIME_CLASSPATH_CONFIGURATIONS
    )


def collect_runtime_classpath_check(
    *,
    configuration: str,
    repo_root: Path = ROOT,
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEPENDENCY_REPORT_TIMEOUT_SECONDS,
) -> RuntimeClasspathCheck:
    command = runtime_classpath_dependency_command(repo_root, configuration)
    wrapper = Path(command[0])
    if not wrapper.is_file():
        return RuntimeClasspathCheck(
            configuration=configuration,
            checked=False,
            command=command,
            error=f"Gradle wrapper is missing; cannot inspect {configuration}.",
        )
    active_runner = runner or default_command_runner
    result = active_runner(command, repo_root, timeout_seconds)
    if result.timed_out:
        return RuntimeClasspathCheck(
            configuration=configuration,
            checked=False,
            command=command,
            error=f"{configuration} dependency report timed out.",
        )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.exit_code != 0:
        return RuntimeClasspathCheck(
            configuration=configuration,
            checked=False,
            command=command,
            error=f"{configuration} dependency report failed.",
        )
    return RuntimeClasspathCheck(
        configuration=configuration,
        checked=True,
        command=command,
        forbidden_matches=find_forbidden_runtime_dependencies(output),
    )


def collect_release_dependency_check(
    *,
    repo_root: Path = ROOT,
    runner: CommandRunner | None = None,
    timeout_seconds: int = DEPENDENCY_REPORT_TIMEOUT_SECONDS,
) -> ReleaseDependencyCheck:
    return collect_runtime_classpath_check(
        configuration="releaseRuntimeClasspath",
        repo_root=repo_root,
        runner=runner,
        timeout_seconds=timeout_seconds,
    )


def runtime_classpath_dependency_command(
    repo_root: Path,
    configuration: str,
) -> tuple[str, ...]:
    wrapper = repo_root / "android" / ("gradlew.bat" if os.name == "nt" else "gradlew")
    return (
        str(wrapper),
        "-p",
        "android",
        ":app:dependencies",
        "--configuration",
        configuration,
        "--no-daemon",
        "--quiet",
    )


def release_dependency_command(repo_root: Path) -> tuple[str, ...]:
    return runtime_classpath_dependency_command(repo_root, "releaseRuntimeClasspath")


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
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def find_forbidden_runtime_dependencies(report_text: str) -> tuple[str, ...]:
    matches = []
    for line in report_text.splitlines():
        normalized = line.lower()
        if any(pattern in normalized for pattern in FORBIDDEN_RUNTIME_DEPENDENCY_PATTERNS):
            matches.append(line.strip()[:240])
    return tuple(dict.fromkeys(matches))


def find_forbidden_release_dependencies(report_text: str) -> tuple[str, ...]:
    return find_forbidden_runtime_dependencies(report_text)


def render_text(report: AndroidApkBudgetReport) -> str:
    lines = ["GOFFY Android APK budget"]
    if report.error is not None:
        lines.append(f"[FAIL] release APK: {report.error}")
    elif report.apk_bytes is None:
        lines.append("[FAIL] release APK: missing size evidence")
    else:
        status = "OK" if report.size_ok else "FAIL"
        lines.append(
            f"[{status}] release APK size: {format_bytes(report.apk_bytes)} / "
            f"{format_bytes(report.max_apk_bytes)}"
        )
    if report.forbidden_entries:
        lines.append("[FAIL] forbidden LiteRT-LM/model payloads:")
        lines.extend(f"       {entry}" for entry in report.forbidden_entries[:20])
        if len(report.forbidden_entries) > 20:
            omitted = len(report.forbidden_entries) - 20
            lines.append(f"       ... {omitted} more entries omitted ...")
    else:
        lines.append("[OK] forbidden LiteRT-LM/model payloads: none")
    for dependency_status in report.runtime_classpaths:
        configuration = dependency_status.configuration
        if dependency_status.error is not None:
            lines.append(f"[FAIL] {configuration}: {dependency_status.error}")
        elif dependency_status.forbidden_matches:
            lines.append(f"[FAIL] {configuration} LiteRT-LM dependencies:")
            lines.extend(f"       {match}" for match in dependency_status.forbidden_matches[:20])
            if len(dependency_status.forbidden_matches) > 20:
                omitted = len(dependency_status.forbidden_matches) - 20
                lines.append(f"       ... {omitted} more matches omitted ...")
        else:
            lines.append(f"[OK] {configuration} LiteRT-LM dependencies: none")
    lines.append("Overall: PASS" if report.ok else "Overall: FAIL")
    return "\n".join(lines)


def render_json(report: AndroidApkBudgetReport) -> str:
    release_status = next(
        (
            check
            for check in report.runtime_classpaths
            if check.configuration == "releaseRuntimeClasspath"
        ),
        RuntimeClasspathCheck.passed("releaseRuntimeClasspath"),
    )
    payload: dict[str, Any] = {
        "schemaVersion": JSON_SCHEMA_VERSION,
        "ok": report.ok,
        "apkPath": safe_path(report.apk_path, report.repo_root),
        "apkBytes": report.apk_bytes,
        "maxApkBytes": report.max_apk_bytes,
        "sizeOk": report.size_ok,
        "forbiddenEntries": list(report.forbidden_entries),
        "runtimeClasspathChecks": [
            {
                "configuration": check.configuration,
                "checked": check.checked,
                "command": list(check.command),
                "forbiddenMatches": list(check.forbidden_matches),
                "error": check.error,
            }
            for check in report.runtime_classpaths
        ],
        "releaseDependencyChecked": release_status.checked,
        "releaseDependencyCommand": list(release_status.command),
        "releaseDependencyForbiddenMatches": list(release_status.forbidden_matches),
        "releaseDependencyError": release_status.error,
        "error": report.error,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def format_bytes(value: int) -> str:
    mib = value / (1024 * 1024)
    return f"{mib:.1f} MiB"


def safe_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return "<external-apk>"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the default GOFFY LITE Android release APK size and "
            "local-model payload boundary."
        ),
    )
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument(
        "--apk",
        default=None,
        help="Release APK path. Defaults to the app release output.",
    )
    parser.add_argument(
        "--max-release-apk-bytes",
        type=int,
        default=DEFAULT_MAX_RELEASE_APK_BYTES,
        help="Maximum allowed release APK size in bytes.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    apk_path = (
        Path(args.apk).resolve() if args.apk else repo_root / DEFAULT_RELEASE_APK.relative_to(ROOT)
    )
    runtime_classpaths = collect_runtime_classpath_checks(repo_root=repo_root)
    report = verify_android_apk_budget(
        apk_path=apk_path,
        max_apk_bytes=args.max_release_apk_bytes,
        repo_root=repo_root,
        runtime_classpaths=runtime_classpaths,
    )
    print(render_json(report) if args.json else render_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
