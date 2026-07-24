from __future__ import annotations

import importlib.util
import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic.alias_generators import to_camel

from goffy_hub.registry import ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations

TOOL_NAME = "goffy.rom.features"
TOOL_VERSION = "1.0.0"
FEATURE_PAYLOAD_PATH = Path("rom") / "features" / "goffy-rom-features.json"
SUPPORTED_SCHEMA = "goffy.rom-feature-payload.v1"
MAX_ARTIFACT_BYTES = 96_000
MAX_FEATURES = 8
MAX_FEATURE_COUNT = 100
MAX_FEATURE_TITLE_LENGTH = 96
MAX_RUNTIME_POLICY_LENGTH = 128
MAX_TOOL_ID_LENGTH = 64
MAX_TOOLS_PER_FEATURE = 12
MAX_BLOCKED_ACTIONS = 12
MAX_BLOCKED_ACTION_LENGTH = 64
MAX_NOTES = 4
MAX_NOTE_LENGTH = 160
MAX_PAYLOAD_NAME_LENGTH = 96
MAX_POLICY_LENGTH = 96
IdentifierText = Annotated[str, Field(min_length=1, max_length=MAX_TOOL_ID_LENGTH)]
BlockedActionText = Annotated[str, Field(min_length=1, max_length=MAX_BLOCKED_ACTION_LENGTH)]
NoteText = Annotated[str, Field(min_length=1, max_length=MAX_NOTE_LENGTH)]
RomStatusText = Literal["available", "missing", "invalid"]
RomTargetStageText = Literal["ROM-0"]
RomPerformanceModeText = Literal["GOFFY LITE"]
RomLocalModelPolicyText = Literal["disabled_by_default_observe_only"]
ExecutionTargetText = Literal["PHONE", "MAC", "CLOUD"]

SAFE_TEXT_SLASH_TOKEN = re.compile(
    r"\b(?:[A-Z0-9]{2,8}(?:/[A-Z0-9]{2,8})+|home/system-app|app/default-launcher)\b"
)
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
COMMAND_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:adb|fastboot)\s+"
        r"(?:reboot|shell|sideload|push|install|uninstall|root|remount|"
        r"disable-verity|enable-verity|flash|flashing|oem|erase|wipe|boot|getvar|devices)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:avbctl|magisk)\b", re.IGNORECASE),
    re.compile(r"\b(?:sh|su|pm|cmd|am|rm|dd|mkfs)\s+", re.IGNORECASE),
    re.compile(r"\breboot\s+(?:bootloader|fastboot|recovery)\b", re.IGNORECASE),
    re.compile(r"\bflash\s+(?:boot|system|vendor|vbmeta|image)\b", re.IGNORECASE),
    re.compile(r"\bboot\s+\S+\.img\b", re.IGNORECASE),
    re.compile(r"\bshell\b", re.IGNORECASE),
)


class GoffyRomFeaturesInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GoffyRomFeatureOutput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    feature_index: int = Field(ge=1, le=MAX_FEATURE_COUNT)
    title: str = Field(min_length=1, max_length=MAX_FEATURE_TITLE_LENGTH)
    execution_targets: list[ExecutionTargetText] = Field(max_length=3)
    mcp_tools: list[IdentifierText] = Field(max_length=MAX_TOOLS_PER_FEATURE)
    mcp_tool_count: int = Field(ge=0, le=MAX_FEATURE_COUNT)
    android_permission_count: int = Field(ge=0, le=MAX_FEATURE_COUNT)
    runtime_policy: str = Field(min_length=1, max_length=MAX_RUNTIME_POLICY_LENGTH)
    foreground_only: Literal[True]
    background_access: Literal[False]
    privileged_required: Literal[False]
    rom_destructive_action: Literal[False]
    app_private_destructive_tool_count: int = Field(ge=0, le=MAX_FEATURE_COUNT)

    @field_validator("title", "runtime_policy")
    @classmethod
    def reject_unsafe_display_text(cls, value: str) -> str:
        return _safe_display_text(value, maximum=MAX_RUNTIME_POLICY_LENGTH)

    @field_validator("mcp_tools")
    @classmethod
    def reject_unsafe_tool_ids(cls, value: list[str]) -> list[str]:
        return [_safe_tool_id(item) for item in value]


class GoffyRomFeaturesOutput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    status: RomStatusText
    payload_name: str = Field(min_length=1, max_length=MAX_PAYLOAD_NAME_LENGTH)
    target_stage: RomTargetStageText
    default_performance_mode: RomPerformanceModeText
    rom0_flashable: Literal[False]
    privileged: Literal[False]
    platform_signed: Literal[False]
    rom_destructive_actions_included: Literal[False]
    app_private_destructive_tools_included: bool
    requires_user_selected_home: Literal[True]
    local_model_policy: RomLocalModelPolicyText
    feature_count: int = Field(ge=0, le=MAX_FEATURE_COUNT)
    features: list[GoffyRomFeatureOutput] = Field(max_length=MAX_FEATURES)
    features_truncated: bool
    mcp_tool_count: int = Field(ge=0, le=MAX_FEATURE_COUNT)
    android_permission_count: int = Field(ge=0, le=MAX_FEATURE_COUNT)
    blocked_rom_action_count: int = Field(ge=0, le=MAX_FEATURE_COUNT)
    blocked_rom_actions: list[BlockedActionText] = Field(max_length=MAX_BLOCKED_ACTIONS)
    blocked_rom_actions_truncated: bool
    notes: list[NoteText] = Field(max_length=MAX_NOTES)
    notes_truncated: bool
    destructive_actions: Literal["withheld"]
    checked_feature_payload: bool

    @field_validator("payload_name")
    @classmethod
    def reject_unsafe_payload_name(cls, value: str) -> str:
        return _safe_display_text(value, maximum=MAX_PAYLOAD_NAME_LENGTH)

    @field_validator("blocked_rom_actions")
    @classmethod
    def reject_unsafe_blocked_actions(cls, value: list[str]) -> list[str]:
        return [_safe_identifier(item) for item in value]

    @field_validator("notes")
    @classmethod
    def reject_unsafe_notes(cls, value: list[str]) -> list[str]:
        return [_safe_display_text(item, maximum=MAX_NOTE_LENGTH) for item in value]


async def read_goffy_rom_features(_request: BaseModel, *, root: Path) -> dict[str, Any]:
    return goffy_rom_features_snapshot(root=root)


async def check_goffy_rom_features_health(root: Path) -> bool:
    features_dir = root / FEATURE_PAYLOAD_PATH.parent
    return not features_dir.is_symlink()


def goffy_rom_features_snapshot(*, root: Path) -> dict[str, Any]:
    repo_root = root.expanduser().resolve(strict=False)
    features_dir = repo_root / FEATURE_PAYLOAD_PATH.parent
    if features_dir.is_symlink():
        return _invalid_features("GOFFY ROM feature directory is not a regular local directory")

    descriptor_path = repo_root / FEATURE_PAYLOAD_PATH
    if not descriptor_path.exists():
        return _missing_features()
    if descriptor_path.is_symlink() or not descriptor_path.is_file():
        return _invalid_features("GOFFY ROM feature payload is not a regular local artifact")

    try:
        if descriptor_path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact exceeds ROM feature payload size limit")
        _validate_full_feature_payload_contract(repo_root, descriptor_path)
        descriptor = _read_json_mapping(descriptor_path)
        _validate_payload_policy(descriptor)
        raw_features = _mapping_items(descriptor.get("features"))
        feature_outputs = _feature_outputs(raw_features)
        blocked_actions = tuple(
            dict.fromkeys(
                _safe_identifier(action)
                for action in _string_items(descriptor.get("blocked_rom_actions"))
            )
        )
        notes = tuple(
            dict.fromkeys(
                _safe_display_text(note, maximum=MAX_NOTE_LENGTH)
                for note in _string_items(descriptor.get("notes"))
            )
        )
        mcp_tools = {tool for feature in feature_outputs for tool in feature.mcp_tools}
        android_permission_count = sum(
            feature.android_permission_count for feature in feature_outputs
        )

        return GoffyRomFeaturesOutput(
            status="available",
            payload_name=_safe_display_text(
                _text_value(descriptor.get("payload_name"), "GOFFY ROM-0 Payload"),
                maximum=MAX_PAYLOAD_NAME_LENGTH,
            ),
            target_stage="ROM-0",
            default_performance_mode="GOFFY LITE",
            rom0_flashable=False,
            privileged=False,
            platform_signed=False,
            rom_destructive_actions_included=False,
            app_private_destructive_tools_included=descriptor.get(
                "app_private_destructive_tools_included"
            )
            is True,
            requires_user_selected_home=True,
            local_model_policy="disabled_by_default_observe_only",
            feature_count=len(feature_outputs),
            features=feature_outputs[:MAX_FEATURES],
            features_truncated=len(feature_outputs) > MAX_FEATURES,
            mcp_tool_count=len(mcp_tools),
            android_permission_count=android_permission_count,
            blocked_rom_action_count=len(blocked_actions),
            blocked_rom_actions=list(blocked_actions[:MAX_BLOCKED_ACTIONS]),
            blocked_rom_actions_truncated=len(blocked_actions) > MAX_BLOCKED_ACTIONS,
            notes=list(notes[:MAX_NOTES]),
            notes_truncated=len(notes) > MAX_NOTES,
            destructive_actions="withheld",
            checked_feature_payload=True,
        ).model_dump(mode="json", by_alias=True)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        return _invalid_features("GOFFY ROM feature payload contains unsafe or unsupported fields")


def build_goffy_rom_features_tool(
    root: Path,
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    resolved_root = root.expanduser().resolve(strict=False)

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await read_goffy_rom_features(request, root=resolved_root)

    async def health_probe() -> bool:
        return await check_goffy_rom_features_health(resolved_root)

    return ToolDefinition(
        name=TOOL_NAME,
        title="GOFFY ROM feature payload",
        description=(
            "Read the bounded GOFFY ROM-0 feature payload without exposing source paths, "
            "commands, signing material, privileged authority, or flash/install controls."
        ),
        tool_version=TOOL_VERSION,
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=GoffyRomFeaturesInput,
        output_model=GoffyRomFeaturesOutput,
        handler=handler,
        health_probe=health_probe,
        health_timeout_seconds=health_timeout_seconds,
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )


def _missing_features() -> dict[str, Any]:
    return GoffyRomFeaturesOutput(
        status="missing",
        payload_name="GOFFY ROM-0 Payload",
        target_stage="ROM-0",
        default_performance_mode="GOFFY LITE",
        rom0_flashable=False,
        privileged=False,
        platform_signed=False,
        rom_destructive_actions_included=False,
        app_private_destructive_tools_included=False,
        requires_user_selected_home=True,
        local_model_policy="disabled_by_default_observe_only",
        feature_count=0,
        features=[],
        features_truncated=False,
        mcp_tool_count=0,
        android_permission_count=0,
        blocked_rom_action_count=0,
        blocked_rom_actions=[],
        blocked_rom_actions_truncated=False,
        notes=["GOFFY ROM feature payload is missing"],
        notes_truncated=False,
        destructive_actions="withheld",
        checked_feature_payload=False,
    ).model_dump(mode="json", by_alias=True)


def _invalid_features(note: str) -> dict[str, Any]:
    return GoffyRomFeaturesOutput(
        status="invalid",
        payload_name="GOFFY ROM-0 Payload",
        target_stage="ROM-0",
        default_performance_mode="GOFFY LITE",
        rom0_flashable=False,
        privileged=False,
        platform_signed=False,
        rom_destructive_actions_included=False,
        app_private_destructive_tools_included=False,
        requires_user_selected_home=True,
        local_model_policy="disabled_by_default_observe_only",
        feature_count=0,
        features=[],
        features_truncated=False,
        mcp_tool_count=0,
        android_permission_count=0,
        blocked_rom_action_count=0,
        blocked_rom_actions=[],
        blocked_rom_actions_truncated=False,
        notes=[note],
        notes_truncated=False,
        destructive_actions="withheld",
        checked_feature_payload=False,
    ).model_dump(mode="json", by_alias=True)


def _read_json_mapping(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact exceeds ROM feature payload size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("artifact root must be an object")
    return cast(dict[str, Any], value)


def _validate_payload_policy(descriptor: Mapping[str, Any]) -> None:
    required = {
        "schema_version": SUPPORTED_SCHEMA,
        "target_stage": "ROM-0",
        "default_performance_mode": "GOFFY LITE",
        "rom0_flashable": False,
        "privileged": False,
        "platform_signed": False,
        "rom_destructive_actions_included": False,
        "requires_user_selected_home": True,
        "local_model_policy": "disabled_by_default_observe_only",
    }
    for key, expected_value in required.items():
        if descriptor.get(key) != expected_value:
            raise ValueError(f"ROM feature payload {key} is unsupported")


def _validate_full_feature_payload_contract(repo_root: Path, descriptor_path: Path) -> None:
    validate_rom_feature_payload = _load_feature_payload_validator()
    findings = validate_rom_feature_payload(root=repo_root, descriptor_path=descriptor_path)
    if findings:
        raise ValueError("GOFFY ROM feature payload failed full contract validation")


def _load_feature_payload_validator() -> Callable[..., list[str]]:
    validator_path = _feature_payload_validator_path()
    spec = importlib.util.spec_from_file_location(
        "_goffy_rom_feature_payload_validator",
        validator_path,
    )
    if spec is None or spec.loader is None:
        raise ValueError("GOFFY ROM feature payload validator is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    validator = getattr(module, "validate_rom_feature_payload", None)
    if not callable(validator):
        raise ValueError("GOFFY ROM feature payload validator is invalid")
    return cast(Callable[..., list[str]], validator)


def _feature_payload_validator_path() -> Path:
    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        candidate = parent / "scripts" / "validate_rom_feature_payload.py"
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    raise ValueError("GOFFY ROM feature payload validator is missing")


def _feature_outputs(raw_features: tuple[Mapping[str, Any], ...]) -> list[GoffyRomFeatureOutput]:
    if len(raw_features) > MAX_FEATURE_COUNT:
        raise ValueError("ROM feature payload contains too many features")
    outputs: list[GoffyRomFeatureOutput] = []
    for index, item in enumerate(raw_features, start=1):
        if item.get("included_in_rom0") is not True:
            continue
        if item.get("foreground_only") is not True:
            raise ValueError("ROM-0 feature must remain foreground-only")
        if item.get("background_access") is not False:
            raise ValueError("ROM-0 feature must not request background access")
        if item.get("privileged_required") is not False:
            raise ValueError("ROM-0 feature must not request privileged authority")
        if item.get("rom_destructive_action") is not False:
            raise ValueError("ROM-0 feature must not request ROM-destructive actions")
        outputs.append(
            GoffyRomFeatureOutput(
                feature_index=index,
                title=_safe_display_text(
                    _text_value(item.get("title"), f"GOFFY ROM feature {index}"),
                    maximum=MAX_FEATURE_TITLE_LENGTH,
                ),
                execution_targets=_execution_targets(item.get("execution_targets")),
                mcp_tools=list(_mcp_tools(item.get("mcp_tools"))[:MAX_TOOLS_PER_FEATURE]),
                mcp_tool_count=len(_mcp_tools(item.get("mcp_tools"))),
                android_permission_count=len(_string_items(item.get("android_permissions"))),
                runtime_policy=_safe_display_text(
                    _text_value(item.get("runtime_policy"), "foreground visible audited"),
                    maximum=MAX_RUNTIME_POLICY_LENGTH,
                ),
                foreground_only=True,
                background_access=False,
                privileged_required=False,
                rom_destructive_action=False,
                app_private_destructive_tool_count=len(
                    _string_items(item.get("app_private_destructive_tools"))
                ),
            )
        )
    if not outputs:
        raise ValueError("ROM feature payload contains no included ROM-0 features")
    return outputs


def _execution_targets(value: object) -> list[ExecutionTargetText]:
    targets = _string_items(value)
    if not targets:
        raise ValueError("ROM feature execution targets are missing")
    result: list[ExecutionTargetText] = []
    for target in targets:
        if target not in {"PHONE", "MAC", "CLOUD"}:
            raise ValueError("ROM feature execution target is unsupported")
        result.append(cast(ExecutionTargetText, target))
    return result


def _mcp_tools(value: object) -> tuple[str, ...]:
    return tuple(_safe_tool_id(tool) for tool in _string_items(value))


def _mapping_items(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _string_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _text_value(value: object, default: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    return value


def _safe_display_text(value: str, *, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in normalized):
        raise ValueError("text contains unsupported control characters")
    if _contains_path_like_text(normalized):
        raise ValueError("text contains unsupported path-like content")
    if any(pattern.search(normalized) for pattern in COMMAND_TEXT_PATTERNS):
        raise ValueError("text contains unsupported command-like content")
    if len(normalized) > maximum:
        return normalized[: maximum - 3].rstrip() + "..."
    return normalized or "unknown"


def _safe_identifier(value: str) -> str:
    normalized = value.strip()
    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError("identifier is unsupported")
    return normalized


def _safe_tool_id(value: str) -> str:
    normalized = value.strip()
    if len(normalized) > MAX_TOOL_ID_LENGTH or not TOOL_ID_PATTERN.fullmatch(normalized):
        raise ValueError("tool identifier is unsupported")
    return normalized


def _contains_path_like_text(value: str) -> bool:
    if "file://" in value.casefold() or "\\" in value:
        return True
    without_safe_acronyms = SAFE_TEXT_SLASH_TOKEN.sub("", value)
    return "/" in without_safe_acronyms
