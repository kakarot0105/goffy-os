from __future__ import annotations

import argparse
import ast
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
ALLOWED_SUBPROCESS_FILES = {
    ROOT / "hub" / "src" / "goffy_hub" / "tools" / "git_status.py",
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
    "android.permission.RECORD_AUDIO",
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
    "android.hardware.microphone": "false",
}
MAIN_ACTIVITY_NAME = ".MainActivity"
MAIN_ACTIVITY_INTENT_FILTERS = {
    ("android.intent.action.MAIN", ("android.intent.category.LAUNCHER",)),
    (
        "android.intent.action.MAIN",
        ("android.intent.category.DEFAULT", "android.intent.category.HOME"),
    ),
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


def validate_main_activity_intent_filters(path: Path) -> list[str]:
    findings: list[str] = []
    manifest = ET.parse(path).getroot()  # noqa: S314
    name_attribute = f"{{{ANDROID_NAMESPACE}}}name"
    location = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    application = manifest.find("application")
    if application is None:
        findings.append(f"{location}: missing application element")
        return findings

    matching_activities = [
        activity
        for activity in application.findall("activity")
        if activity.attrib.get(name_attribute) == MAIN_ACTIVITY_NAME
        or activity.attrib.get(name_attribute, "").endswith(".MainActivity")
    ]
    if len(matching_activities) != 1:
        findings.append(f"{location}: expected exactly one GOFFY MainActivity")
        return findings

    filters = set()
    filter_count = 0
    for intent_filter in matching_activities[0].findall("intent-filter"):
        filter_count += 1
        actions = [
            action.attrib.get(name_attribute, "")
            for action in intent_filter.findall("action")
            if action.attrib.get(name_attribute)
        ]
        categories = sorted(
            category.attrib.get(name_attribute, "")
            for category in intent_filter.findall("category")
            if category.attrib.get(name_attribute)
        )
        if len(actions) != 1 or not categories:
            findings.append(f"{location}: MainActivity intent filter has unexpected shape")
            continue
        filters.add((actions[0], tuple(categories)))

    if filter_count != len(MAIN_ACTIVITY_INTENT_FILTERS) or filters != MAIN_ACTIVITY_INTENT_FILTERS:
        findings.append(
            f"{location}: MainActivity launcher/home filters mismatch (found {sorted(filters)})"
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


def prohibited_source_patterns(path: Path) -> dict[str, re.Pattern[str]]:
    return dict(PROHIBITED_SOURCE_PATTERNS)


def validate_allowed_subprocess_usage(path: Path, text: str) -> list[str]:
    location = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"{location}: cannot validate subprocess usage ({exc.msg})"]

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            findings.append(f"{location}: subprocess from-import is not allowed")
        if (
            isinstance(node, ast.Attribute)
            and _is_name(node.value, "subprocess")
            and node.attr != "run"
        ):
            findings.append(f"{location}: unsupported subprocess API subprocess.{node.attr}")
        if (
            isinstance(node, ast.Call)
            and _is_subprocess_run_call(node)
            and not _is_allowed_git_status_run_call(node)
        ):
            findings.append(f"{location}: subprocess.run shape does not match git.status policy")
    return sorted(set(findings))


def _is_subprocess_run_call(node: ast.Call) -> bool:
    return (
        isinstance(node.func, ast.Attribute)
        and _is_name(node.func.value, "subprocess")
        and node.func.attr == "run"
    )


def _is_allowed_git_status_run_call(node: ast.Call) -> bool:
    if len(node.args) != 1:
        return False
    command = node.args[0]
    if not isinstance(command, ast.List) or len(command.elts) != 6:
        return False
    if not _is_str_call(command.elts[0], "git_executable"):
        return False
    expected_literals = ["status", "--porcelain=v2", "--branch", "--no-renames"]
    for element, expected in zip(command.elts[1:5], expected_literals, strict=True):
        if not _is_constant(element, expected):
            return False
    if not _is_name(command.elts[5], "untracked_mode"):
        return False

    keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg is not None}
    if set(keywords) != {
        "cwd",
        "check",
        "capture_output",
        "text",
        "encoding",
        "errors",
        "env",
        "timeout",
    }:
        return False
    if not _is_name(keywords["cwd"], "repo_path"):
        return False
    if not _is_constant(keywords["check"], False):
        return False
    if not _is_constant(keywords["capture_output"], True):
        return False
    if not _is_constant(keywords["text"], True):
        return False
    if not _is_constant(keywords["encoding"], "utf-8"):
        return False
    if not _is_constant(keywords["errors"], "replace"):
        return False
    if not _is_name(keywords["timeout"], "timeout_seconds"):
        return False
    env = keywords["env"]
    if not isinstance(env, ast.Dict):
        return False
    env_values = {
        key.value: value.value
        for key, value in zip(env.keys, env.values, strict=True)
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and isinstance(value, ast.Constant)
        and isinstance(value.value, str)
    }
    return env_values == {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    }


def _is_name(node: ast.AST, value: str) -> bool:
    return isinstance(node, ast.Name) and node.id == value


def _is_str_call(node: ast.AST, argument_name: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and _is_name(node.func, "str")
        and len(node.args) == 1
        and not node.keywords
        and _is_name(node.args[0], argument_name)
    )


def _is_constant(node: ast.AST, value: object) -> bool:
    return isinstance(node, ast.Constant) and node.value == value


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
            patterns.update(prohibited_source_patterns(path))
        for label, pattern in patterns.items():
            if pattern.search(text):
                if label == "subprocess API" and path in ALLOWED_SUBPROCESS_FILES:
                    findings.extend(validate_allowed_subprocess_usage(path, text))
                    continue
                findings.append(f"{path.relative_to(ROOT)}: {label}")

    findings.extend(validate_manifest(ANDROID_MANIFEST, ALLOWED_ANDROID_PERMISSIONS))
    findings.extend(validate_main_activity_intent_filters(ANDROID_MANIFEST))
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
