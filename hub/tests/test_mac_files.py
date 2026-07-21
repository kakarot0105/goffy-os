from __future__ import annotations

import pytest

from goffy_hub.registry import ToolRegistry
from goffy_hub.tools.mac_files import (
    MacFilesListInput,
    build_mac_files_list_tool,
    list_mac_files,
)


@pytest.mark.asyncio
async def test_mac_files_list_returns_bounded_visible_entries(tmp_path) -> None:
    (tmp_path / "alpha.txt").write_text("hello", encoding="utf-8")
    (tmp_path / ".hidden").write_text("secret-ish", encoding="utf-8")
    (tmp_path / "folder").mkdir()

    tool = build_mac_files_list_tool((tmp_path,), timeout_seconds=1)
    result = await tool.handler(MacFilesListInput(max_entries=10, include_hidden=False))

    assert result["status"] == "available"
    assert result["rootIndex"] == 0
    assert result["rootName"] == tmp_path.name
    assert result["approvedRoots"] == [{"rootIndex": 0, "name": tmp_path.name}]
    assert [entry["name"] for entry in result["entries"]] == ["alpha.txt", "folder"]
    assert {entry["kind"] for entry in result["entries"]} == {"file", "directory"}
    assert result["truncated"] is False
    assert "secret-ish" not in str(result)
    assert str(tmp_path) not in str(result)


@pytest.mark.asyncio
async def test_mac_files_list_never_follows_symlink_targets(tmp_path) -> None:
    outside = tmp_path / "outside"
    approved = tmp_path / "approved"
    outside.mkdir()
    approved.mkdir()
    (outside / "private.txt").write_text("do-not-read", encoding="utf-8")
    (approved / "link").symlink_to(outside / "private.txt")

    tool = build_mac_files_list_tool((approved,), timeout_seconds=1)
    result = await tool.handler(MacFilesListInput(max_entries=10, include_hidden=True))

    assert result["entries"][0]["name"] == "link"
    assert result["entries"][0]["kind"] == "symlink"
    assert result["entries"][0]["sizeBytes"] is None
    assert "do-not-read" not in str(result)
    assert str(outside) not in str(result)


@pytest.mark.asyncio
async def test_mac_files_list_rejects_traversal_and_root_index_drift(tmp_path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    (outside / "other").mkdir()
    (approved / "escape").symlink_to(outside / "other")

    tool = build_mac_files_list_tool((approved,), timeout_seconds=1)

    with pytest.raises(ValueError, match="inside an approved root"):
        MacFilesListInput(relative_path="../outside")
    with pytest.raises(ValueError, match="root_index"):
        await tool.handler(MacFilesListInput(root_index=1))
    with pytest.raises(ValueError, match="escapes"):
        await tool.handler(MacFilesListInput(relative_path="escape"))


@pytest.mark.asyncio
async def test_mac_files_list_tool_registers_with_safe_mcp_metadata(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(build_mac_files_list_tool((tmp_path,), timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    capability = registry.describe()[0]

    assert capability.name == "mac.files.list"
    assert capability.meta.permission.value == "SAFE"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False


@pytest.mark.asyncio
async def test_mac_files_list_direct_helper_requires_configured_root(tmp_path) -> None:
    with pytest.raises(ValueError, match="root_index"):
        await list_mac_files(MacFilesListInput(), ())
