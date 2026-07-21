from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "rom" / "system-app" / "goffy-system-app.json"
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
ANDROID_BUILD = ROOT / "android" / "app" / "build.gradle.kts"
ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
SCHEMA_VERSION = "goffy.rom-system-app.v1"
APPLICATION_ID_PATTERN = re.compile(r'applicationId\s*=\s*"([^"]+)"')
ALLOWED_INSTALL_PARTITIONS = {"system", "system_ext", "product"}
ALLOWED_INSTALL_CLASSES = {"system_app"}
ALLOWED_SYSTEM_APP_PERMISSIONS = {
    "android.permission.CAMERA",
    "android.permission.INTERNET",
    "com.android.alarm.permission.SET_ALARM",
}
BLOCKED_TEMPLATE_PATTERNS = (
    "privileged: true",
    'certificate: "platform"',
    "privapp-permissions",
)


def validate_rom_system_app(
    *,
    descriptor_path: Path = DESCRIPTOR,
    manifest_path: Path = MANIFEST,
    android_build_path: Path = ANDROID_BUILD,
    root: Path = ROOT,
) -> list[str]:
    findings: list[str] = []
    descriptor = load_descriptor(descriptor_path)
    manifest_permissions = manifest_requested_permissions(manifest_path)
    application_id = android_application_id(android_build_path)

    if descriptor.get("schema_version") != SCHEMA_VERSION:
        findings.append("descriptor schema_version mismatch")
    if descriptor.get("package_name") != application_id:
        findings.append("descriptor package_name does not match Android applicationId")
    if descriptor.get("module_name") != "GoffyOS":
        findings.append("descriptor module_name must be GoffyOS")
    if descriptor.get("install_partition") not in ALLOWED_INSTALL_PARTITIONS:
        findings.append("install_partition must be system, system_ext, or product")
    if descriptor.get("install_class") not in ALLOWED_INSTALL_CLASSES:
        findings.append("install_class must remain system_app")
    if descriptor.get("privileged") is not False:
        findings.append("GOFFY ROM descriptor must not be privileged")
    if descriptor.get("platform_signed") is not False:
        findings.append("GOFFY ROM descriptor must not request platform signing")
    if descriptor.get("requires_external_signing") is not True:
        findings.append("unsigned Gradle release APK must require external signing")

    requested_permissions = string_set(descriptor.get("requested_permissions"))
    if requested_permissions != manifest_permissions:
        findings.append("descriptor requested_permissions must match Android manifest")
    unexpected_permissions = manifest_permissions - ALLOWED_SYSTEM_APP_PERMISSIONS
    if unexpected_permissions:
        findings.append(
            "manifest permissions are not approved for ROM system-app: "
            f"{sorted(unexpected_permissions)}"
        )

    priv_allowlist = descriptor.get("privileged_permission_allowlist")
    if priv_allowlist != []:
        findings.append("privileged_permission_allowlist must stay empty")

    source_apk_relative = relative_path_value(descriptor.get("source_apk"))
    if source_apk_relative is None or source_apk_relative.parts[:4] != (
        "android",
        "app",
        "build",
        "outputs",
    ):
        findings.append("source_apk must be a relative Android build output path")
    elif source_apk_relative.name.endswith("-unsigned.apk") and (
        descriptor.get("requires_external_signing") is not True
    ):
        findings.append("unsigned source_apk must require external signing")

    import_apk = str(descriptor.get("aosp_import_apk", ""))
    if import_apk != "GoffyOS.apk":
        findings.append("aosp_import_apk must be GoffyOS.apk")

    template_path = relative_repo_path(descriptor.get("aosp_template"), root=root)
    if template_path is None or not template_path.is_file():
        findings.append("aosp_template must point to an existing repo file")
    elif template_findings := validate_template(template_path):
        findings.extend(template_findings)

    runtime_policy = mapping_value(descriptor.get("runtime_permission_policy"))
    if runtime_policy.get("android.permission.CAMERA") != "foreground_user_approved_only":
        findings.append("CAMERA runtime policy must remain foreground_user_approved_only")

    return findings


def load_descriptor(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ROM system-app descriptor must be a JSON object")
    return payload


def manifest_requested_permissions(path: Path) -> set[str]:
    manifest = ET.parse(path).getroot()  # noqa: S314
    name_attribute = f"{{{ANDROID_NAMESPACE}}}name"
    return {
        str(element.attrib.get(name_attribute, ""))
        for element in manifest.findall("uses-permission")
        if element.attrib.get(name_attribute)
    }


def android_application_id(path: Path) -> str:
    match = APPLICATION_ID_PATTERN.search(path.read_text(encoding="utf-8"))
    return match.group(1) if match else ""


def string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value}


def mapping_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def relative_repo_path(value: object, *, root: Path) -> Path | None:
    path = relative_path_value(value)
    return root / path if path is not None else None


def relative_path_value(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path


def validate_template(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    findings: list[str] = []
    if "android_app_import" not in text:
        findings.append("AOSP template must use android_app_import")
    for pattern in BLOCKED_TEMPLATE_PATTERNS:
        if pattern in text:
            findings.append(f"AOSP template must not contain {pattern}")
    if 'name: "GoffyOS"' not in text:
        findings.append("AOSP template module name must be GoffyOS")
    if 'apk: "GoffyOS.apk"' not in text:
        findings.append("AOSP template must import GoffyOS.apk")
    if "presigned: true" not in text:
        findings.append("AOSP template must use presigned APK import")
    if "privileged: false" not in text:
        findings.append("AOSP template must explicitly keep privileged false")
    return findings


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate GOFFY ROM system-app packaging metadata.",
    )
    parser.add_argument("--descriptor", type=Path, default=DESCRIPTOR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--android-build", type=Path, default=ANDROID_BUILD)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        findings = validate_rom_system_app(
            descriptor_path=args.descriptor,
            manifest_path=args.manifest,
            android_build_path=args.android_build,
        )
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("GOFFY ROM system-app validation failed")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("GOFFY ROM system-app validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
