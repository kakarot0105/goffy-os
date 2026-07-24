from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from goffy_hub.registry import ToolRegistry
from goffy_hub.tools.rom_features import (
    TOOL_NAME,
    build_goffy_rom_features_tool,
    goffy_rom_features_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_PAYLOAD_RELATIVE_PATH = Path("rom") / "features" / "goffy-rom-features.json"
ANDROID_TOOL_NAMES_RELATIVE_PATH = (
    Path("android")
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


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def full_feature_payload() -> dict[str, Any]:
    payload = json.loads((REPO_ROOT / FEATURE_PAYLOAD_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return copy.deepcopy(payload)


def write_full_contract_fixture(
    root: Path,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    descriptor = payload if payload is not None else full_feature_payload()
    write_json(root / FEATURE_PAYLOAD_RELATIVE_PATH, descriptor)
    _copy_descriptor(root, descriptor["system_app_descriptor"])
    _copy_descriptor(root, descriptor["product_overlay_descriptor"])
    _copy_android_tool_names(root)
    for feature in descriptor["features"]:
        source_module = feature["source_module"]
        assert isinstance(source_module, str)
        _create_source_stub(root, source_module)
    return descriptor


def test_rom_features_reports_missing_payload(tmp_path: Path) -> None:
    result = goffy_rom_features_snapshot(root=tmp_path)

    assert result["status"] == "missing"
    assert result["checkedFeaturePayload"] is False
    assert result["destructiveActions"] == "withheld"
    assert result["features"] == []


def test_rom_features_summarizes_payload_without_paths_or_commands(tmp_path: Path) -> None:
    write_full_contract_fixture(tmp_path)

    result = goffy_rom_features_snapshot(root=tmp_path)
    serialized = json.dumps(result)

    assert result["status"] == "available"
    assert result["payloadName"] == "GOFFY ROM-0 Jarvis Payload"
    assert result["targetStage"] == "ROM-0"
    assert result["defaultPerformanceMode"] == "GOFFY LITE"
    assert result["rom0Flashable"] is False
    assert result["privileged"] is False
    assert result["platformSigned"] is False
    assert result["romDestructiveActionsIncluded"] is False
    assert result["requiresUserSelectedHome"] is True
    assert result["featureCount"] == 8
    assert result["mcpToolCount"] == 16
    assert result["appPrivateDestructiveToolsIncluded"] is True
    assert result["features"][0]["title"] == "GOFFY Home Surface"
    assert result["features"][0]["mcpTools"] == ["phone.device.info"]
    assert result["blockedRomActionCount"] == 11
    assert "unlock_bootloader" in result["blockedRomActions"]
    assert "flash_image" in result["blockedRomActions"]
    assert "source_module" not in serialized
    assert "android/app/src" not in serialized
    assert "hub/src" not in serialized
    assert "fastboot" not in serialized


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload.__setitem__("privileged", True),
        lambda payload: payload.__setitem__("app_private_destructive_tools_included", False),
        lambda payload: payload["features"][0].__setitem__("background_access", True),
        lambda payload: payload["features"][0].__setitem__("title", "/Users/example/private"),
        lambda payload: payload["features"][0].__setitem__(
            "title",
            "Run fastboot flash boot boot.img",
        ),
    ],
)
def test_rom_features_fails_closed_for_unsafe_payload(
    tmp_path: Path,
    mutator: Callable[[dict[str, Any]], None],
) -> None:
    payload = full_feature_payload()
    mutator(payload)
    write_full_contract_fixture(tmp_path, payload)

    result = goffy_rom_features_snapshot(root=tmp_path)

    assert result["status"] == "invalid"
    assert result["checkedFeaturePayload"] is False
    assert result["destructiveActions"] == "withheld"


def test_rom_features_fails_closed_when_referenced_system_descriptor_drifts(
    tmp_path: Path,
) -> None:
    descriptor = write_full_contract_fixture(tmp_path)
    system_app_path = tmp_path / descriptor["system_app_descriptor"]
    system_app = json.loads(system_app_path.read_text(encoding="utf-8"))
    system_app["privileged"] = True
    write_json(system_app_path, system_app)

    result = goffy_rom_features_snapshot(root=tmp_path)

    assert result["status"] == "invalid"
    assert result["checkedFeaturePayload"] is False
    assert result["destructiveActions"] == "withheld"


@pytest.mark.asyncio
async def test_rom_features_tool_registers_with_safe_metadata(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.register(build_goffy_rom_features_tool(tmp_path, timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    capability = registry.discover(TOOL_NAME)[0]

    assert capability.name == TOOL_NAME
    assert capability.meta.permission.value == "SAFE"
    assert capability.meta.execution_target.value == "MAC"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False
    assert capability.input_schema["properties"] == {}
    assert capability.output_schema["properties"]["features"]["maxItems"] == 8
    assert capability.output_schema["properties"]["blockedRomActions"]["maxItems"] == 12


def _copy_descriptor(root: Path, relative_path: object) -> None:
    assert isinstance(relative_path, str)
    destination = root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        (REPO_ROOT / relative_path).read_text(encoding="utf-8"), encoding="utf-8"
    )


def _copy_android_tool_names(root: Path) -> None:
    destination = root / ANDROID_TOOL_NAMES_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        (REPO_ROOT / ANDROID_TOOL_NAMES_RELATIVE_PATH).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def _create_source_stub(root: Path, relative_path: str) -> None:
    destination = root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = REPO_ROOT / relative_path
    if source.is_dir() or destination.suffix == "":
        destination.mkdir(parents=True, exist_ok=True)
    else:
        destination.write_text("stub", encoding="utf-8")
