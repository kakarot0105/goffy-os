from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from scripts.verify_litertlm_android_dependency import (
    PINNED_LITERTLM_ANDROID_VERSION,
    MavenMetadata,
    ProbeMode,
    ProbeStatus,
    find_dynamic_litertlm_versions,
    parse_maven_metadata,
    sanitize_detail,
    select_pinned_version,
    verify_litertlm_android_dependency,
)

METADATA_XML = """\
<metadata>
  <groupId>com.google.ai.edge.litertlm</groupId>
  <artifactId>litertlm-android</artifactId>
  <versioning>
    <latest>0.14.0</latest>
    <release>0.14.0</release>
    <versions>
      <version>0.13.0</version>
      <version>0.14.0</version>
    </versions>
    <lastUpdated>20260708211520</lastUpdated>
  </versioning>
</metadata>
"""


def fetch_metadata(url: str, timeout_seconds: int) -> str:
    assert "litertlm-android/maven-metadata.xml" in url
    assert timeout_seconds <= 30
    return METADATA_XML


def passing_runner(
    seen: list[tuple[str, ...]],
) -> Callable[[Sequence[str], Path, int], subprocess.CompletedProcess[str]]:
    def run(
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        return subprocess.CompletedProcess(normalized, 0, stdout="ok\n", stderr="")

    return run


def failing_probe_runner(
    seen: list[tuple[str, ...]],
) -> Callable[[Sequence[str], Path, int], subprocess.CompletedProcess[str]]:
    def run(
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(str(part) for part in command)
        seen.append(normalized)
        if ":probe:dependencies" in normalized:
            return subprocess.CompletedProcess(
                normalized,
                1,
                stdout="",
                stderr="Unsupported class file major version 65\n",
            )
        return subprocess.CompletedProcess(normalized, 0, stdout="ok\n", stderr="")

    return run


def write_repo(tmp_path: Path, *, build_gradle_text: str = "") -> Path:
    root = tmp_path / "repo"
    app = root / "android" / "app"
    app.mkdir(parents=True)
    (root / "android" / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    (app / "build.gradle.kts").write_text(build_gradle_text, encoding="utf-8")
    return root


def test_parse_maven_metadata_extracts_release_versions_and_timestamp() -> None:
    metadata = parse_maven_metadata(METADATA_XML)

    assert metadata.release == "0.14.0"
    assert metadata.latest == "0.14.0"
    assert metadata.versions == ("0.13.0", "0.14.0")
    assert metadata.last_updated == "20260708211520"


def test_select_pinned_version_defaults_to_committed_pin() -> None:
    metadata = MavenMetadata(
        latest="0.15.0",
        release="0.15.0",
        versions=("0.14.0", "0.15.0"),
        last_updated="20260708211520",
    )

    assert select_pinned_version(None, metadata) == PINNED_LITERTLM_ANDROID_VERSION


@pytest.mark.parametrize("version", ["latest.release", "latest.integration", "0.+"])
def test_select_pinned_version_rejects_dynamic_versions(version: str) -> None:
    metadata = MavenMetadata(
        latest="0.14.0",
        release="0.14.0",
        versions=("0.14.0",),
        last_updated="20260708211520",
    )

    with pytest.raises(ValueError, match="exact pinned version"):
        select_pinned_version(version, metadata)


def test_select_pinned_version_rejects_unknown_metadata_version() -> None:
    metadata = MavenMetadata(
        latest="0.14.0",
        release="0.14.0",
        versions=("0.14.0",),
        last_updated="20260708211520",
    )

    with pytest.raises(ValueError, match="not present"):
        select_pinned_version("9.9.9", metadata)


def test_find_dynamic_litertlm_versions_scans_android_gradle_files_only(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text='implementation("com.google.ai.edge.litertlm:litertlm-android:latest.release")\n',
    )
    docs = root / "docs"
    docs.mkdir()
    (docs / "note.md").write_text(
        "documentation may mention com.google.ai.edge.litertlm:litertlm-android:latest.release\n",
        encoding="utf-8",
    )

    assert find_dynamic_litertlm_versions(root) == ("android/app/build.gradle.kts:1",)


def test_find_dynamic_litertlm_versions_rejects_catalog_direct_version(
    tmp_path: Path,
) -> None:
    root = write_repo(tmp_path)
    catalog = root / "android" / "gradle" / "libs.versions.toml"
    catalog.parent.mkdir()
    catalog.write_text(
        """
[libraries]
litertlm = { module = "com.google.ai.edge.litertlm:litertlm-android", version = "latest.release" }
""".lstrip(),
        encoding="utf-8",
    )

    assert find_dynamic_litertlm_versions(root) == ("android/gradle/libs.versions.toml:2",)


def test_find_dynamic_litertlm_versions_rejects_catalog_version_ref(
    tmp_path: Path,
) -> None:
    root = write_repo(tmp_path)
    catalog = root / "android" / "gradle" / "libs.versions.toml"
    catalog.parent.mkdir()
    catalog.write_text(
        """
[versions]
litertlm = "latest.release"

[libraries.litertlmRuntime]
module = "com.google.ai.edge.litertlm:litertlm-android"
version.ref = "litertlm"
""".lstrip(),
        encoding="utf-8",
    )

    assert find_dynamic_litertlm_versions(root) == ("android/gradle/libs.versions.toml:2",)


def test_verify_metadata_mode_reports_pinned_coordinate_without_gradle_probe(
    tmp_path: Path,
) -> None:
    root = write_repo(tmp_path)
    seen: list[tuple[str, ...]] = []

    report = verify_litertlm_android_dependency(
        root=root,
        mode=ProbeMode.METADATA,
        fetcher=fetch_metadata,
        runner=passing_runner(seen),
    )

    assert report.status is ProbeStatus.PASS
    assert report.coordinate.endswith(":0.14.0")
    assert report.gradle_probe is None
    assert any(command[:2] == ("java", "-version") for command in seen)


def test_verify_resolve_mode_reports_gradle_classfile_failure(tmp_path: Path) -> None:
    root = write_repo(tmp_path)
    seen: list[tuple[str, ...]] = []

    report = verify_litertlm_android_dependency(
        root=root,
        mode=ProbeMode.RESOLVE,
        fetcher=fetch_metadata,
        runner=failing_probe_runner(seen),
    )

    assert report.status is ProbeStatus.FAIL
    assert report.gradle_probe is not None
    assert "Unsupported class file major version 65" in report.gradle_probe.detail
    assert "Do not add LiteRT-LM" in report.recommendation


def test_verify_reports_network_blocker_without_running_gradle(tmp_path: Path) -> None:
    root = write_repo(tmp_path)
    seen: list[tuple[str, ...]] = []

    def fail_fetch(url: str, timeout_seconds: int) -> str:
        raise OSError("network unavailable")

    report = verify_litertlm_android_dependency(
        root=root,
        mode=ProbeMode.RESOLVE,
        fetcher=fail_fetch,
        runner=passing_runner(seen),
    )

    assert report.status is ProbeStatus.BLOCKED
    assert report.recommendation == "network unavailable"
    assert seen == []


def test_verify_reports_dynamic_repo_usage_as_fail_before_network(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text='implementation("com.google.ai.edge.litertlm:litertlm-android:latest.release")\n',
    )

    def fail_fetch(url: str, timeout_seconds: int) -> str:
        raise AssertionError("metadata fetch should not run when repo usage is already unsafe")

    report = verify_litertlm_android_dependency(
        root=root,
        mode=ProbeMode.RESOLVE,
        fetcher=fail_fetch,
        runner=passing_runner([]),
    )

    assert report.status is ProbeStatus.FAIL
    assert report.dynamic_repo_usages == ("android/app/build.gradle.kts:1",)


def test_verify_fails_when_repo_uses_dynamic_litertlm_version(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text='implementation("com.google.ai.edge.litertlm:litertlm-android:0.+")\n',
    )

    report = verify_litertlm_android_dependency(
        root=root,
        mode=ProbeMode.RESOLVE,
        fetcher=fetch_metadata,
        runner=passing_runner([]),
    )

    assert report.status is ProbeStatus.FAIL
    assert report.dynamic_repo_usages == ("android/app/build.gradle.kts:1",)
    assert "exact pin" in report.recommendation


def test_sanitize_detail_redacts_absolute_paths_but_keeps_urls(tmp_path: Path) -> None:
    text = (
        "Daemon JVM: /opt/homebrew/Cellar/openjdk@17/17.0.19\n"
        "Docs: https://docs.gradle.org/9.4.1/userguide/configuration_cache.html\n"
        "Windows SDK: C:\\Users\\demo\\Android\\Sdk\n"
    )

    sanitized = sanitize_detail(text, tmp_path, ())

    assert "/opt/homebrew" not in sanitized
    assert "C:\\Users" not in sanitized
    assert "https://docs.gradle.org/9.4.1/userguide/configuration_cache.html" in sanitized


def test_sanitize_detail_redacts_quoted_paths_with_spaces(tmp_path: Path) -> None:
    text = (
        'JDK="/Applications/Android Studio.app/Contents/jbr/Contents/Home"\n'
        'SDK="C:\\Program Files\\Android\\Sdk"\n'
    )

    sanitized = sanitize_detail(text, tmp_path, ())

    assert "Android Studio.app" not in sanitized
    assert "Program Files" not in sanitized
    assert 'JDK="<path>"' in sanitized
    assert 'SDK="<path>"' in sanitized
