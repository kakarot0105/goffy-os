from __future__ import annotations

import pytest

import goffy_hub.tools.mac_apps as mac_apps
from goffy_hub.registry import ToolRegistry
from goffy_hub.tools.mac_apps import (
    MAX_APPROVED_MAC_APPS,
    MacAppsListInput,
    MacAppsOpenInput,
    build_mac_apps_list_tool,
    build_mac_apps_open_tool,
    list_mac_apps,
    open_mac_app,
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


@pytest.mark.asyncio
async def test_mac_apps_open_uses_approved_bundle_identifier_and_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    class Completed:
        returncode = 0
        stdout = "true\n"

    def fake_open(app: mac_apps.ApprovedMacApp, _timeout_seconds: float) -> Completed:
        calls.append([mac_apps.OPEN_EXECUTABLE, "-b", app.bundle_id])
        return Completed()

    def fake_running(bundle_id: str, _timeout_seconds: float) -> Completed:
        calls.append(
            [
                mac_apps.OSASCRIPT_EXECUTABLE,
                "-e",
                f'application id "{bundle_id}" is running',
            ]
        )
        return Completed()

    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "_run_open_request", fake_open)
    monkeypatch.setattr(mac_apps, "_run_running_check", fake_running)
    tool = build_mac_apps_open_tool(("Safari=com.apple.Safari",), timeout_seconds=1)

    result = await tool.handler(MacAppsOpenInput(display_name="safari"))

    assert result == {
        "status": "running",
        "displayName": "Safari",
        "bundleId": "com.apple.Safari",
        "verified": True,
    }
    assert calls == [
        [mac_apps.OPEN_EXECUTABLE, "-b", "com.apple.Safari"],
        [
            mac_apps.OSASCRIPT_EXECUTABLE,
            "-e",
            'application id "com.apple.Safari" is running',
        ],
    ]


@pytest.mark.asyncio
async def test_mac_apps_open_rejects_unapproved_names_and_registers_confirm_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    tool = build_mac_apps_open_tool(("Safari=com.apple.Safari",), timeout_seconds=1)
    registry = ToolRegistry(confirm_tool_names=frozenset({"mac.apps.open"}))
    registry.register(tool)
    registry.seal()
    await registry.refresh_health()

    with pytest.raises(ValueError, match="approved display name"):
        await open_mac_app(
            MacAppsOpenInput(display_name="Terminal"),
            mac_apps._approved_apps(("Safari=com.apple.Safari",)),
            operation_timeout_seconds=1.0,
        )

    capability = registry.describe()[0]
    assert capability.name == "mac.apps.open"
    assert capability.meta.permission.value == "CONFIRM"
    assert capability.annotations.read_only_hint is False
    assert capability.annotations.destructive_hint is False
    assert capability.annotations.idempotent_hint is False
    assert capability.annotations.open_world_hint is False


def test_mac_apps_open_requires_explicit_registry_authorization() -> None:
    registry = ToolRegistry()

    with pytest.raises(ValueError, match="CONFIRM tools require"):
        registry.register(build_mac_apps_open_tool(("Safari=com.apple.Safari",), timeout_seconds=1))


@pytest.mark.asyncio
async def test_mac_apps_open_uses_internal_deadline_before_registry_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_timeouts: list[float] = []
    running_timeouts: list[float] = []

    class Completed:
        returncode = 0
        stdout = "false\n"

    def fake_open(_app: mac_apps.ApprovedMacApp, timeout_seconds: float) -> Completed:
        captured_timeouts.append(timeout_seconds)
        return Completed()

    def fake_running(_bundle_id: str, timeout_seconds: float) -> Completed:
        running_timeouts.append(timeout_seconds)
        return Completed()

    monkeypatch.setattr(mac_apps, "is_mac_apps_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "mac_app_open_supported", lambda: True)
    monkeypatch.setattr(mac_apps, "_run_open_request", fake_open)
    monkeypatch.setattr(mac_apps, "_run_running_check", fake_running)
    tool = build_mac_apps_open_tool(("Safari=com.apple.Safari",), timeout_seconds=0.5)

    with pytest.raises(ValueError, match="could not verify"):
        await tool.handler(MacAppsOpenInput(display_name="Safari"))

    assert len(captured_timeouts) == 1
    assert captured_timeouts[0] <= 0.25
    assert running_timeouts
    assert all(timeout <= 0.25 for timeout in running_timeouts)


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
