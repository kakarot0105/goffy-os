from pathlib import Path

from scripts.security_scan import ALLOWED_ANDROID_PERMISSIONS, validate_manifest

EXPECTED_MANIFEST = """\
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="com.android.alarm.permission.SET_ALARM" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-feature android:name="android.hardware.camera" android:required="false" />
    <uses-feature android:name="android.hardware.camera.flash" android:required="false" />
    <queries>
        <intent>
            <action android:name="android.intent.action.SET_TIMER" />
        </intent>
    </queries>
</manifest>
"""


def write_manifest(tmp_path: Path, content: str) -> Path:
    manifest = tmp_path / "AndroidManifest.xml"
    manifest.write_text(content, encoding="utf-8")
    return manifest


def test_manifest_allowlist_accepts_exact_structure(tmp_path: Path) -> None:
    manifest = write_manifest(tmp_path, EXPECTED_MANIFEST)

    assert validate_manifest(manifest, ALLOWED_ANDROID_PERMISSIONS) == []


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
            '    <uses-feature android:name="android.hardware.microphone" '
            'android:required="false" />\n'
            "    <queries>",
        ),
    )

    findings = validate_manifest(manifest, ALLOWED_ANDROID_PERMISSIONS)

    assert any("hardware feature allowlist mismatch" in finding for finding in findings)
