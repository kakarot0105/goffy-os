from __future__ import annotations

from types import SimpleNamespace

import psutil
import pytest

import goffy_hub.tools.mac_processes as mac_processes
from goffy_hub.registry import ToolRegistry
from goffy_hub.tools.mac_processes import (
    MAX_PROCESS_ENTRIES,
    MacProcessesListInput,
    build_mac_processes_list_tool,
    list_mac_processes,
)


class FakeProcess:
    def __init__(
        self, info: dict[str, object] | None = None, error: Exception | None = None
    ) -> None:
        self._info = info or {}
        self._error = error

    @property
    def info(self) -> dict[str, object]:
        if self._error is not None:
            raise self._error
        return self._info


@pytest.mark.asyncio
async def test_mac_processes_returns_bounded_read_only_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mac_processes.psutil,
        "process_iter",
        lambda _attrs: iter(
            [
                FakeProcess(
                    {
                        "pid": 100,
                        "name": "WindowServer",
                        "status": "sleeping",
                        "memory_info": SimpleNamespace(rss=200),
                        "create_time": 1_784_620_000.9,
                    }
                ),
                FakeProcess(
                    {
                        "pid": 200,
                        "name": "/Users/example/private/secret-agent",
                        "status": "running",
                        "memory_info": SimpleNamespace(rss=400),
                        "create_time": 1_784_620_001.1,
                    }
                ),
            ]
        ),
    )

    result = await list_mac_processes(MacProcessesListInput(max_entries=10))

    assert result == {
        "status": "available",
        "processCount": 2,
        "skippedCount": 0,
        "truncated": False,
        "entries": [
            {
                "pid": 200,
                "name": "secret-agent",
                "status": "running",
                "rssBytes": 400,
                "createTimeEpochSeconds": 1_784_620_001,
            },
            {
                "pid": 100,
                "name": "WindowServer",
                "status": "sleeping",
                "rssBytes": 200,
                "createTimeEpochSeconds": 1_784_620_000,
            },
        ],
    }
    encoded = str(result)
    assert "/Users/example/private" not in encoded
    assert "cmdline" not in encoded
    assert "environ" not in encoded


@pytest.mark.asyncio
async def test_mac_processes_skips_inaccessible_or_racing_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mac_processes.psutil,
        "process_iter",
        lambda _attrs: iter(
            [
                FakeProcess(error=psutil.AccessDenied(pid=7)),
                FakeProcess(
                    {
                        "pid": 9,
                        "name": "safe",
                        "status": "running",
                        "memory_info": SimpleNamespace(rss=1),
                        "create_time": None,
                    }
                ),
            ]
        ),
    )

    result = await list_mac_processes(MacProcessesListInput(max_entries=10))

    assert result["processCount"] == 2
    assert result["skippedCount"] == 1
    assert result["entries"] == [
        {
            "pid": 9,
            "name": "safe",
            "status": "running",
            "rssBytes": 1,
            "createTimeEpochSeconds": None,
        }
    ]


@pytest.mark.asyncio
async def test_mac_processes_truncates_to_request_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mac_processes.psutil,
        "process_iter",
        lambda _attrs: iter(
            FakeProcess(
                {
                    "pid": index,
                    "name": f"process-{index}",
                    "status": "running",
                    "memory_info": SimpleNamespace(rss=index),
                    "create_time": 1,
                }
            )
            for index in range(MAX_PROCESS_ENTRIES + 5)
        ),
    )

    result = await list_mac_processes(MacProcessesListInput(max_entries=MAX_PROCESS_ENTRIES))

    assert result["processCount"] == MAX_PROCESS_ENTRIES + 5
    assert result["truncated"] is True
    assert len(result["entries"]) == MAX_PROCESS_ENTRIES
    assert [entry["rssBytes"] for entry in result["entries"]] == sorted(
        [entry["rssBytes"] for entry in result["entries"]],
        reverse=True,
    )


@pytest.mark.asyncio
async def test_mac_processes_tool_registers_with_safe_mcp_metadata() -> None:
    registry = ToolRegistry()
    registry.register(build_mac_processes_list_tool(timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    capability = registry.describe()[0]

    assert capability.name == "mac.processes.list"
    assert capability.meta.permission.value == "SAFE"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False
    assert capability.annotations.idempotent_hint is True
    assert capability.annotations.open_world_hint is False


@pytest.mark.asyncio
async def test_mac_processes_health_uses_provider_availability_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def boot_time() -> float:
        calls.append("boot")
        return 1.0

    def process_iter(_attrs: object) -> object:
        calls.append("processes")
        raise AssertionError("health must not enumerate process metadata")

    monkeypatch.setattr(mac_processes.psutil, "boot_time", boot_time)
    monkeypatch.setattr(mac_processes.psutil, "process_iter", process_iter)

    tool = build_mac_processes_list_tool(timeout_seconds=1)

    assert await tool.health_probe() is True
    assert calls == ["boot"]


@pytest.mark.asyncio
async def test_mac_processes_fails_closed_off_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_processes, "is_mac_processes_supported", lambda: False)
    tool = build_mac_processes_list_tool(timeout_seconds=1)

    assert await tool.health_probe() is False
    with pytest.raises(ValueError, match="requires macOS"):
        await list_mac_processes(MacProcessesListInput(max_entries=1))
