from __future__ import annotations

import os
from pathlib import Path

from scripts.android_preflight import (
    Check,
    collect_checks,
    java_home_from_bin,
    java_major_from_release,
    render_report,
    resolve_adb,
)


def write_jdk(tmp_path: Path, version: str) -> Path:
    home = tmp_path / "jdk"
    home.mkdir()
    (home / "release").write_text(f'JAVA_VERSION="{version}"\n', encoding="utf-8")
    bin_dir = home / "bin"
    bin_dir.mkdir()
    (bin_dir / "java").write_text("", encoding="utf-8")
    return home


def write_android_project(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    android = root / "android"
    android.mkdir(parents=True)
    gradlew = android / "gradlew"
    gradlew.write_text("#!/bin/sh\n", encoding="utf-8")
    gradlew.chmod(0o755)
    return root


def write_android_sdk(tmp_path: Path) -> Path:
    sdk = tmp_path / "sdk"
    (sdk / "platforms" / "android-36").mkdir(parents=True)
    (sdk / "build-tools" / "36.0.0").mkdir(parents=True)
    platform_tools = sdk / "platform-tools"
    platform_tools.mkdir(parents=True)
    adb = platform_tools / "adb"
    adb.write_text("", encoding="utf-8")
    adb.chmod(0o755)
    return sdk


def test_java_major_from_release_accepts_current_version_shape(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.write_text('JAVA_VERSION="17.0.11"\n', encoding="utf-8")

    assert java_major_from_release(release) == 17


def test_java_home_from_bin_resolves_release_home(tmp_path: Path) -> None:
    jdk = write_jdk(tmp_path, "21.0.1")

    assert java_home_from_bin(str(jdk / "bin" / "java")) == jdk


def test_collect_checks_accepts_valid_android_environment(tmp_path: Path) -> None:
    root = write_android_project(tmp_path)
    jdk = write_jdk(tmp_path, "17.0.11")
    sdk = write_android_sdk(tmp_path)

    checks = collect_checks(
        root=root,
        env={"JAVA_HOME": str(jdk), "ANDROID_HOME": str(sdk)},
        known_jdk_homes=[],
        sdk_roots=[sdk],
        java_on_path=None,
        adb_on_path=None,
        use_path_tools=False,
    )

    assert all(check.ok for check in checks)
    assert "Ready for Android Gradle validation" in render_report(checks)


def test_render_report_redacts_paths_and_escapes_control_characters(tmp_path: Path) -> None:
    report = render_report(
        [
            Check(
                name="JDK",
                ok=False,
                detail=f"{tmp_path}/jdk\n[OK] forged\x1b[31m",
                remediation=f"set JAVA_HOME under {tmp_path}\rnow",
            )
        ]
    )

    assert "[FAIL] JDK: <path>\\n[OK] forged" in report
    assert "fix: set JAVA_HOME under <path>\\rnow" in report
    assert str(tmp_path) not in report


def test_collect_checks_rejects_missing_jdk_without_shelling_out(tmp_path: Path) -> None:
    root = write_android_project(tmp_path)
    sdk = write_android_sdk(tmp_path)

    checks = collect_checks(
        root=root,
        env={"ANDROID_HOME": str(sdk)},
        known_jdk_homes=[],
        sdk_roots=[sdk],
        java_on_path=None,
        adb_on_path=None,
        use_path_tools=False,
    )

    assert any(check.name == "JDK" and not check.ok for check in checks)


def test_collect_checks_rejects_mismatched_android_sdk_roots(tmp_path: Path) -> None:
    root = write_android_project(tmp_path)
    jdk = write_jdk(tmp_path, "17.0.11")
    sdk = write_android_sdk(tmp_path)
    other_sdk = tmp_path / "other-sdk"
    other_sdk.mkdir()

    checks = collect_checks(
        root=root,
        env={
            "JAVA_HOME": str(jdk),
            "ANDROID_HOME": str(sdk),
            "ANDROID_SDK_ROOT": str(other_sdk),
        },
        known_jdk_homes=[],
        sdk_roots=[sdk],
        java_on_path=None,
        adb_on_path=None,
        use_path_tools=False,
    )

    assert any(check.name == "Android SDK root" and not check.ok for check in checks)


def test_gradle_wrapper_requires_executable_on_unix(tmp_path: Path) -> None:
    if os.name == "nt":
        return
    root = write_android_project(tmp_path)
    (root / "android" / "gradlew").chmod(0o644)
    jdk = write_jdk(tmp_path, "17.0.11")
    sdk = write_android_sdk(tmp_path)

    checks = collect_checks(
        root=root,
        env={"JAVA_HOME": str(jdk), "ANDROID_HOME": str(sdk)},
        known_jdk_homes=[],
        sdk_roots=[sdk],
        java_on_path=None,
        adb_on_path=None,
        use_path_tools=False,
    )

    assert any(check.name == "Gradle wrapper" and not check.ok for check in checks)


def test_resolve_adb_rejects_relative_candidates(tmp_path: Path) -> None:
    sdk = Path("relative-sdk")

    assert resolve_adb(sdk, "relative-adb") is None


def test_resolve_adb_accepts_absolute_executable(tmp_path: Path) -> None:
    sdk = write_android_sdk(tmp_path)

    assert resolve_adb(sdk, None) == sdk / "platform-tools" / "adb"
