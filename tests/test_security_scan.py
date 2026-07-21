from pathlib import Path

from scripts.security_scan import (
    ALLOWED_ANDROID_PERMISSIONS,
    ALLOWED_MERGED_ANDROID_PERMISSIONS,
    PAIRING_QR_ARTIFACT_MARKER,
    merged_manifest_permission_allowlist,
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
    <uses-feature android:name="android.hardware.camera" android:required="false" />
    <uses-feature android:name="android.hardware.camera.flash" android:required="false" />
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
            '    <uses-feature android:name="android.hardware.microphone" '
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
