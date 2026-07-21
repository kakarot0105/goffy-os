from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_rom_system_app import validate_rom_system_app

MANIFEST = """\
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="com.android.alarm.permission.SET_ALARM" />
    <uses-permission android:name="android.permission.CAMERA" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
</manifest>
"""

BUILD = """\
android {
    namespace = "dev.goffy.os"
    defaultConfig {
        applicationId = "dev.goffy.os"
    }
}
"""

TEMPLATE = """\
android_app_import {
    name: "GoffyOS",
    apk: "GoffyOS.apk",
    presigned: true,
    privileged: false,
}
"""


def descriptor() -> dict[str, object]:
    return {
        "schema_version": "goffy.rom-system-app.v1",
        "module_name": "GoffyOS",
        "package_name": "dev.goffy.os",
        "source_apk": "android/app/build/outputs/apk/release/app-release-unsigned.apk",
        "aosp_import_apk": "GoffyOS.apk",
        "aosp_template": "rom/system-app/Android.bp.template",
        "install_partition": "product",
        "install_class": "system_app",
        "privileged": False,
        "platform_signed": False,
        "requires_external_signing": True,
        "requested_permissions": [
            "android.permission.CAMERA",
            "android.permission.INTERNET",
            "android.permission.RECORD_AUDIO",
            "com.android.alarm.permission.SET_ALARM",
        ],
        "privileged_permission_allowlist": [],
        "runtime_permission_policy": {
            "android.permission.CAMERA": "foreground_user_approved_only",
            "android.permission.RECORD_AUDIO": "foreground_user_approved_only",
        },
    }


def write_fixture(tmp_path: Path, payload: dict[str, object]) -> tuple[Path, Path, Path]:
    descriptor_path = tmp_path / "rom" / "system-app" / "goffy-system-app.json"
    template_path = tmp_path / "rom" / "system-app" / "Android.bp.template"
    manifest_path = tmp_path / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    build_path = tmp_path / "android" / "app" / "build.gradle.kts"
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    build_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_text(json.dumps(payload), encoding="utf-8")
    template_path.write_text(TEMPLATE, encoding="utf-8")
    manifest_path.write_text(MANIFEST, encoding="utf-8")
    build_path.write_text(BUILD, encoding="utf-8")
    return descriptor_path, manifest_path, build_path


def test_rom_system_app_descriptor_accepts_current_safe_shape(tmp_path: Path) -> None:
    descriptor_path, manifest_path, build_path = write_fixture(tmp_path, descriptor())

    findings = validate_rom_system_app(
        descriptor_path=descriptor_path,
        manifest_path=manifest_path,
        android_build_path=build_path,
        root=tmp_path,
    )

    assert findings == []


def test_rom_system_app_descriptor_rejects_privileged_mode(tmp_path: Path) -> None:
    payload = descriptor()
    payload["privileged"] = True
    payload["platform_signed"] = True
    payload["privileged_permission_allowlist"] = ["android.permission.WRITE_SECURE_SETTINGS"]
    descriptor_path, manifest_path, build_path = write_fixture(tmp_path, payload)

    findings = validate_rom_system_app(
        descriptor_path=descriptor_path,
        manifest_path=manifest_path,
        android_build_path=build_path,
        root=tmp_path,
    )

    assert "GOFFY ROM descriptor must not be privileged" in findings
    assert "GOFFY ROM descriptor must not request platform signing" in findings
    assert "privileged_permission_allowlist must stay empty" in findings


def test_rom_system_app_descriptor_rejects_missing_external_signing(tmp_path: Path) -> None:
    payload = descriptor()
    payload["requires_external_signing"] = False
    descriptor_path, manifest_path, build_path = write_fixture(tmp_path, payload)

    findings = validate_rom_system_app(
        descriptor_path=descriptor_path,
        manifest_path=manifest_path,
        android_build_path=build_path,
        root=tmp_path,
    )

    assert "unsigned Gradle release APK must require external signing" in findings
    assert "unsigned source_apk must require external signing" in findings


def test_rom_system_app_descriptor_rejects_permission_drift(tmp_path: Path) -> None:
    payload = descriptor()
    payload["requested_permissions"] = ["android.permission.INTERNET"]
    descriptor_path, manifest_path, build_path = write_fixture(tmp_path, payload)

    findings = validate_rom_system_app(
        descriptor_path=descriptor_path,
        manifest_path=manifest_path,
        android_build_path=build_path,
        root=tmp_path,
    )

    assert "descriptor requested_permissions must match Android manifest" in findings


def test_rom_system_app_descriptor_rejects_privileged_template(tmp_path: Path) -> None:
    descriptor_path, manifest_path, build_path = write_fixture(tmp_path, descriptor())
    template_path = tmp_path / "rom" / "system-app" / "Android.bp.template"
    template_path.write_text(
        TEMPLATE.replace("privileged: false", "privileged: true"), encoding="utf-8"
    )

    findings = validate_rom_system_app(
        descriptor_path=descriptor_path,
        manifest_path=manifest_path,
        android_build_path=build_path,
        root=tmp_path,
    )

    assert "AOSP template must not contain privileged: true" in findings
    assert "AOSP template must explicitly keep privileged false" in findings
