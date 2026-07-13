import platform

import pytest

from goffy_hub.registry import ToolHealthStatus, ToolRegistry
from goffy_hub.tool_health import ToolHealthMonitor
from goffy_hub.tools import build_mac_system_tool


@pytest.mark.asyncio
async def test_monitor_tracks_health_transitions_without_expanding_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    registry = ToolRegistry()
    registry.register(build_mac_system_tool(1, 0.1))
    registry.seal()
    monitor = ToolHealthMonitor(
        registry,
        interval_seconds=30,
    )

    initial = await monitor.initialize()
    unchanged = await monitor.check_now()
    monkeypatch.setattr(platform, "system", lambda: "")
    unavailable = await monitor.check_now()
    duplicate = await monitor.check_now()
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    restored = await monitor.check_now()

    assert initial.changed is True
    assert unchanged.changed is False
    assert unavailable.changed is True
    assert duplicate.changed is False
    assert restored.changed is True
    assert unavailable.tools[0].status is ToolHealthStatus.UNAVAILABLE
    assert restored.tools[0].status is ToolHealthStatus.HEALTHY
    assert [tool.name for tool in registry.describe()] == ["mac.system_info"]


@pytest.mark.asyncio
async def test_first_check_performs_initial_health_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    registry = ToolRegistry()
    registry.register(build_mac_system_tool(1, 0.1))
    registry.seal()
    monitor = ToolHealthMonitor(
        registry,
        interval_seconds=30,
    )
    monkeypatch.setattr(platform, "machine", lambda: "")

    report = await monitor.check_now()
    repeated = await monitor.check_now()

    assert report.changed is False
    assert repeated.changed is False
    assert registry.describe() == []


@pytest.mark.asyncio
async def test_unexpected_monitor_failure_marks_all_tools_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    registry = ToolRegistry()
    registry.register(build_mac_system_tool(1, 0.1))
    registry.seal()
    monitor = ToolHealthMonitor(registry, interval_seconds=30)
    await monitor.initialize()

    async def fail_refresh() -> None:
        raise RuntimeError("unexpected internal failure")

    monkeypatch.setattr(registry, "refresh_health", fail_refresh)
    report = await monitor.check_now()

    assert report.changed is True
    assert report.tools[0].status is ToolHealthStatus.UNAVAILABLE
    assert registry.describe() == []
