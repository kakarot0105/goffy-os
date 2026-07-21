from __future__ import annotations

import os
import shutil

import pytest

from goffy_hub.registry import ToolRegistry
from goffy_hub.tools.mac_files import (
    MacFilesLargestInput,
    MacFilesListInput,
    build_mac_files_largest_tool,
    build_mac_files_list_tool,
    find_largest_mac_files,
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


@pytest.mark.asyncio
async def test_mac_files_largest_returns_bounded_relative_metadata(tmp_path) -> None:
    (tmp_path / "small.txt").write_text("1", encoding="utf-8")
    (tmp_path / ".hidden-big.bin").write_bytes(b"x" * 100)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "large.bin").write_bytes(b"x" * 20)

    tool = build_mac_files_largest_tool((tmp_path,), timeout_seconds=1)
    result = await tool.handler(
        MacFilesLargestInput(max_entries=10, max_depth=4, include_hidden=False),
    )

    assert result["status"] == "available"
    assert result["rootIndex"] == 0
    assert result["rootName"] == tmp_path.name
    assert result["approvedRoots"] == [{"rootIndex": 0, "name": tmp_path.name}]
    assert [entry["relativePath"] for entry in result["entries"]] == [
        "nested/large.bin",
        "small.txt",
    ]
    assert [entry["sizeBytes"] for entry in result["entries"]] == [20, 1]
    assert result["scannedEntries"] == 3
    assert result["truncated"] is False
    assert ".hidden-big" not in str(result)
    assert str(tmp_path) not in str(result)
    assert "x" * 20 not in str(result)


@pytest.mark.asyncio
async def test_mac_files_largest_never_follows_symlinks(tmp_path) -> None:
    outside = tmp_path / "outside"
    approved = tmp_path / "approved"
    outside.mkdir()
    approved.mkdir()
    (outside / "private.bin").write_bytes(b"x" * 100)
    (approved / "link").symlink_to(outside / "private.bin")

    tool = build_mac_files_largest_tool((approved,), timeout_seconds=1)
    result = await tool.handler(MacFilesLargestInput(max_entries=10, include_hidden=True))

    assert result["entries"] == []
    assert result["skippedEntries"] == 1
    assert "private.bin" not in str(result)
    assert str(outside) not in str(result)


@pytest.mark.asyncio
async def test_mac_files_largest_refuses_directory_replaced_by_symlink_during_scan(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import goffy_hub.tools.mac_files as mac_files

    outside = tmp_path / "outside"
    approved = tmp_path / "approved"
    outside.mkdir()
    approved.mkdir()
    (outside / "secret.bin").write_bytes(b"x" * 100)
    queued = approved / "a"
    queued.mkdir()
    (queued / "safe.bin").write_bytes(b"x")

    real_stat = mac_files.os.stat
    swapped = False

    def racing_stat(path, *args, **kwargs):
        nonlocal swapped
        result = real_stat(path, *args, **kwargs)
        if path == "a" and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            shutil.rmtree(queued)
            queued.symlink_to(outside)
        return result

    monkeypatch.setattr(mac_files.os, "stat", racing_stat)
    tool = build_mac_files_largest_tool((approved,), timeout_seconds=1)
    result = await tool.handler(MacFilesLargestInput(max_entries=10, include_hidden=True))

    assert swapped is True
    assert result["entries"] == []
    assert result["skippedEntries"] >= 1
    assert "secret.bin" not in str(result)
    assert str(outside) not in str(result)


@pytest.mark.asyncio
async def test_mac_files_largest_rejects_traversal_root_index_and_symlink_path(tmp_path) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    (outside / "other").mkdir()
    (approved / "escape").symlink_to(outside / "other")

    tool = build_mac_files_largest_tool((approved,), timeout_seconds=1)

    with pytest.raises(ValueError, match="inside an approved root"):
        MacFilesLargestInput(relative_path="../outside")
    with pytest.raises(ValueError, match="root_index"):
        await tool.handler(MacFilesLargestInput(root_index=1))
    with pytest.raises(ValueError, match="symlinks"):
        await tool.handler(MacFilesLargestInput(relative_path="escape"))


@pytest.mark.asyncio
async def test_mac_files_largest_truncates_to_scan_and_result_bounds(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import goffy_hub.tools.mac_files as mac_files

    monkeypatch.setattr(mac_files, "MAX_LARGEST_SCAN_ENTRIES", 3)
    for index in range(6):
        (tmp_path / f"file-{index}.bin").write_bytes(b"x" * (index + 1))

    tool = build_mac_files_largest_tool((tmp_path,), timeout_seconds=1)
    result = await tool.handler(MacFilesLargestInput(max_entries=2, include_hidden=True))

    assert result["scannedEntries"] == 3
    assert result["truncated"] is True
    assert len(result["entries"]) == 2
    assert [entry["sizeBytes"] for entry in result["entries"]] == sorted(
        [entry["sizeBytes"] for entry in result["entries"]],
        reverse=True,
    )


@pytest.mark.asyncio
async def test_mac_files_largest_truncated_paths_remain_relative_and_display_safe(tmp_path) -> None:
    long_dir = tmp_path / ("d" * 191)
    long_dir.mkdir()
    long_file = long_dir / "file.bin"
    long_file.write_bytes(b"x" * 20)

    tool = build_mac_files_largest_tool((tmp_path,), timeout_seconds=1)
    result = await tool.handler(MacFilesLargestInput(max_entries=1, include_hidden=True))
    entry = result["entries"][0]

    assert entry["pathTruncated"] is True
    assert entry["relativePath"].startswith("truncated/")
    assert not entry["relativePath"].startswith("/")
    assert "" not in entry["relativePath"].split("/")
    assert ".." not in entry["relativePath"].split("/")


@pytest.mark.asyncio
async def test_mac_files_largest_preserves_post_2038_modified_time(tmp_path) -> None:
    target = tmp_path / "future.bin"
    target.write_bytes(b"x" * 20)
    future_epoch_seconds = 4_102_444_800
    os.utime(target, (future_epoch_seconds, future_epoch_seconds))

    tool = build_mac_files_largest_tool((tmp_path,), timeout_seconds=1)
    result = await tool.handler(MacFilesLargestInput(max_entries=1, include_hidden=True))

    assert result["entries"][0]["modifiedEpochSeconds"] == future_epoch_seconds


@pytest.mark.asyncio
async def test_mac_files_largest_tool_registers_with_safe_mcp_metadata(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(build_mac_files_largest_tool((tmp_path,), timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    capability = registry.describe()[0]

    assert capability.name == "mac.files.largest"
    assert capability.meta.permission.value == "SAFE"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False


@pytest.mark.asyncio
async def test_mac_files_largest_direct_helper_requires_configured_root(tmp_path) -> None:
    with pytest.raises(ValueError, match="root_index"):
        await find_largest_mac_files(MacFilesLargestInput(), ())
