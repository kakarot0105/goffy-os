from pathlib import Path

from scripts.security_scan import (
    ALLOWED_ANDROID_PERMISSIONS,
    ALLOWED_MERGED_ANDROID_PERMISSIONS,
    ALLOWED_SUBPROCESS_FILES,
    PAIRING_QR_ARTIFACT_MARKER,
    merged_manifest_permission_allowlist,
    prohibited_source_patterns,
    validate_allowed_subprocess_usage,
    validate_main_activity_intent_filters,
    validate_manifest,
    validate_merged_manifests,
    validate_no_pairing_qr_artifact,
)

EXPECTED_MANIFEST = """\
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="com.android.alarm.permission.SET_ALARM" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-feature android:name="android.hardware.camera" android:required="false" />
    <uses-feature android:name="android.hardware.camera.flash" android:required="false" />
    <uses-feature android:name="android.hardware.microphone" android:required="false" />
    <queries>
        <intent>
            <action android:name="android.intent.action.SET_TIMER" />
        </intent>
    </queries>
</manifest>
"""

EXPECTED_APP_MANIFEST = """\
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application>
        <activity android:name=".MainActivity">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.HOME" />
                <category android:name="android.intent.category.DEFAULT" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""


def write_manifest(tmp_path: Path, content: str) -> Path:
    manifest = tmp_path / "AndroidManifest.xml"
    manifest.write_text(content, encoding="utf-8")
    return manifest


def write_merged_manifest(tmp_path: Path, variant: str, content: str) -> Path:
    manifest = tmp_path / variant / f"process{variant.title()}Manifest" / "AndroidManifest.xml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(content, encoding="utf-8")
    return manifest


def test_manifest_allowlist_accepts_exact_structure(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, EXPECTED_MANIFEST)

    assert validate_manifest(manifest, ALLOWED_ANDROID_PERMISSIONS) == []


def test_main_activity_home_shell_filters_accept_exact_shape(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, EXPECTED_APP_MANIFEST)

    assert validate_main_activity_intent_filters(manifest) == []


def test_main_activity_home_shell_filters_reject_missing_home(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path,
        EXPECTED_APP_MANIFEST.replace(
            """            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.HOME" />
                <category android:name="android.intent.category.DEFAULT" />
            </intent-filter>
""",
            "",
        ),
    )

    findings = validate_main_activity_intent_filters(manifest)

    assert any("launcher/home filters mismatch" in finding for finding in findings)


def test_main_activity_home_shell_filters_reject_duplicate_filters(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path,
        EXPECTED_APP_MANIFEST.replace(
            "        </activity>",
            """            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>""",
        ),
    )

    findings = validate_main_activity_intent_filters(manifest)

    assert any("launcher/home filters mismatch" in finding for finding in findings)


def test_merged_manifest_allowlist_accepts_dependency_permissions(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path,
        EXPECTED_MANIFEST.replace(
            "    <uses-feature",
            '    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />\n'
            '    <uses-permission android:name="'
            'dev.goffy.os.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION" />\n'
            "    <uses-feature",
            1,
        ),
    )

    assert validate_manifest(manifest, ALLOWED_MERGED_ANDROID_PERMISSIONS) == []


def test_modeldebug_merged_manifest_allowlist_accepts_variant_receiver_permission(
    tmp_path: Path,
) -> None:
    manifest = write_manifest(
        tmp_path,
        EXPECTED_MANIFEST.replace(
            "    <uses-feature",
            '    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />\n'
            '    <uses-permission android:name="'
            'dev.goffy.os.model.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION" />\n'
            "    <uses-feature",
            1,
        ),
    )

    allowlist = merged_manifest_permission_allowlist("modelDebug")

    assert allowlist is not None
    assert validate_manifest(manifest, allowlist) == []


def test_merged_manifest_validation_requires_modeldebug_variant(tmp_path: Path) -> None:
    manifests = [
        write_merged_manifest(tmp_path, "debug", EXPECTED_MANIFEST),
        write_merged_manifest(tmp_path, "release", EXPECTED_MANIFEST),
    ]

    findings = validate_merged_manifests(manifests, manifest_root=tmp_path)

    assert any("modelDebug" in finding for finding in findings)


def test_manifest_allowlist_rejects_permission_variants_and_non_intent_queries(
    tmp_path: Path,
) -> None:
    manifest = write_manifest(
        tmp_path,
        EXPECTED_MANIFEST.replace(
            "    <queries>",
            '    <uses-permission-sdk-23 android:name="android.permission.RECORD_AUDIO" />\n'
            "    <queries>\n"
            '        <package android:name="com.example.clock" />',
        ),
    )

    findings = validate_manifest(manifest, ALLOWED_ANDROID_PERMISSIONS)

    assert any("unexpected permission tags" in finding for finding in findings)
    assert any("unexpected queries entry package" in finding for finding in findings)


def test_manifest_allowlist_rejects_extra_query_shape(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path,
        EXPECTED_MANIFEST.replace(
            '<action android:name="android.intent.action.SET_TIMER" />',
            '<action android:name="android.intent.action.SET_TIMER" />\n'
            '            <category android:name="android.intent.category.DEFAULT" />',
        ),
    )

    findings = validate_manifest(manifest, ALLOWED_ANDROID_PERMISSIONS)

    assert any("exactly one action" in finding for finding in findings)


def test_manifest_allowlist_rejects_required_or_extra_hardware_features(tmp_path: Path) -> None:
    manifest = write_manifest(
        tmp_path,
        EXPECTED_MANIFEST.replace(
            'android:name="android.hardware.camera.flash" android:required="false"',
            'android:name="android.hardware.camera.flash" android:required="true"',
        ).replace(
            "    <queries>",
            '    <uses-feature android:name="android.hardware.location.gps" '
            'android:required="false" />\n'
            "    <queries>",
        ),
    )

    findings = validate_manifest(manifest, ALLOWED_ANDROID_PERMISSIONS)

    assert any("hardware feature allowlist mismatch" in finding for finding in findings)


def test_security_scan_rejects_generated_pairing_qr_artifact(tmp_path: Path) -> None:
    default_artifact = tmp_path / "goffy-pairing-bundle.svg"
    custom_artifact = tmp_path / "custom.svg"

    assert validate_no_pairing_qr_artifact(default_artifact, "<svg />")
    assert validate_no_pairing_qr_artifact(
        custom_artifact,
        f"<!-- {PAIRING_QR_ARTIFACT_MARKER} --><svg />",
    )
    assert validate_no_pairing_qr_artifact(tmp_path / "logo.svg", "<svg />") == []


def test_subprocess_exception_is_limited_to_git_status_tool_shape() -> None:
    git_status_file = next(
        path for path in ALLOWED_SUBPROCESS_FILES if path.name == "git_status.py"
    )
    generic_file = git_status_file.with_name("other_tool.py")
    source = git_status_file.read_text(encoding="utf-8")
    git_status_location = git_status_file.relative_to(git_status_file.parents[4])

    assert validate_allowed_subprocess_usage(git_status_file, source) == []
    assert validate_allowed_subprocess_usage(
        git_status_file,
        source.replace("subprocess.run(", "subprocess.Popen(", 1),
    ) == [f"{git_status_location}: unsupported subprocess API subprocess.Popen"]
    assert validate_allowed_subprocess_usage(
        git_status_file,
        source.replace("timeout=timeout_seconds,", "timeout=timeout_seconds, shell=True,", 1),
    ) == [f"{git_status_location}: subprocess.run shape does not match allowlisted policy"]
    assert "subprocess API" in prohibited_source_patterns(git_status_file)
    assert "subprocess API" in prohibited_source_patterns(generic_file)
    assert "shell execution" in prohibited_source_patterns(git_status_file)


def test_subprocess_exception_is_limited_to_mac_app_open_tool_shape() -> None:
    mac_apps_file = next(path for path in ALLOWED_SUBPROCESS_FILES if path.name == "mac_apps.py")
    source = mac_apps_file.read_text(encoding="utf-8")
    location = mac_apps_file.relative_to(mac_apps_file.parents[4])

    assert validate_allowed_subprocess_usage(mac_apps_file, source) == []
    assert validate_allowed_subprocess_usage(
        mac_apps_file,
        source.replace(
            'OSASCRIPT_EXECUTABLE = "/usr/bin/osascript"',
            'OSASCRIPT_EXECUTABLE = "/bin/sh"',
            1,
        ),
    ) == [f"{location}: subprocess.run shape does not match allowlisted policy"]
    assert validate_allowed_subprocess_usage(
        mac_apps_file,
        source.replace(
            "f'application id \"{bundle_id}\" is running'",
            "f'do shell script \"{bundle_id}\"'",
            1,
        ),
    ) == [f"{location}: subprocess.run shape does not match allowlisted policy"]
    assert validate_allowed_subprocess_usage(
        mac_apps_file,
        source.replace("timeout=timeout_seconds,", "timeout=1.0,", 1),
    ) == [f"{location}: subprocess.run shape does not match allowlisted policy"]
    assert validate_allowed_subprocess_usage(
        mac_apps_file,
        source.replace("import subprocess", "import subprocess as sp", 1).replace(
            "subprocess.run(",
            "sp.run(",
            1,
        ),
    ) == [
        f"{location}: indirect subprocess call is not allowed",
        f"{location}: subprocess import aliases are not allowed",
    ]
    assert validate_allowed_subprocess_usage(
        mac_apps_file,
        source.replace(
            "return subprocess.run(",
            "runner = subprocess.run\n    return runner(",
            1,
        ),
    ) == [f"{location}: subprocess binding is not allowed"]
    assert validate_allowed_subprocess_usage(
        mac_apps_file,
        source.replace(
            "return subprocess.run(",
            'return getattr(subprocess, "run")(',
            1,
        ),
    ) == [f"{location}: indirect subprocess call is not allowed"]
    assert validate_allowed_subprocess_usage(
        mac_apps_file,
        source.replace(
            "import subprocess",
            'import subprocess\nsubprocess.run = getattr(__import__("os"), "spawnv")',
            1,
        ),
    ) == [f"{location}: subprocess binding is not allowed"]
    assert validate_allowed_subprocess_usage(
        mac_apps_file,
        source.replace(
            "import subprocess",
            "import subprocess\nsubprocess.TimeoutExpired = Exception",
            1,
        ),
    ) == [f"{location}: subprocess binding is not allowed"]
