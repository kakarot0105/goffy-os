from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.error
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
GROUP = "org.tensorflow"
ARTIFACT = "tensorflow-lite-task-text"
MAVEN_CENTRAL_BASE = "https://repo1.maven.org/maven2"
METADATA_PATH = "org/tensorflow/tensorflow-lite-task-text/maven-metadata.xml"
PINNED_TFLITE_TASK_TEXT_VERSION = "0.4.4"
DEFAULT_AGP_VERSION = "9.2.0"
DEFAULT_COMPILE_SDK = 36
DEFAULT_MIN_SDK = 26
DEFAULT_TIMEOUT_SECONDS = 300

ALLOWED_ANDROID_CONFIGURATIONS = frozenset({"modelDebugImplementation"})
DYNAMIC_VERSION = re.compile(
    rf"{re.escape(GROUP)}:{re.escape(ARTIFACT)}:(?:latest\.[A-Za-z]+|[^\"')\s]*\+)",
)

if __package__ in {None, ""} and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_litertlm_android_dependency import (  # noqa: E402
    CommandEvidence,
    CommandRunner,
    Fetcher,
    MavenMetadata,
    MetadataReadError,
    PinnedVersionError,
    ProbeMode,
    ProbeStatus,
    android_gradle_version_command,
    android_gradle_wrapper_path,
    catalog_library_direct_version,
    catalog_library_version_ref,
    combine_statuses,
    default_fetcher,
    default_runner,
    is_dynamic_gradle_version,
    mapping_or_empty,
    parse_maven_metadata,
    redact_path,
    run_command,
    sanitize_detail,
    toml_key_line,
)


@dataclass(frozen=True)
class TfliteTaskTextDependencyReport:
    status: ProbeStatus
    mode: ProbeMode
    coordinate: str
    selected_version: str | None
    maven_latest: str | None
    maven_release: str | None
    maven_last_updated: str | None
    dynamic_repo_usages: tuple[str, ...]
    default_runtime_usages: tuple[str, ...]
    java: CommandEvidence | None
    gradle: CommandEvidence | None
    gradle_probe: CommandEvidence | None
    recommendation: str


def metadata_url(base_url: str = MAVEN_CENTRAL_BASE) -> str:
    return f"{base_url.rstrip('/')}/{METADATA_PATH}"


def select_pinned_version(requested_version: str | None, metadata: MavenMetadata) -> str:
    selected = (
        PINNED_TFLITE_TASK_TEXT_VERSION if requested_version is None else requested_version.strip()
    )
    if not selected:
        raise PinnedVersionError("Maven metadata does not declare a release version.")
    if selected.startswith("latest.") or "+" in selected:
        raise PinnedVersionError("TensorFlow Lite Task Text must use an exact pinned version.")
    if metadata.versions and selected not in metadata.versions:
        raise PinnedVersionError(f"Version {selected} is not present in Maven metadata.")
    return selected


def find_tflite_task_text_repo_usages(root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    android_root = root / "android"
    if not android_root.exists():
        return (), ()

    dynamic_findings: list[str] = []
    default_runtime_findings: list[str] = []
    catalog_aliases: set[str] = set()
    catalog_paths = tuple(sorted(root.rglob("libs.versions.toml")))
    for path in catalog_paths:
        if is_ignored_gradle_path(path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        aliases, dynamic_alias_findings = find_catalog_tflite_task_text_aliases(path, root, text)
        catalog_aliases.update(aliases)
        dynamic_findings.extend(dynamic_alias_findings)

    candidates = list(android_root.rglob("*.gradle")) + list(android_root.rglob("*.gradle.kts"))
    for path in sorted(set(candidates)):
        if is_ignored_gradle_path(path):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if DYNAMIC_VERSION.search(line):
                dynamic_findings.append(f"{redact_path(path, root)}:{line_number}")
            if is_default_runtime_dependency_line(line, catalog_aliases):
                default_runtime_findings.append(f"{redact_path(path, root)}:{line_number}")
    return tuple(dict.fromkeys(dynamic_findings)), tuple(dict.fromkeys(default_runtime_findings))


def find_catalog_tflite_task_text_aliases(
    path: Path,
    root: Path,
    text: str,
) -> tuple[set[str], tuple[str, ...]]:
    try:
        import tomllib

        catalog = cast("dict[str, object]", tomllib.loads(text))
    except tomllib.TOMLDecodeError:
        return set(), ()

    versions = mapping_or_empty(catalog.get("versions"))
    libraries = mapping_or_empty(catalog.get("libraries"))
    aliases: set[str] = set()
    dynamic_findings: list[str] = []
    for alias, entry in libraries.items():
        if not is_tflite_task_text_catalog_library(entry):
            continue
        aliases.update(catalog_accessor_names(alias))

        direct_version = catalog_library_direct_version(entry)
        if is_dynamic_gradle_version(direct_version):
            dynamic_findings.append(f"{redact_path(path, root)}:{toml_key_line(text, alias)}")

        version_ref = catalog_library_version_ref(entry)
        if version_ref is None:
            continue
        referenced_version = versions.get(version_ref)
        if is_dynamic_gradle_version(referenced_version):
            dynamic_findings.append(f"{redact_path(path, root)}:{toml_key_line(text, version_ref)}")

    return aliases, tuple(dict.fromkeys(dynamic_findings))


def is_tflite_task_text_catalog_library(entry: object) -> bool:
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


def catalog_accessor_names(alias: str) -> set[str]:
    return {
        alias,
        alias.replace("-", "."),
        alias.replace("_", "."),
        alias.replace("-", "_"),
        alias.replace("_", "-"),
    }


def is_default_runtime_dependency_line(line: str, catalog_aliases: set[str]) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("//"):
        return False
    if f"{GROUP}:{ARTIFACT}:" not in stripped and not uses_tflite_task_text_alias(
        stripped,
        catalog_aliases,
    ):
        return False

    configuration = gradle_dependency_configuration(stripped)
    return configuration is not None and configuration not in ALLOWED_ANDROID_CONFIGURATIONS


def uses_tflite_task_text_alias(line: str, catalog_aliases: set[str]) -> bool:
    return any(f"libs.{alias}" in line for alias in catalog_aliases)


def gradle_dependency_configuration(line: str) -> str | None:
    add_match = re.match(
        r"""add\(\s*["'](?P<configuration>[A-Za-z][A-Za-z0-9_]*)["']\s*,""",
        line,
    )
    if add_match is not None:
        return add_match.group("configuration")

    direct = re.match(r"(?P<configuration>[A-Za-z][A-Za-z0-9_]*)\s*\(", line)
    if direct is not None:
        return direct.group("configuration")

    groovy_direct = re.match(
        r"""(?P<configuration>[A-Za-z][A-Za-z0-9_]*)\s+["']""",
        line,
    )
    if groovy_direct is not None:
        return groovy_direct.group("configuration")
    return None


def is_ignored_gradle_path(path: Path) -> bool:
    return any(part in {".gradle", "build", ".git"} for part in path.parts)


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

rootProject.name = "goffy-tflite-task-text-compat-probe"
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
    namespace = "dev.goffy.tflitetextprobe"
    compileSdk = {compile_sdk}

    defaultConfig {{
        applicationId = "dev.goffy.tflitetextprobe"
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


def verify_tflite_task_text_android_dependency(
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
) -> TfliteTaskTextDependencyReport:
    dynamic_usages, default_runtime_usages = find_tflite_task_text_repo_usages(root)
    if dynamic_usages or default_runtime_usages:
        return TfliteTaskTextDependencyReport(
            status=ProbeStatus.FAIL,
            mode=mode,
            coordinate=f"{GROUP}:{ARTIFACT}",
            selected_version=None,
            maven_latest=None,
            maven_release=None,
            maven_last_updated=None,
            dynamic_repo_usages=dynamic_usages,
            default_runtime_usages=default_runtime_usages,
            java=None,
            gradle=None,
            gradle_probe=None,
            recommendation=repo_usage_recommendation(dynamic_usages, default_runtime_usages),
        )

    metadata: MavenMetadata | None = None
    selected_version: str | None = None
    try:
        metadata = parse_maven_metadata(fetcher(metadata_url(), min(timeout_seconds, 30)))
        if not metadata.versions:
            raise MetadataReadError("Maven metadata does not declare any versions.")
        selected_version = select_pinned_version(requested_version, metadata)
    except (
        MetadataReadError,
        PinnedVersionError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as exc:
        status = ProbeStatus.FAIL if isinstance(exc, PinnedVersionError) else ProbeStatus.BLOCKED
        return TfliteTaskTextDependencyReport(
            status=status,
            mode=mode,
            coordinate=f"{GROUP}:{ARTIFACT}",
            selected_version=None,
            maven_latest=metadata.latest if metadata else None,
            maven_release=metadata.release if metadata else None,
            maven_last_updated=metadata.last_updated if metadata else None,
            dynamic_repo_usages=dynamic_usages,
            default_runtime_usages=default_runtime_usages,
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
        with tempfile.TemporaryDirectory(prefix="goffy-tflite-task-text-probe-") as temp_dir:
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
    return TfliteTaskTextDependencyReport(
        status=status,
        mode=mode,
        coordinate=f"{GROUP}:{ARTIFACT}:{selected_version}",
        selected_version=selected_version,
        maven_latest=metadata.latest,
        maven_release=metadata.release,
        maven_last_updated=metadata.last_updated,
        dynamic_repo_usages=dynamic_usages,
        default_runtime_usages=default_runtime_usages,
        java=java,
        gradle=gradle,
        gradle_probe=gradle_probe,
        recommendation=recommendation_for(status, mode, selected_version),
    )


def repo_usage_recommendation(
    dynamic_usages: Sequence[str],
    default_runtime_usages: Sequence[str],
) -> str:
    if dynamic_usages:
        return "Replace dynamic TensorFlow Lite Task Text Gradle versions with an exact pin."
    if default_runtime_usages:
        return (
            "Keep TensorFlow Lite Task Text out of default GOFFY builds; use only "
            "variant-scoped modelDebug probe configurations until Moto evidence passes."
        )
    return "Repository TensorFlow Lite Task Text usage is compatible with the probe policy."


def recommendation_for(status: ProbeStatus, mode: ProbeMode, selected_version: str) -> str:
    if status is ProbeStatus.PASS and mode is ProbeMode.BUILD:
        return (
            f"{GROUP}:{ARTIFACT}:{selected_version} builds in the isolated Android probe; "
            "next gate is a modelDebug-only tiny classifier benchmark on the Moto G."
        )
    if status is ProbeStatus.PASS:
        return (
            f"{GROUP}:{ARTIFACT}:{selected_version} is resolvable with the local toolchain; "
            "run this script with --mode build before wiring modelDebug classifier code."
        )
    if status is ProbeStatus.BLOCKED:
        return "Dependency compatibility could not be proven because the probe was blocked."
    return "Do not add TensorFlow Lite Task Text to GOFFY until the failing probe is fixed."


def render_text_report(report: TfliteTaskTextDependencyReport) -> str:
    lines = [
        "GOFFY TensorFlow Lite Task Text dependency probe",
        f"[{report.status}] {report.coordinate}",
        f"mode: {report.mode}",
        f"maven release: {report.maven_release or 'unknown'}",
        f"maven latest: {report.maven_latest or 'unknown'}",
        f"maven lastUpdated: {report.maven_last_updated or 'unknown'}",
    ]
    if report.dynamic_repo_usages:
        lines.append("dynamic repo usages:")
        lines.extend(f"- {usage}" for usage in report.dynamic_repo_usages)
    if report.default_runtime_usages:
        lines.append("disallowed repo usages:")
        lines.extend(f"- {usage}" for usage in report.default_runtime_usages)
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
        description=(
            "Verify the pinned TensorFlow Lite Task Text Android dependency path "
            "before GOFFY modelDebug classifier integration."
        ),
    )
    parser.add_argument(
        "--version",
        help=(
            "Exact TensorFlow Lite Task Text version to verify. Defaults to the "
            f"committed GOFFY pin {PINNED_TFLITE_TASK_TEXT_VERSION}."
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
    report = verify_tflite_task_text_android_dependency(
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
