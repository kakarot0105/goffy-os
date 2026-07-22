from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from scripts.verify_litertlm_android_dependency import MavenMetadata, ProbeMode, ProbeStatus
from scripts.verify_tflite_task_text_android_dependency import (
    PINNED_TFLITE_TASK_TEXT_VERSION,
    find_tflite_task_text_repo_usages,
    metadata_url,
    select_pinned_version,
    verify_tflite_task_text_android_dependency,
)

METADATA_XML = """\
<metadata>
  <groupId>org.tensorflow</groupId>
  <artifactId>tensorflow-lite-task-text</artifactId>
  <versioning>
    <latest>0.4.4</latest>
    <release>0.4.4</release>
    <versions>
      <version>0.4.3</version>
      <version>0.4.4</version>
    </versions>
    <lastUpdated>20230717111520</lastUpdated>
  </versioning>
</metadata>
"""


def fetch_metadata(url: str, timeout_seconds: int) -> str:
    assert url == metadata_url()
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
                stderr="Could not resolve org.tensorflow:tensorflow-lite-task-text\n",
            )
        return subprocess.CompletedProcess(normalized, 0, stdout="ok\n", stderr="")

    return run


def write_repo(
    tmp_path: Path,
    *,
    build_gradle_text: str = "",
    catalog_text: str = "",
) -> Path:
    root = tmp_path / "repo"
    app = root / "android" / "app"
    app.mkdir(parents=True)
    (root / "android" / "gradlew").write_text("#!/bin/sh\n", encoding="utf-8")
    (app / "build.gradle.kts").write_text(build_gradle_text, encoding="utf-8")
    if catalog_text:
        catalog = root / "android" / "gradle" / "libs.versions.toml"
        catalog.parent.mkdir()
        catalog.write_text(catalog_text, encoding="utf-8")
    return root


def test_select_pinned_version_defaults_to_committed_pin() -> None:
    metadata = MavenMetadata(
        latest="0.4.4",
        release="0.4.4",
        versions=("0.4.4",),
        last_updated="20230717111520",
    )

    assert select_pinned_version(None, metadata) == PINNED_TFLITE_TASK_TEXT_VERSION


@pytest.mark.parametrize("version", ["latest.release", "latest.integration", "0.+"])
def test_select_pinned_version_rejects_dynamic_versions(version: str) -> None:
    metadata = MavenMetadata(
        latest="0.4.4",
        release="0.4.4",
        versions=("0.4.4",),
        last_updated="20230717111520",
    )

    with pytest.raises(ValueError, match="exact pinned version"):
        select_pinned_version(version, metadata)


def test_select_pinned_version_rejects_unknown_metadata_version() -> None:
    metadata = MavenMetadata(
        latest="0.4.4",
        release="0.4.4",
        versions=("0.4.4",),
        last_updated="20230717111520",
    )

    with pytest.raises(ValueError, match="not present"):
        select_pinned_version("9.9.9", metadata)


def test_find_repo_usages_rejects_dynamic_direct_version(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text=(
            'androidTestImplementation("org.tensorflow:tensorflow-lite-task-text:latest.release")\n'
        ),
    )

    dynamic, default_runtime = find_tflite_task_text_repo_usages(root)

    assert dynamic == ("android/app/build.gradle.kts:1",)
    assert default_runtime == ()


def test_find_repo_usages_blocks_default_runtime_direct_coordinate(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text='implementation("org.tensorflow:tensorflow-lite-task-text:0.4.4")\n',
    )

    dynamic, default_runtime = find_tflite_task_text_repo_usages(root)

    assert dynamic == ()
    assert default_runtime == ("android/app/build.gradle.kts:1",)


@pytest.mark.parametrize(
    "configuration",
    [
        "debugRuntimeOnly",
        "releaseRuntimeOnly",
        "debugCompileOnly",
        "testImplementation",
    ],
)
def test_find_repo_usages_blocks_unapproved_variant_configurations(
    tmp_path: Path,
    configuration: str,
) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text=(f'{configuration}("org.tensorflow:tensorflow-lite-task-text:0.4.4")\n'),
    )

    dynamic, default_runtime = find_tflite_task_text_repo_usages(root)

    assert dynamic == ()
    assert default_runtime == ("android/app/build.gradle.kts:1",)


def test_find_repo_usages_blocks_unapproved_add_configuration(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text=(
            'add("releaseRuntimeOnly", "org.tensorflow:tensorflow-lite-task-text:0.4.4")\n'
        ),
    )

    dynamic, default_runtime = find_tflite_task_text_repo_usages(root)

    assert dynamic == ()
    assert default_runtime == ("android/app/build.gradle.kts:1",)


def test_find_repo_usages_allows_android_test_and_modeldebug(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text="""
androidTestImplementation("org.tensorflow:tensorflow-lite-task-text:0.4.4")
modelDebugImplementation("org.tensorflow:tensorflow-lite-task-text:0.4.4")
add("modelDebugImplementation", "org.tensorflow:tensorflow-lite-task-text:0.4.4")
""".lstrip(),
    )

    assert find_tflite_task_text_repo_usages(root) == ((), ())


def test_find_repo_usages_rejects_catalog_dynamic_version(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        catalog_text="""
[versions]
tfliteTaskText = "latest.release"

[libraries.tflite-task-text]
module = "org.tensorflow:tensorflow-lite-task-text"
version.ref = "tfliteTaskText"
""".lstrip(),
    )

    dynamic, default_runtime = find_tflite_task_text_repo_usages(root)

    assert dynamic == ("android/gradle/libs.versions.toml:2",)
    assert default_runtime == ()


def test_find_repo_usages_blocks_default_runtime_catalog_alias(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text="implementation(libs.tflite.task.text)\n",
        catalog_text="""
[libraries]
tflite-task-text = "org.tensorflow:tensorflow-lite-task-text:0.4.4"
""".lstrip(),
    )

    dynamic, default_runtime = find_tflite_task_text_repo_usages(root)

    assert dynamic == ()
    assert default_runtime == ("android/app/build.gradle.kts:1",)


def test_find_repo_usages_blocks_variant_runtime_catalog_alias(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text="releaseRuntimeOnly(libs.tflite.task.text)\n",
        catalog_text="""
[libraries]
tflite-task-text = "org.tensorflow:tensorflow-lite-task-text:0.4.4"
""".lstrip(),
    )

    dynamic, default_runtime = find_tflite_task_text_repo_usages(root)

    assert dynamic == ()
    assert default_runtime == ("android/app/build.gradle.kts:1",)


def test_verify_metadata_mode_reports_pinned_coordinate_without_gradle_probe(
    tmp_path: Path,
) -> None:
    root = write_repo(tmp_path)
    seen: list[tuple[str, ...]] = []

    report = verify_tflite_task_text_android_dependency(
        root=root,
        mode=ProbeMode.METADATA,
        fetcher=fetch_metadata,
        runner=passing_runner(seen),
    )

    assert report.status is ProbeStatus.PASS
    assert report.coordinate.endswith(":0.4.4")
    assert report.gradle_probe is None
    assert any(command[:2] == ("java", "-version") for command in seen)


def test_verify_resolve_mode_reports_gradle_probe_failure(tmp_path: Path) -> None:
    root = write_repo(tmp_path)
    seen: list[tuple[str, ...]] = []

    report = verify_tflite_task_text_android_dependency(
        root=root,
        mode=ProbeMode.RESOLVE,
        fetcher=fetch_metadata,
        runner=failing_probe_runner(seen),
    )

    assert report.status is ProbeStatus.FAIL
    assert report.gradle_probe is not None
    assert "Could not resolve" in report.gradle_probe.detail
    assert "Do not add TensorFlow Lite Task Text" in report.recommendation


def test_verify_reports_network_blocker_without_running_gradle(tmp_path: Path) -> None:
    root = write_repo(tmp_path)
    seen: list[tuple[str, ...]] = []

    def fail_fetch(url: str, timeout_seconds: int) -> str:
        raise OSError("network unavailable")

    report = verify_tflite_task_text_android_dependency(
        root=root,
        mode=ProbeMode.RESOLVE,
        fetcher=fail_fetch,
        runner=passing_runner(seen),
    )

    assert report.status is ProbeStatus.BLOCKED
    assert report.recommendation == "network unavailable"
    assert seen == []


def test_verify_fails_repo_default_runtime_usage_before_network(tmp_path: Path) -> None:
    root = write_repo(
        tmp_path,
        build_gradle_text='implementation("org.tensorflow:tensorflow-lite-task-text:0.4.4")\n',
    )

    def fail_fetch(url: str, timeout_seconds: int) -> str:
        raise AssertionError("metadata fetch should not run when repo usage is unsafe")

    report = verify_tflite_task_text_android_dependency(
        root=root,
        mode=ProbeMode.RESOLVE,
        fetcher=fail_fetch,
        runner=passing_runner([]),
    )

    assert report.status is ProbeStatus.FAIL
    assert report.default_runtime_usages == ("android/app/build.gradle.kts:1",)
