from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = [ROOT / "hub", ROOT / "protocol", ROOT / "android"]
SKIP_PARTS = {".git", ".venv", ".gradle", "build", "__pycache__"}

PROHIBITED_SOURCE_PATTERNS = {
    "subprocess API": re.compile(r"\bsubprocess\b"),
    "os.system": re.compile(r"\bos\.system\s*\("),
    "shell execution": re.compile(r"shell\s*=\s*True"),
    "dynamic eval": re.compile(r"\beval\s*\("),
    "dynamic exec": re.compile(r"\bexec\s*\("),
}

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{30,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}

TEXT_SUFFIXES = {
    ".json",
    ".kts",
    ".kt",
    ".md",
    ".properties",
    ".py",
    ".svg",
    ".toml",
    ".xml",
    ".yml",
    ".yaml",
}

ANDROID_NAMESPACE = "http://schemas.android.com/apk/res/android"
ANDROID_MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
MERGED_MANIFEST_ROOT = ROOT / "android" / "app" / "build" / "intermediates" / "merged_manifests"
ALLOWED_ANDROID_PERMISSIONS = {
    "android.permission.CAMERA",
    "android.permission.INTERNET",
    "com.android.alarm.permission.SET_ALARM",
}
ALLOWED_MERGED_ANDROID_PERMISSIONS = ALLOWED_ANDROID_PERMISSIONS | {
    "android.permission.ACCESS_NETWORK_STATE",
    "dev.goffy.os.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION",
}
ALLOWED_MERGED_ANDROID_PERMISSIONS_BY_VARIANT = {
    "debug": ALLOWED_MERGED_ANDROID_PERMISSIONS,
    "release": ALLOWED_MERGED_ANDROID_PERMISSIONS,
    "modelDebug": ALLOWED_ANDROID_PERMISSIONS
    | {
        "android.permission.ACCESS_NETWORK_STATE",
        "dev.goffy.os.model.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION",
    },
}
REQUIRED_MERGED_ANDROID_VARIANTS = {"debug", "modelDebug", "release"}
ALLOWED_PACKAGE_QUERY_ACTIONS = {"android.intent.action.SET_TIMER"}
ALLOWED_ANDROID_FEATURES = {
    "android.hardware.camera": "false",
    "android.hardware.camera.flash": "false",
}
PAIRING_QR_ARTIFACT_MARKER = "GOFFY_PAIRING_QR_ARTIFACT_V1"
PAIRING_QR_ARTIFACT_FILENAMES = {"goffy-pairing-bundle.svg"}


def candidate_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not SKIP_PARTS.intersection(path.parts)
    )


def validate_manifest(path: Path, allowed_permissions: set[str]) -> list[str]:
    findings: list[str] = []
    manifest = ET.parse(path).getroot()  # noqa: S314
    name_attribute = f"{{{ANDROID_NAMESPACE}}}name"
    location = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path

    permission_elements = manifest.findall("uses-permission")
    permissions = [
        element.attrib.get(name_attribute, "<missing-name>") for element in permission_elements
    ]
    unexpected_permission_tags = sorted(
        {
            child.tag
            for child in manifest
            if child.tag.startswith("uses-permission") and child.tag != "uses-permission"
        }
    )
    if unexpected_permission_tags:
        findings.append(f"{location}: unexpected permission tags {unexpected_permission_tags}")
    if set(permissions) != allowed_permissions or len(permissions) != len(allowed_permissions):
        findings.append(f"{location}: permission allowlist mismatch (found {sorted(permissions)})")

    required_attribute = f"{{{ANDROID_NAMESPACE}}}required"
    feature_elements = manifest.findall("uses-feature")
    features: dict[str, str] = {}
    for feature in feature_elements:
        if set(feature.attrib) != {name_attribute, required_attribute} or list(feature):
            findings.append(f"{location}: hardware feature has unexpected structure")
            continue
        feature_name = feature.attrib[name_attribute]
        if feature_name in features:
            findings.append(f"{location}: duplicate hardware feature {feature_name}")
        features[feature_name] = feature.attrib[required_attribute]
    if features != ALLOWED_ANDROID_FEATURES:
        findings.append(f"{location}: hardware feature allowlist mismatch (found {features})")

    queries_elements = manifest.findall("queries")
    query_actions: list[str] = []
    if len(queries_elements) != 1:
        findings.append(f"{location}: expected exactly one queries element")
    for queries in queries_elements:
        for query in queries:
            if query.tag != "intent" or query.attrib:
                findings.append(f"{location}: unexpected queries entry {query.tag}")
                continue
            children = list(query)
            if len(children) != 1 or children[0].tag != "action":
                findings.append(f"{location}: query intent must contain exactly one action")
                continue
            action = children[0]
            if set(action.attrib) != {name_attribute} or list(action):
                findings.append(f"{location}: query action has unexpected structure")
                continue
            query_actions.append(action.attrib[name_attribute])
    if set(query_actions) != ALLOWED_PACKAGE_QUERY_ACTIONS or len(query_actions) != len(
        ALLOWED_PACKAGE_QUERY_ACTIONS
    ):
        findings.append(
            f"{location}: package-query allowlist mismatch (found {sorted(query_actions)})"
        )
    return findings


def merged_manifests() -> list[Path]:
    return sorted(MERGED_MANIFEST_ROOT.glob("*/process*Manifest/AndroidManifest.xml"))


def merged_manifest_permission_allowlist(variant: str) -> set[str] | None:
    return ALLOWED_MERGED_ANDROID_PERMISSIONS_BY_VARIANT.get(variant)


def validate_merged_manifests(
    manifests: list[Path],
    *,
    manifest_root: Path = MERGED_MANIFEST_ROOT,
) -> list[str]:
    findings: list[str] = []
    variants = {path.relative_to(manifest_root).parts[0] for path in manifests}
    missing_variants = REQUIRED_MERGED_ANDROID_VARIANTS - variants
    unknown_variants = variants - set(ALLOWED_MERGED_ANDROID_PERMISSIONS_BY_VARIANT)
    if missing_variants:
        findings.append(
            "Android merged manifests: expected freshly built debug, modelDebug, "
            f"and release variants (missing {sorted(missing_variants)}, "
            f"found {sorted(variants)})"
        )
    if unknown_variants:
        findings.append(
            "Android merged manifests: unexpected variants "
            f"{sorted(unknown_variants)} (found {sorted(variants)})"
        )
    for manifest in manifests:
        variant = manifest.relative_to(manifest_root).parts[0]
        allowed_permissions = merged_manifest_permission_allowlist(variant)
        if allowed_permissions is None:
            continue
        findings.extend(validate_manifest(manifest, allowed_permissions))
    return findings


def validate_no_pairing_qr_artifact(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    location = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    if path.name in PAIRING_QR_ARTIFACT_FILENAMES:
        findings.append(f"{location}: generated pairing QR artifact")
    if PAIRING_QR_ARTIFACT_MARKER in text:
        findings.append(f"{location}: generated pairing QR artifact marker")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-merged-manifests",
        action="store_true",
        help="also require and validate post-merge debug, modelDebug, and release manifests",
    )
    args = parser.parse_args(argv)
    findings: list[str] = []
    source_files = {
        path
        for source_root in SOURCE_ROOTS
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".kt", ".kts"}
    }

    for path in candidate_files():
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".svg":
            findings.extend(validate_no_pairing_qr_artifact(path, text))
        patterns = dict(SECRET_PATTERNS)
        if path in source_files:
            patterns.update(PROHIBITED_SOURCE_PATTERNS)
        for label, pattern in patterns.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}: {label}")

    findings.extend(validate_manifest(ANDROID_MANIFEST, ALLOWED_ANDROID_PERMISSIONS))
    if args.require_merged_manifests:
        findings.extend(validate_merged_manifests(merged_manifests()))

    if findings:
        print("Security scan failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print(f"Security scan passed ({len(candidate_files())} text files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
