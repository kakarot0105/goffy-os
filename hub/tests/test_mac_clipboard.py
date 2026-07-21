from __future__ import annotations

import sys

import pytest

from goffy_hub.registry import ToolRegistry
from goffy_hub.tools import mac_clipboard
from goffy_hub.tools.mac_clipboard import (
    ClipboardProviderUnavailableError,
    MacClipboardReadInput,
    build_mac_clipboard_read_tool,
    check_mac_clipboard_health,
    read_mac_clipboard,
)


class FakeClipboardReader:
    def __init__(self, text: str | None, *, available: bool = True) -> None:
        self.text = text
        self.available = available
        self.read_count = 0
        self.health_count = 0

    def read_text(self) -> str | None:
        self.read_count += 1
        return self.text

    def is_available(self) -> bool:
        self.health_count += 1
        return self.available


@pytest.mark.asyncio
async def test_mac_clipboard_read_returns_bounded_plaintext() -> None:
    reader = FakeClipboardReader("hello\x00\nworld")

    result = await read_mac_clipboard(MacClipboardReadInput(max_chars=20), reader)

    assert result == {
        "status": "available",
        "contentType": "text",
        "text": "hello \nworld",
        "textTruncated": False,
        "characterCount": 12,
        "characterCountTruncated": False,
    }
    assert reader.read_count == 1


@pytest.mark.asyncio
async def test_mac_clipboard_read_truncates_text_to_request_limit() -> None:
    reader = FakeClipboardReader("abcdef")

    result = await read_mac_clipboard(MacClipboardReadInput(max_chars=3), reader)

    assert result["text"] == "abc"
    assert result["textTruncated"] is True
    assert result["characterCount"] == 6
    assert result["characterCountTruncated"] is False


@pytest.mark.asyncio
async def test_mac_clipboard_read_caps_observed_character_count() -> None:
    reader = FakeClipboardReader("a" * (mac_clipboard.MAX_CLIPBOARD_OBSERVED_CHARS + 10))

    result = await read_mac_clipboard(MacClipboardReadInput(max_chars=5), reader)

    assert result["text"] == "aaaaa"
    assert result["textTruncated"] is True
    assert result["characterCount"] == mac_clipboard.MAX_CLIPBOARD_OBSERVED_CHARS
    assert result["characterCountTruncated"] is True


@pytest.mark.asyncio
async def test_mac_clipboard_read_reports_empty_without_content() -> None:
    reader = FakeClipboardReader(None)

    result = await read_mac_clipboard(MacClipboardReadInput(), reader)

    assert result == {
        "status": "empty",
        "contentType": "text",
        "text": None,
        "textTruncated": False,
        "characterCount": 0,
        "characterCountTruncated": False,
    }


@pytest.mark.asyncio
async def test_mac_clipboard_read_rejects_file_url_text_without_leaking_path() -> None:
    reader = FakeClipboardReader("file:///Users/example/private.txt")

    result = await read_mac_clipboard(MacClipboardReadInput(), reader)

    assert result == {
        "status": "unsupported",
        "contentType": "text",
        "text": None,
        "textTruncated": False,
        "characterCount": 0,
        "characterCountTruncated": False,
    }
    assert "private.txt" not in str(result)


@pytest.mark.asyncio
async def test_mac_clipboard_health_does_not_read_clipboard_content() -> None:
    reader = FakeClipboardReader("private")

    assert await check_mac_clipboard_health(reader) is True
    assert reader.health_count == 1
    assert reader.read_count == 0


@pytest.mark.asyncio
async def test_mac_clipboard_tool_registers_with_safe_mcp_metadata() -> None:
    registry = ToolRegistry()
    registry.register(
        build_mac_clipboard_read_tool(
            timeout_seconds=1,
            reader=FakeClipboardReader("copy"),
        )
    )
    registry.seal()
    await registry.refresh_health()

    capability = registry.describe()[0]

    assert capability.name == "mac.clipboard.read"
    assert capability.meta.permission.value == "SAFE"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False
    assert capability.input_schema["properties"]["maxChars"]["maximum"] == 2000
    assert capability.output_schema["properties"]["text"]["anyOf"][0]["maxLength"] == 2000


@pytest.mark.asyncio
async def test_mac_clipboard_tool_without_provider_fails_closed_on_non_macos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    tool = build_mac_clipboard_read_tool(timeout_seconds=1)

    assert await tool.health_probe() is False
    with pytest.raises(ClipboardProviderUnavailableError, match="mac.clipboard.read"):
        await tool.handler(MacClipboardReadInput())
