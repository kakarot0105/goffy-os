from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
GROUP = "com.google.ai.edge.litertlm"
ARTIFACT = "litertlm-android"
GOOGLE_MAVEN_BASE = "https://dl.google.com/dl/android/maven2"
METADATA_PATH = "com/google/ai/edge/litertlm/litertlm-android/maven-metadata.xml"
PINNED_LITERTLM_ANDROID_VERSION = "0.14.0"
DEFAULT_AGP_VERSION = "9.2.0"
DEFAULT_COMPILE_SDK = 36
DEFAULT_MIN_SDK = 26
DEFAULT_TIMEOUT_SECONDS = 300

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
OTHER_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ABSOLUTE_POSIX_PATH = re.compile(r"(?<![:>/\w])/(?!/|\s)(?:[^;\n\r,)'\"\s]+)")
ABSOLUTE_WINDOWS_PATH = re.compile(r"(?<![\w<])(?:[A-Za-z]:\\[^;\n\r,)'\"\s]+)")
QUOTED_POSIX_PATH = re.compile(r"([\"'])(/(?!/)[^\"'\n\r]+)(\1)")
QUOTED_WINDOWS_PATH = re.compile(r"([\"'])([A-Za-z]:\\[^\"'\n\r]+)(\1)")
DYNAMIC_VERSION = re.compile(
    rf"{re.escape(GROUP)}:{re.escape(ARTIFACT)}:(?:latest\.[A-Za-z]+|[^\"')\s]*\+)",
)


class ProbeMode(StrEnum):
    METADATA = "metadata"
    RESOLVE = "resolve"
    BUILD = "build"


class ProbeStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - status label, not a credential
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class MetadataReadError(Exception):
    pass


class PinnedVersionError(ValueError):
    pass


@dataclass(frozen=True)
class MavenMetadata:
    latest: str | None
    release: str | None
    versions: tuple[str, ...]
    last_updated: str | None


@dataclass(frozen=True)
class CommandEvidence:
    status: ProbeStatus
    command: tuple[str, ...]
    exit_code: int | None
    detail: str


@dataclass(frozen=True)
class LiteRtLmDependencyReport:
    status: ProbeStatus
    mode: ProbeMode
    coordinate: str
    selected_version: str | None
    maven_latest: str | None
    maven_release: str | None
    maven_last_updated: str | None
    dynamic_repo_usages: tuple[str, ...]
    java: CommandEvidence | None
    gradle: CommandEvidence | None
    gradle_probe: CommandEvidence | None
    recommendation: str


CommandRunner = Callable[
    [Sequence[str], Path, int],
    subprocess.CompletedProcess[str],
]
Fetcher = Callable[[str, int], str]


def default_fetcher(url: str, timeout_seconds: int) -> str:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
        content = response.read()
        if not isinstance(content, bytes):
            raise MetadataReadError("Maven metadata response was not bytes.")
        return content.decode("utf-8", errors="replace")


def default_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )


def metadata_url(base_url: str = GOOGLE_MAVEN_BASE) -> str:
    return f"{base_url.rstrip('/')}/{METADATA_PATH}"


def parse_maven_metadata(xml_text: str) -> MavenMetadata:
    if len(xml_text) > 100_000:
        raise MetadataReadError("Maven metadata document is unexpectedly large.")
    versioning = extract_tag_body(xml_text, "versioning")
    if versioning is None:
        return MavenMetadata(latest=None, release=None, versions=(), last_updated=None)

    versions_parent = extract_tag_body(versioning, "versions")
    versions = tuple(extract_repeated_tag_values(versions_parent or "", "version"))
    return MavenMetadata(
        latest=extract_tag_body(versioning, "latest"),
        release=extract_tag_body(versioning, "release"),
        versions=versions,
        last_updated=extract_tag_body(versioning, "lastUpdated"),
    )


def extract_tag_body(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(?P<value>.*?)</{tag}>", text, flags=re.DOTALL)
    if match is None:
        return None
    value = match.group("value").strip()
    return value or None


def extract_repeated_tag_values(text: str, tag: str) -> tuple[str, ...]:
    values: list[str] = []
    for match in re.finditer(rf"<{tag}>(?P<value>[^<]*)</{tag}>", text):
        value = match.group("value").strip()
        if value:
            values.append(value)
    return tuple(values)


def select_pinned_version(requested_version: str | None, metadata: MavenMetadata) -> str:
    selected = (
        PINNED_LITERTLM_ANDROID_VERSION if requested_version is None else requested_version.strip()
    )
    if not selected:
        raise PinnedVersionError("Google Maven metadata does not declare a release version.")
    if selected.startswith("latest.") or "+" in selected:
        raise PinnedVersionError("LiteRT-LM Android dependency must use an exact pinned version.")
    if metadata.versions and selected not in metadata.versions:
        raise PinnedVersionError(f"Version {selected} is not present in Google Maven metadata.")
    return selected


def find_dynamic_litertlm_versions(root: Path) -> tuple[str, ...]:
    android_root = root / "android"
    if not android_root.exists():
        return ()

    findings: list[str] = []
    candidates = list(android_root.rglob("*.gradle")) + list(android_root.rglob("*.gradle.kts"))
    candidates.extend(root.rglob("libs.versions.toml"))
    for path in sorted(set(candidates)):
        if any(part in {".gradle", "build", ".git"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.name == "libs.versions.toml":
            findings.extend(find_dynamic_litertlm_catalog_versions(path, root, text))
        for line_number, line in enumerate(text.splitlines(), start=1):
            if DYNAMIC_VERSION.search(line):
                findings.append(f"{redact_path(path, root)}:{line_number}")
    return tuple(dict.fromkeys(findings))


def find_dynamic_litertlm_catalog_versions(path: Path, root: Path, text: str) -> tuple[str, ...]:
    try:
        catalog = cast("dict[str, object]", tomllib.loads(text))
    except tomllib.TOMLDecodeError:
        return ()

    versions = mapping_or_empty(catalog.get("versions"))
    libraries = mapping_or_empty(catalog.get("libraries"))
    findings: list[str] = []
    for alias, entry in libraries.items():
        if not is_litertlm_catalog_library(entry):
            continue

        direct_version = catalog_library_direct_version(entry)
        if is_dynamic_gradle_version(direct_version):
            findings.append(f"{redact_path(path, root)}:{toml_key_line(text, alias)}")

        version_ref = catalog_library_version_ref(entry)
        if version_ref is None:
            continue
        referenced_version = versions.get(version_ref)
        if is_dynamic_gradle_version(referenced_version):
            findings.append(f"{redact_path(path, root)}:{toml_key_line(text, version_ref)}")

    return tuple(dict.fromkeys(findings))


def mapping_or_empty(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast("dict[str, object]", value)
    return {}


def is_litertlm_catalog_library(entry: object) -> bool:
    if isinstance(entry, str):
        return entry.startswith(f"{GROUP}:{ARTIFACT}:")
    if not isinstance(entry, dict):
        return False

    values = cast("dict[str, object]", entry)
    module = values.get("module")
    if module == f"{GROUP}:{ARTIFACT}" or (
        isinstance(module, str) and module.startswith(f"{GROUP}:{ARTIFACT}:")
    ):
        return True
    return values.get("group") == GROUP and values.get("name") == ARTIFACT


def catalog_library_direct_version(entry: object) -> object | None:
    if isinstance(entry, str):
        parts = entry.split(":")
        return parts[2] if len(parts) >= 3 else None
    if not isinstance(entry, dict):
        return None

    values = cast("dict[str, object]", entry)
    version = values.get("version")
    if isinstance(version, dict) and "ref" in version:
        return None
    if version is not None:
        return version

    module = values.get("module")
    if isinstance(module, str):
        parts = module.split(":")
        return parts[2] if len(parts) >= 3 else None
    return None


def catalog_library_version_ref(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return None
    values = cast("dict[str, object]", entry)
    version = values.get("version")
    if isinstance(version, dict):
        ref = version.get("ref")
        return ref if isinstance(ref, str) else None
    return None


def is_dynamic_gradle_version(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith("latest.") or "+" in value
    if isinstance(value, dict):
        values = cast("dict[str, object]", value)
        return any(
            is_dynamic_gradle_version(values.get(key)) for key in ("require", "strictly", "prefer")
        )
    return False


def toml_key_line(text: str, key: str) -> int:
    quoted = re.escape(f'"{key}"')
    bare = re.escape(key)
    pattern = re.compile(rf"^\s*(?:{bare}|{quoted})\s*=", flags=re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        return 1
    return text[: match.start()].count("\n") + 1


def run_command(
    command: Sequence[str],
    cwd: Path,
    *,
    root: Path,
    runner: CommandRunner,
    timeout_seconds: int,
    redaction_roots: Sequence[Path] = (),
) -> CommandEvidence:
    try:
        completed = runner(command, cwd, timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return CommandEvidence(
            status=ProbeStatus.BLOCKED,
            command=redact_command(command, root, redaction_roots),
            exit_code=None,
            detail=f"command timed out after {exc.timeout} seconds",
        )
    except OSError as exc:
        return CommandEvidence(
            status=ProbeStatus.BLOCKED,
            command=redact_command(command, root, redaction_roots),
            exit_code=None,
            detail=sanitize_detail(str(exc), root, redaction_roots),
        )

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return CommandEvidence(
        status=ProbeStatus.PASS if completed.returncode == 0 else ProbeStatus.FAIL,
        command=redact_command(command, root, redaction_roots),
        exit_code=completed.returncode,
        detail=tail(sanitize_detail(output, root, redaction_roots)),
    )


def create_probe_project(
    root: Path,
    *,
    selected_version: str,
    agp_version: str,
    compile_sdk: int,
    min_sdk: int,
) -> Path:
    probe_root = root
    (probe_root / "probe" / "src" / "main").mkdir(parents=True)
    (probe_root / "settings.gradle.kts").write_text(
        """
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "goffy-litertlm-compat-probe"
include(":probe")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (probe_root / "build.gradle.kts").write_text(
        f"""
plugins {{
    id("com.android.application") version "{agp_version}" apply false
}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (probe_root / "probe" / "build.gradle.kts").write_text(
        f"""
plugins {{
    id("com.android.application")
}}

android {{
    namespace = "dev.goffy.litertlmprobe"
    compileSdk = {compile_sdk}

    defaultConfig {{
        applicationId = "dev.goffy.litertlmprobe"
        minSdk = {min_sdk}
        targetSdk = {compile_sdk}
        versionCode = 1
        versionName = "0.1.0"
    }}

    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}
}}

dependencies {{
    implementation("{GROUP}:{ARTIFACT}:{selected_version}")
}}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (probe_root / "probe" / "src" / "main" / "AndroidManifest.xml").write_text(
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" />\n',
        encoding="utf-8",
    )
    return probe_root


def verify_litertlm_android_dependency(
    *,
    root: Path = ROOT,
    requested_version: str | None = None,
    mode: ProbeMode = ProbeMode.RESOLVE,
    fetcher: Fetcher = default_fetcher,
    runner: CommandRunner = default_runner,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    agp_version: str = DEFAULT_AGP_VERSION,
    compile_sdk: int = DEFAULT_COMPILE_SDK,
    min_sdk: int = DEFAULT_MIN_SDK,
) -> LiteRtLmDependencyReport:
    dynamic_usages = find_dynamic_litertlm_versions(root)
    if dynamic_usages:
        return LiteRtLmDependencyReport(
            status=ProbeStatus.FAIL,
            mode=mode,
            coordinate=f"{GROUP}:{ARTIFACT}",
            selected_version=None,
            maven_latest=None,
            maven_release=None,
            maven_last_updated=None,
            dynamic_repo_usages=dynamic_usages,
            java=None,
            gradle=None,
            gradle_probe=None,
            recommendation="Replace dynamic LiteRT-LM Android Gradle versions with an exact pin.",
        )

    metadata: MavenMetadata | None = None
    selected_version: str | None = None

    try:
        metadata = parse_maven_metadata(fetcher(metadata_url(), min(timeout_seconds, 30)))
        if not metadata.versions:
            raise MetadataReadError("Google Maven metadata does not declare any versions.")
        selected_version = select_pinned_version(requested_version, metadata)
    except (
        MetadataReadError,
        PinnedVersionError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as exc:
        status = ProbeStatus.FAIL if isinstance(exc, PinnedVersionError) else ProbeStatus.BLOCKED
        return LiteRtLmDependencyReport(
            status=status,
            mode=mode,
            coordinate=f"{GROUP}:{ARTIFACT}",
            selected_version=None,
            maven_latest=metadata.latest if metadata else None,
            maven_release=metadata.release if metadata else None,
            maven_last_updated=metadata.last_updated if metadata else None,
            dynamic_repo_usages=dynamic_usages,
            java=None,
            gradle=None,
            gradle_probe=None,
            recommendation=sanitize_detail(str(exc), root, ()),
        )

    java = run_command(
        ("java", "-version"),
        root,
        root=root,
        runner=runner,
        timeout_seconds=30,
    )
    gradle = run_command(
        android_gradle_version_command(root),
        root,
        root=root,
        runner=runner,
        timeout_seconds=60,
    )

    gradle_probe: CommandEvidence | None = None
    if mode is not ProbeMode.METADATA:
        with tempfile.TemporaryDirectory(prefix="goffy-litertlm-probe-") as temp_dir:
            probe_root = create_probe_project(
                Path(temp_dir),
                selected_version=selected_version,
                agp_version=agp_version,
                compile_sdk=compile_sdk,
                min_sdk=min_sdk,
            )
            command: tuple[str, ...]
            if mode is ProbeMode.RESOLVE:
                command = (
                    android_gradle_wrapper_path(root),
                    "-p",
                    str(probe_root),
                    ":probe:dependencies",
                    "--configuration",
                    "debugRuntimeClasspath",
                    "--no-daemon",
                )
            else:
                command = (
                    android_gradle_wrapper_path(root),
                    "-p",
                    str(probe_root),
                    ":probe:assembleDebug",
                    "--no-daemon",
                )
            gradle_probe = run_command(
                command,
                root,
                root=root,
                runner=runner,
                timeout_seconds=timeout_seconds,
                redaction_roots=(probe_root,),
            )

    status = combine_statuses(java, gradle, gradle_probe)
    recommendation = recommendation_for(status, mode, selected_version)
    return LiteRtLmDependencyReport(
        status=status,
        mode=mode,
        coordinate=f"{GROUP}:{ARTIFACT}:{selected_version}",
        selected_version=selected_version,
        maven_latest=metadata.latest,
        maven_release=metadata.release,
        maven_last_updated=metadata.last_updated,
        dynamic_repo_usages=dynamic_usages,
        java=java,
        gradle=gradle,
        gradle_probe=gradle_probe,
        recommendation=recommendation,
    )


def android_gradle_wrapper_path(root: Path) -> str:
    wrapper = root / "android" / ("gradlew.bat" if sys.platform.startswith("win") else "gradlew")
    return str(wrapper)


def android_gradle_version_command(root: Path) -> tuple[str, ...]:
    return (android_gradle_wrapper_path(root), "-p", "android", "--version", "--no-daemon")


def combine_statuses(*evidence: CommandEvidence | None) -> ProbeStatus:
    statuses = tuple(item.status for item in evidence if item is not None)
    if any(status is ProbeStatus.FAIL for status in statuses):
        return ProbeStatus.FAIL
    if any(status is ProbeStatus.BLOCKED for status in statuses):
        return ProbeStatus.BLOCKED
    return ProbeStatus.PASS


def recommendation_for(status: ProbeStatus, mode: ProbeMode, selected_version: str) -> str:
    if status is ProbeStatus.PASS and mode is ProbeMode.BUILD:
        return (
            f"{GROUP}:{ARTIFACT}:{selected_version} builds in the isolated Android probe; "
            "next gate is a real Moto G benchmark with one tiny text model."
        )
    if status is ProbeStatus.PASS:
        return (
            f"{GROUP}:{ARTIFACT}:{selected_version} is resolvable with the local toolchain; "
            "run this script with --mode build before wiring app runtime code."
        )
    if status is ProbeStatus.BLOCKED:
        return "Dependency compatibility could not be proven because the probe was blocked."
    return "Do not add LiteRT-LM to the Android app until the failing probe is fixed."


def redact_command(
    command: Sequence[str],
    root: Path,
    redaction_roots: Sequence[Path],
) -> tuple[str, ...]:
    return tuple(redact_path_text(str(part), root, redaction_roots) for part in command)


def sanitize_detail(text: str, root: Path, redaction_roots: Sequence[Path]) -> str:
    without_ansi = ANSI_ESCAPE.sub("", text)
    without_control = OTHER_CONTROL.sub("", without_ansi)
    return redact_path_text(without_control, root, redaction_roots)


def redact_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return "<path>"


def redact_path_text(text: str, root: Path, redaction_roots: Sequence[Path]) -> str:
    redacted = text.replace(str(root), "<repo>")
    for redaction_root in redaction_roots:
        redacted = redacted.replace(str(redaction_root), "<probe>")
    redacted = QUOTED_WINDOWS_PATH.sub(r"\1<path>\3", redacted)
    redacted = QUOTED_POSIX_PATH.sub(r"\1<path>\3", redacted)
    redacted = ABSOLUTE_WINDOWS_PATH.sub("<path>", redacted)
    return ABSOLUTE_POSIX_PATH.sub("<path>", redacted)


def tail(text: str, *, max_lines: int = 40, max_chars: int = 6000) -> str:
    lines = text.strip().splitlines()
    trimmed = "\n".join(lines[-max_lines:])
    return trimmed[-max_chars:]


def render_text_report(report: LiteRtLmDependencyReport) -> str:
    lines = [
        "GOFFY LiteRT-LM Android dependency probe",
        f"[{report.status}] {report.coordinate}",
        f"mode: {report.mode}",
        f"maven release: {report.maven_release or 'unknown'}",
        f"maven latest: {report.maven_latest or 'unknown'}",
        f"maven lastUpdated: {report.maven_last_updated or 'unknown'}",
    ]
    if report.dynamic_repo_usages:
        lines.append("dynamic repo usages:")
        lines.extend(f"- {usage}" for usage in report.dynamic_repo_usages)
    for label, evidence in (
        ("java", report.java),
        ("gradle", report.gradle),
        ("gradle probe", report.gradle_probe),
    ):
        if evidence is None:
            continue
        lines.append(f"[{evidence.status}] {label}")
        lines.append(f"       command: {' '.join(evidence.command)}")
        if evidence.exit_code is not None:
            lines.append(f"       exit_code: {evidence.exit_code}")
        if evidence.detail:
            lines.append(f"       detail: {evidence.detail}")
    lines.append(f"recommendation: {report.recommendation}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the pinned LiteRT-LM Android dependency path before app integration.",
    )
    parser.add_argument(
        "--version",
        help=(
            "Exact LiteRT-LM Android version to verify. Defaults to the committed "
            f"GOFFY pin {PINNED_LITERTLM_ANDROID_VERSION}."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in ProbeMode],
        default=ProbeMode.RESOLVE.value,
        help="Probe depth: metadata, resolve, or build.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout for the Gradle probe.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = verify_litertlm_android_dependency(
        requested_version=args.version,
        mode=ProbeMode(args.mode),
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps(asdict(report), indent=2))
    else:
        print(render_text_report(report))
    return 0 if report.status is ProbeStatus.PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
