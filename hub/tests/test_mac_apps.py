from __future__ import annotations

import pytest

import goffy_hub.tools.mac_apps as mac_apps
from goffy_hub.registry import ToolRegistry
from goffy_hub.tools.mac_apps import (
    MAX_APPROVED_MAC_APPS,
    MacAppsListInput,
    build_mac_apps_list_tool,
    list_mac_apps,
)


@pytest.mark.asyncio
async def test_mac_apps_list_returns_bounded_approved_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    tool = build_mac_apps_list_tool(
        (
            "Safari=com.apple.Safari",
            "Terminal=com.apple.Terminal",
        ),
        timeout_seconds=1,
    )

    result = await tool.handler(MacAppsListInput(max_entries=1))

    assert result == {
        "status": "available",
        "appCount": 2,
        "truncated": True,
        "entries": [
            {
                "appIndex": 0,
                "displayName": "Safari",
                "bundleId": "com.apple.Safari",
            }
        ],
    }


@pytest.mark.asyncio
async def test_mac_apps_list_rejects_unconfigured_or_non_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: False)
    tool = build_mac_apps_list_tool(("Safari=com.apple.Safari",), timeout_seconds=1)

    assert await tool.health_probe() is False
    with pytest.raises(ValueError, match="requires macOS"):
        await list_mac_apps(
            MacAppsListInput(), mac_apps._approved_apps(("Safari=com.apple.Safari",))
        )
    with pytest.raises(ValueError, match="requires 1.."):
        build_mac_apps_list_tool((), timeout_seconds=1)


@pytest.mark.asyncio
async def test_mac_apps_tool_registers_with_safe_mcp_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    registry = ToolRegistry()
    registry.register(build_mac_apps_list_tool(("Safari=com.apple.Safari",), timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    capability = registry.describe()[0]

    assert capability.name == "mac.apps.list"
    assert capability.meta.permission.value == "SAFE"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False
    assert capability.annotations.idempotent_hint is True
    assert capability.annotations.open_world_hint is False


@pytest.mark.parametrize(
    "entry",
    [
        "Safari",
        "Safari=/Applications/Safari.app",
        "Safari=com..apple.Safari",
        "Safari\u202e=com.apple.Safari",
        "Bad/Name=com.apple.Safari",
    ],
)
def test_mac_apps_allowlist_rejects_unsafe_entries(entry: str) -> None:
    with pytest.raises(ValueError, match="GOFFY_MAC_APP_ALLOWLIST"):
        build_mac_apps_list_tool((entry,), timeout_seconds=1)


def test_mac_apps_allowlist_rejects_duplicates_and_unbounded_size() -> None:
    with pytest.raises(ValueError, match="unique"):
        build_mac_apps_list_tool(
            ("Safari=com.apple.Safari", "Safari=com.apple.MobileSafari"),
            timeout_seconds=1,
        )
    with pytest.raises(ValueError, match="unique"):
        build_mac_apps_list_tool(
            ("Safari=com.apple.Safari", "Browser=com.apple.Safari"),
            timeout_seconds=1,
        )
    too_many = tuple(
        f"App {index}=com.example.App{index}" for index in range(MAX_APPROVED_MAC_APPS + 1)
    )
    with pytest.raises(ValueError, match="requires 1.."):
        build_mac_apps_list_tool(too_many, timeout_seconds=1)
