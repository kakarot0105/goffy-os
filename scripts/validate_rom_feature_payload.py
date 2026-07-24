from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "rom" / "features" / "goffy-rom-features.json"
ANDROID_TOOL_NAMES = (
    ROOT
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "dev"
    / "goffy"
    / "os"
    / "protocol"
    / "GoffyToolNames.kt"
)
SCHEMA_VERSION = "goffy.rom-feature-payload.v1"
SYSTEM_APP_SCHEMA_VERSION = "goffy.rom-system-app.v1"
PRODUCT_OVERLAY_SCHEMA_VERSION = "goffy.rom-product-overlay.v1"
FEATURE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,48}$")
REQUIRED_FEATURE_IDS = {
    "agent_loop_timeline",
    "charging_dock_awake",
    "foreground_voice_camera",
    "home_surface",
    "local_intent_fallback",
    "phone_tools",
    "rom_status",
    "secure_mac_hub",
}
ALLOWED_EXECUTION_TARGETS = {"PHONE", "MAC", "CLOUD"}
ALLOWED_ANDROID_PERMISSIONS = {
    "android.permission.CAMERA",
    "android.permission.INTERNET",
    "android.permission.RECORD_AUDIO",
    "com.android.alarm.permission.SET_ALARM",
}
FOREGROUND_ONLY_PERMISSIONS = {
    "android.permission.CAMERA",
    "android.permission.RECORD_AUDIO",
}
ALLOWED_MCP_TOOLS = {
    "goffy.rom.checklist",
    "goffy.rom.status",
    "mac.system_info",
    "phone.battery.status",
    "phone.device.info",
    "phone.flashlight.set",
    "phone.memory.forget",
    "phone.memory.forget_all",
    "phone.memory.list",
    "phone.memory.remember",
    "phone.memory.update",
    "phone.note.create",
    "phone.ocr.read",
    "phone.qr.read",
    "phone.timer.create",
}
EXPECTED_FEATURE_TARGETS = {
    "agent_loop_timeline": {"PHONE", "MAC", "CLOUD"},
    "charging_dock_awake": {"PHONE"},
    "foreground_voice_camera": {"PHONE"},
    "home_surface": {"PHONE"},
    "local_intent_fallback": {"PHONE"},
    "phone_tools": {"PHONE"},
    "rom_status": {"MAC"},
    "secure_mac_hub": {"MAC"},
}
EXPECTED_FEATURE_ANDROID_PERMISSIONS = {
    "agent_loop_timeline": set(),
    "charging_dock_awake": set(),
    "foreground_voice_camera": {
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO",
    },
    "home_surface": set(),
    "local_intent_fallback": set(),
    "phone_tools": {
        "android.permission.CAMERA",
        "com.android.alarm.permission.SET_ALARM",
    },
    "rom_status": set(),
    "secure_mac_hub": {"android.permission.INTERNET"},
}
EXPECTED_FEATURE_MCP_TOOLS = {
    "agent_loop_timeline": set(),
    "charging_dock_awake": set(),
    "foreground_voice_camera": {"phone.ocr.read", "phone.qr.read"},
    "home_surface": {"phone.device.info"},
    "local_intent_fallback": set(),
    "phone_tools": {
        "phone.battery.status",
        "phone.device.info",
        "phone.flashlight.set",
        "phone.memory.forget",
        "phone.memory.forget_all",
        "phone.memory.list",
        "phone.memory.remember",
        "phone.memory.update",
        "phone.note.create",
        "phone.ocr.read",
        "phone.qr.read",
        "phone.timer.create",
    },
    "rom_status": {"goffy.rom.checklist", "goffy.rom.status"},
    "secure_mac_hub": {"goffy.rom.checklist", "goffy.rom.status", "mac.system_info"},
}
EXPECTED_FEATURE_APP_PRIVATE_DESTRUCTIVE_TOOLS = {
    "agent_loop_timeline": set(),
    "charging_dock_awake": set(),
    "foreground_voice_camera": set(),
    "home_surface": set(),
    "local_intent_fallback": set(),
    "phone_tools": {"phone.memory.forget", "phone.memory.forget_all"},
    "rom_status": set(),
    "secure_mac_hub": set(),
}
REQUIRED_BLOCKED_ACTIONS = {
    "background_camera",
    "background_microphone",
    "disable_verity",
    "flash_image",
    "platform_signing",
    "privileged_permission_grants",
    "reboot_bootloader",
    "root_or_su",
    "unlock_bootloader",
    "unrestricted_shell",
    "wipe_data",
}
REQUIRED_SOURCE_BASIS_MARKERS = (
    "PRODUCT_PACKAGES",
    "AndroidProducts.mk",
    "privileged permission allowlists",
    "GSI",
    "DSU",
)
BLOCKED_TEXT_PATTERNS = (
    "fastboot flashing unlock",
    "fastboot oem unlock",
    "adb reboot bootloader",
    "avbctl disable-verification",
    "disable-verity",
    "privileged: true",
    "platform key",
    "privapp-permissions",
)


def validate_rom_feature_payload(
    *,
    descriptor_path: Path = DESCRIPTOR,
    root: Path = ROOT,
) -> list[str]:
    findings: list[str] = []
    descriptor = load_descriptor(descriptor_path)

    if descriptor.get("schema_version") != SCHEMA_VERSION:
        findings.append("descriptor schema_version mismatch")
    if descriptor.get("target_stage") != "ROM-0":
        findings.append("target_stage must remain ROM-0")
    if descriptor.get("default_performance_mode") != "GOFFY LITE":
        findings.append("default_performance_mode must remain GOFFY LITE")
    if descriptor.get("rom0_flashable") is not False:
        findings.append("ROM-0 feature payload must not claim to be flashable")
    if descriptor.get("privileged") is not False:
        findings.append("ROM-0 feature payload must remain non-privileged")
    if descriptor.get("platform_signed") is not False:
        findings.append("ROM-0 feature payload must not request platform signing")
    if "destructive_actions_included" in descriptor:
        findings.append(
            "destructive_actions_included is ambiguous; use "
            "rom_destructive_actions_included and app_private_destructive_tools_included"
        )
    if descriptor.get("rom_destructive_actions_included") is not False:
        findings.append("ROM-0 feature payload must not include ROM/system destructive actions")
    if descriptor.get("app_private_destructive_tools_included") is not True:
        findings.append(
            "app_private_destructive_tools_included must truthfully acknowledge memory forget tools"
        )
    if descriptor.get("requires_user_selected_home") is not True:
        findings.append("ROM-0 feature payload must keep HOME user-selected")
    if descriptor.get("local_model_policy") != "disabled_by_default_observe_only":
        findings.append("local_model_policy must remain disabled_by_default_observe_only")

    findings.extend(validate_source_basis(descriptor.get("source_basis")))
    findings.extend(validate_blocked_actions(descriptor.get("blocked_rom_actions")))

    system_app_path = relative_repo_path(descriptor.get("system_app_descriptor"), root=root)
    product_overlay_path = relative_repo_path(
        descriptor.get("product_overlay_descriptor"),
        root=root,
    )
    findings.extend(validate_system_app_descriptor(system_app_path))
    findings.extend(validate_product_overlay_descriptor(product_overlay_path))

    features = list_value(descriptor.get("features"))
    findings.extend(validate_features(features, root=root))
    findings.extend(
        validate_phone_tool_source_coverage(
            features,
            android_tool_names_path=root / ANDROID_TOOL_NAMES.relative_to(ROOT),
        )
    )
    findings.extend(validate_no_blocked_text(descriptor))

    return findings


def validate_source_basis(value: object) -> list[str]:
    findings: list[str] = []
    source_basis = string_list(value)
    if len(source_basis) < len(REQUIRED_SOURCE_BASIS_MARKERS):
        findings.append("source_basis must include current AOSP/GSI/DSU reuse decisions")
    joined = "\n".join(source_basis)
    for marker in REQUIRED_SOURCE_BASIS_MARKERS:
        if marker not in joined:
            findings.append(f"source_basis must mention {marker}")
    return findings


def validate_blocked_actions(value: object) -> list[str]:
    blocked_actions = set(string_list(value))
    findings: list[str] = []
    missing = REQUIRED_BLOCKED_ACTIONS - blocked_actions
    extra = blocked_actions - REQUIRED_BLOCKED_ACTIONS
    if missing:
        findings.append(f"blocked_actions missing required entries: {sorted(missing)}")
    if extra:
        findings.append(f"blocked_actions contains unreviewed entries: {sorted(extra)}")
    return findings


def validate_system_app_descriptor(path: Path | None) -> list[str]:
    if path is None or not path.is_file():
        return ["system_app_descriptor must point to an existing repo file"]
    descriptor = load_descriptor(path)
    findings: list[str] = []
    if descriptor.get("schema_version") != SYSTEM_APP_SCHEMA_VERSION:
        findings.append("system_app_descriptor schema_version mismatch")
    if descriptor.get("module_name") != "GoffyOS":
        findings.append("system_app_descriptor module_name must be GoffyOS")
    if descriptor.get("privileged") is not False:
        findings.append("system_app_descriptor must remain non-privileged")
    if descriptor.get("platform_signed") is not False:
        findings.append("system_app_descriptor must not request platform signing")
    if descriptor.get("privileged_permission_allowlist") != []:
        findings.append("system_app_descriptor privileged allowlist must remain empty")
    home_surface = mapping_value(descriptor.get("home_surface"))
    if home_surface.get("policy") != "user_selectable_default_home":
        findings.append("system_app_descriptor must keep user-selectable HOME policy")
    return findings


def validate_product_overlay_descriptor(path: Path | None) -> list[str]:
    if path is None or not path.is_file():
        return ["product_overlay_descriptor must point to an existing repo file"]
    descriptor = load_descriptor(path)
    findings: list[str] = []
    if descriptor.get("schema_version") != PRODUCT_OVERLAY_SCHEMA_VERSION:
        findings.append("product_overlay_descriptor schema_version mismatch")
    if descriptor.get("required_module") != "GoffyOS":
        findings.append("product_overlay_descriptor required_module must be GoffyOS")
    if descriptor.get("flashable") is not False:
        findings.append("product_overlay_descriptor must not claim flashable")
    if descriptor.get("destructive_actions_included") is not False:
        findings.append("product_overlay_descriptor must not include destructive actions")
    return findings


def validate_features(features: list[object], *, root: Path) -> list[str]:
    findings: list[str] = []
    if not features:
        return ["features must be a non-empty list"]

    feature_objects = [feature for feature in features if isinstance(feature, Mapping)]
    if len(feature_objects) != len(features):
        findings.append("features must contain only JSON objects")

    ids = [str(feature.get("id", "")) for feature in feature_objects]
    id_set = set(ids)
    duplicates = sorted({feature_id for feature_id in ids if ids.count(feature_id) > 1})
    if duplicates:
        findings.append(f"feature ids must be unique: {duplicates}")
    if id_set != REQUIRED_FEATURE_IDS:
        findings.append(
            f"features must exactly cover ROM-0 feature ids: {sorted(REQUIRED_FEATURE_IDS)}"
        )

    for feature in feature_objects:
        findings.extend(validate_feature(feature, root=root))
    return findings


def validate_feature(feature: Mapping[str, object], *, root: Path) -> list[str]:
    findings: list[str] = []
    feature_id = str(feature.get("id", ""))
    if FEATURE_ID_PATTERN.fullmatch(feature_id) is None:
        findings.append("feature id must be lowercase snake_case")
    if feature.get("included_in_rom0") is not True:
        findings.append(f"{feature_id}: included_in_rom0 must stay true for ROM-0 payload")
    if feature.get("privileged_required") is not False:
        findings.append(f"{feature_id}: privileged_required must remain false")
    if feature.get("background_access") is not False:
        findings.append(f"{feature_id}: background_access must remain false")
    if "destructive_action" in feature:
        findings.append(
            f"{feature_id}: destructive_action is ambiguous; use rom_destructive_action"
        )
    if feature.get("rom_destructive_action") is not False:
        findings.append(f"{feature_id}: rom_destructive_action must remain false")
    if feature.get("foreground_only") is not True:
        findings.append(f"{feature_id}: foreground_only must remain true")

    execution_targets = set(string_list(feature.get("execution_targets")))
    if not execution_targets or not execution_targets.issubset(ALLOWED_EXECUTION_TARGETS):
        findings.append(f"{feature_id}: execution_targets contain unsupported targets")
    expected_targets = EXPECTED_FEATURE_TARGETS.get(feature_id)
    if expected_targets is not None and execution_targets != expected_targets:
        findings.append(
            f"{feature_id}: execution_targets must be exactly {sorted(expected_targets)}"
        )

    android_permissions = set(string_list(feature.get("android_permissions")))
    unexpected_permissions = android_permissions - ALLOWED_ANDROID_PERMISSIONS
    if unexpected_permissions:
        findings.append(
            f"{feature_id}: android_permissions not approved: {sorted(unexpected_permissions)}"
        )
    expected_permissions = EXPECTED_FEATURE_ANDROID_PERMISSIONS.get(feature_id)
    if expected_permissions is not None and android_permissions != expected_permissions:
        findings.append(
            f"{feature_id}: android_permissions must be exactly {sorted(expected_permissions)}"
        )
    if android_permissions.intersection(FOREGROUND_ONLY_PERMISSIONS) and (
        "foreground" not in str(feature.get("runtime_policy", "")).casefold()
        or feature.get("foreground_only") is not True
    ):
        findings.append(f"{feature_id}: camera/microphone permissions require foreground policy")

    tools = set(string_list(feature.get("mcp_tools")))
    unexpected_tools = tools - ALLOWED_MCP_TOOLS
    if unexpected_tools:
        findings.append(
            f"{feature_id}: mcp_tools not in ROM-0 allowlist: {sorted(unexpected_tools)}"
        )
    expected_tools = EXPECTED_FEATURE_MCP_TOOLS.get(feature_id)
    if expected_tools is not None and tools != expected_tools:
        findings.append(f"{feature_id}: mcp_tools must be exactly {sorted(expected_tools)}")

    app_private_destructive_tools = set(string_list(feature.get("app_private_destructive_tools")))
    expected_destructive_tools = EXPECTED_FEATURE_APP_PRIVATE_DESTRUCTIVE_TOOLS.get(feature_id)
    if expected_destructive_tools is not None and (
        app_private_destructive_tools != expected_destructive_tools
    ):
        findings.append(
            f"{feature_id}: app_private_destructive_tools must be exactly "
            f"{sorted(expected_destructive_tools)}"
        )
    if app_private_destructive_tools - tools:
        findings.append(
            f"{feature_id}: app_private_destructive_tools must also appear in mcp_tools"
        )

    source_module = relative_repo_path(feature.get("source_module"), root=root)
    if source_module is None or not source_module.exists():
        findings.append(f"{feature_id}: source_module must point to an existing repo path")

    if not isinstance(feature.get("runtime_policy"), str) or not feature.get("runtime_policy"):
        findings.append(f"{feature_id}: runtime_policy must be a non-empty string")
    if not isinstance(feature.get("audit_policy"), str) or not feature.get("audit_policy"):
        findings.append(f"{feature_id}: audit_policy must be a non-empty string")

    return findings


def validate_phone_tool_source_coverage(
    features: list[object],
    *,
    android_tool_names_path: Path,
) -> list[str]:
    feature_objects = [feature for feature in features if isinstance(feature, Mapping)]
    descriptor_phone_tools = {
        tool
        for feature in feature_objects
        for tool in string_list(feature.get("mcp_tools"))
        if tool.startswith("phone.")
    }
    source_phone_tools = source_phone_tool_names(android_tool_names_path)
    if descriptor_phone_tools != source_phone_tools:
        return [
            "descriptor PHONE tools must match Android GoffyToolNames.kt constants "
            f"(missing={sorted(source_phone_tools - descriptor_phone_tools)}, "
            f"extra={sorted(descriptor_phone_tools - source_phone_tools)})"
        ]
    return []


def source_phone_tool_names(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r'const val PHONE_[A-Z0-9_]+_TOOL = "(phone\.[^"]+)"', text))


def validate_no_blocked_text(value: object) -> list[str]:
    text = json.dumps(value, sort_keys=True)
    findings: list[str] = []
    for pattern in BLOCKED_TEXT_PATTERNS:
        if pattern in text:
            findings.append(f"descriptor must not contain blocked pattern: {pattern}")
    return findings


def load_descriptor(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ROM feature payload descriptor must be a JSON object")
    return payload


def list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def mapping_value(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def relative_repo_path(value: object, *, root: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return root / path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate GOFFY ROM-0 feature payload metadata.",
    )
    parser.add_argument("--descriptor", type=Path, default=DESCRIPTOR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        findings = validate_rom_feature_payload(descriptor_path=args.descriptor)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("GOFFY ROM feature payload validation failed")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("GOFFY ROM feature payload validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
