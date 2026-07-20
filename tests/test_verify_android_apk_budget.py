from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.verify_android_apk_budget import (
    JSON_SCHEMA_VERSION,
    ReleaseDependencyCheck,
    RuntimeClasspathCheck,
    find_forbidden_release_dependencies,
    find_forbidden_runtime_dependencies,
    render_json,
    render_text,
    verify_android_apk_budget,
)


def test_apk_budget_passes_for_small_apk_without_model_payload(tmp_path: Path) -> None:
    apk = tmp_path / "app-release-unsigned.apk"
    write_apk(apk, {"classes.dex": b"dex", "AndroidManifest.xml": b"manifest"})

    report = verify_android_apk_budget(
        apk_path=apk,
        max_apk_bytes=apk.stat().st_size + 1,
        repo_root=tmp_path,
    )

    assert report.ok
    assert report.forbidden_entries == ()
    assert "[OK] forbidden LiteRT-LM/model payloads: none" in render_text(report)


def test_apk_budget_fails_when_release_runtime_classpath_includes_litertlm(
    tmp_path: Path,
) -> None:
    apk = tmp_path / "app-release-unsigned.apk"
    write_apk(apk, {"classes.dex": b"dex"})

    report = verify_android_apk_budget(
        apk_path=apk,
        max_apk_bytes=apk.stat().st_size + 1,
        repo_root=tmp_path,
        release_dependencies=ReleaseDependencyCheck(
            configuration="releaseRuntimeClasspath",
            checked=True,
            forbidden_matches=("+--- com.google.ai.edge.litertlm:litertlm-android:0.14.0",),
        ),
    )

    assert not report.ok
    assert "[FAIL] releaseRuntimeClasspath LiteRT-LM dependencies:" in render_text(report)


def test_apk_budget_fails_when_debug_runtime_classpath_includes_litertlm(
    tmp_path: Path,
) -> None:
    apk = tmp_path / "app-release-unsigned.apk"
    write_apk(apk, {"classes.dex": b"dex"})

    report = verify_android_apk_budget(
        apk_path=apk,
        max_apk_bytes=apk.stat().st_size + 1,
        repo_root=tmp_path,
        runtime_classpaths=(
            RuntimeClasspathCheck(
                configuration="debugRuntimeClasspath",
                checked=True,
                forbidden_matches=("\\--- com.google.ai.edge.litertlm:litertlm-android:0.14.0",),
            ),
            RuntimeClasspathCheck.passed("releaseRuntimeClasspath"),
        ),
    )

    assert not report.ok
    assert "[FAIL] debugRuntimeClasspath LiteRT-LM dependencies:" in render_text(report)


def test_release_runtime_dependency_parser_detects_litertlm_coordinates() -> None:
    matches = find_forbidden_release_dependencies(
        "releaseRuntimeClasspath\n"
        "+--- androidx.compose.ui:ui:1.11.3\n"
        "+--- com.google.ai.edge.litertlm:litertlm-android:0.14.0\n"
        "\\--- com.squareup.okhttp3:okhttp:5.4.0\n"
    )

    assert matches == ("+--- com.google.ai.edge.litertlm:litertlm-android:0.14.0",)


def test_runtime_dependency_parser_deduplicates_default_classpath_matches() -> None:
    matches = find_forbidden_runtime_dependencies(
        "debugRuntimeClasspath\n"
        "+--- com.google.ai.edge.litertlm:litertlm-android:0.14.0\n"
        "+--- com.google.ai.edge.litertlm:litertlm-android:0.14.0\n"
        "releaseRuntimeClasspath\n"
        "\\--- androidx.compose.ui:ui:1.11.3\n"
    )

    assert matches == ("+--- com.google.ai.edge.litertlm:litertlm-android:0.14.0",)


def test_apk_budget_fails_when_release_apk_is_missing(tmp_path: Path) -> None:
    report = verify_android_apk_budget(
        apk_path=tmp_path / "missing.apk",
        max_apk_bytes=1024,
        repo_root=tmp_path,
    )

    assert not report.ok
    assert report.error == "Release APK is missing; run the Android release build first."


def test_apk_budget_fails_when_apk_exceeds_goffy_lite_budget(tmp_path: Path) -> None:
    apk = tmp_path / "app-release-unsigned.apk"
    write_apk(apk, {"classes.dex": b"x" * 2048})

    report = verify_android_apk_budget(
        apk_path=apk,
        max_apk_bytes=10,
        repo_root=tmp_path,
    )

    assert not report.ok
    assert report.apk_bytes is not None
    assert report.apk_bytes > report.max_apk_bytes
    assert "[FAIL] release APK size" in render_text(report)


def test_apk_budget_fails_when_litertlm_or_model_entries_are_packaged(tmp_path: Path) -> None:
    apk = tmp_path / "app-release-unsigned.apk"
    write_apk(
        apk,
        {
            "classes.dex": b"dex",
            "lib/arm64-v8a/liblitertlm_jni.so": b"runtime",
            "assets/models/router.litertlm": b"model",
        },
    )

    report = verify_android_apk_budget(
        apk_path=apk,
        max_apk_bytes=apk.stat().st_size + 1,
        repo_root=tmp_path,
    )

    assert not report.ok
    assert report.forbidden_entries == (
        "assets/models/router.litertlm",
        "lib/arm64-v8a/liblitertlm_jni.so",
    )


def test_apk_budget_json_is_machine_readable_and_path_scoped(tmp_path: Path) -> None:
    apk = tmp_path / "android" / "app-release-unsigned.apk"
    write_apk(apk, {"classes.dex": b"dex"})
    report = verify_android_apk_budget(
        apk_path=apk,
        max_apk_bytes=apk.stat().st_size + 1,
        repo_root=tmp_path,
    )

    payload = json.loads(render_json(report))

    assert payload["schemaVersion"] == JSON_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["apkPath"] == "android/app-release-unsigned.apk"
    assert payload["forbiddenEntries"] == []
    assert [check["configuration"] for check in payload["runtimeClasspathChecks"]] == [
        "debugRuntimeClasspath",
        "releaseRuntimeClasspath",
    ]
    assert payload["releaseDependencyForbiddenMatches"] == []


def test_apk_budget_fails_for_unreadable_apk_zip(tmp_path: Path) -> None:
    apk = tmp_path / "app-release-unsigned.apk"
    apk.write_bytes(b"not a zip")

    report = verify_android_apk_budget(
        apk_path=apk,
        max_apk_bytes=apk.stat().st_size + 1,
        repo_root=tmp_path,
    )

    assert not report.ok
    assert report.error == "Release APK is not a readable ZIP archive."


def write_apk(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, mode="w") as apk:
        for name, content in entries.items():
            apk.writestr(name, content)
