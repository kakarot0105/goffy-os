from __future__ import annotations

import asyncio
import importlib
import sys
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from goffy_hub.registry import ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations

MAX_CLIPBOARD_TEXT_CHARS = 2_000
MAX_CLIPBOARD_OBSERVED_CHARS = 100_000


class ClipboardProviderUnavailableError(RuntimeError):
    pass


class ClipboardTextReader(Protocol):
    def read_text(self) -> str | None:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class PasteboardClipboardTextReader:
    def __init__(self) -> None:
        self._pasteboard: Any | None = None
        self._string_type: Any | None = None

    def read_text(self) -> str | None:
        self._load_provider()
        if self._pasteboard is None:
            raise ClipboardProviderUnavailableError(
                "mac.clipboard.read could not initialize the pasteboard provider"
            )
        value = self._pasteboard.get_contents(type=self._string_type)
        return value if isinstance(value, str) else None

    def is_available(self) -> bool:
        try:
            self._load_provider()
        except ClipboardProviderUnavailableError:
            return False
        return True

    def _load_provider(self) -> None:
        if self._pasteboard is not None:
            return
        if sys.platform != "darwin":
            raise ClipboardProviderUnavailableError("mac.clipboard.read only supports macOS")
        try:
            module = importlib.import_module("pasteboard")
        except ImportError as exc:
            raise ClipboardProviderUnavailableError(
                "mac.clipboard.read requires the optional pasteboard dependency"
            ) from exc

        pasteboard_class: Any = getattr(module, "Pasteboard", None)
        string_type: Any = getattr(module, "String", None)
        if pasteboard_class is None or string_type is None:
            raise ClipboardProviderUnavailableError(
                "mac.clipboard.read could not initialize the pasteboard provider"
            )
        self._pasteboard = pasteboard_class()
        self._string_type = string_type


class MacClipboardReadInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    max_chars: int = Field(default=1_000, ge=1, le=MAX_CLIPBOARD_TEXT_CHARS)


class MacClipboardReadOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    status: Literal["available", "empty", "unsupported"]
    content_type: Literal["text"] = "text"
    text: str | None = Field(default=None, max_length=MAX_CLIPBOARD_TEXT_CHARS)
    text_truncated: bool
    character_count: int = Field(ge=0, le=MAX_CLIPBOARD_OBSERVED_CHARS)
    character_count_truncated: bool


async def read_mac_clipboard(
    request: BaseModel,
    reader: ClipboardTextReader,
) -> dict[str, Any]:
    parsed = cast(MacClipboardReadInput, request)
    raw_text = await asyncio.to_thread(reader.read_text)
    if raw_text is None:
        return _empty_output()

    observed_sample = raw_text[: MAX_CLIPBOARD_OBSERVED_CHARS + 1]
    if _contains_file_url(observed_sample):
        return _unsupported_output()

    character_count_truncated = len(observed_sample) > MAX_CLIPBOARD_OBSERVED_CHARS
    sanitized_text = _sanitize_clipboard_text(observed_sample[:MAX_CLIPBOARD_OBSERVED_CHARS])
    if not sanitized_text:
        return _empty_output()

    bounded_text = sanitized_text[: parsed.max_chars]
    return MacClipboardReadOutput(
        status="available",
        text=bounded_text,
        text_truncated=character_count_truncated or len(sanitized_text) > len(bounded_text),
        character_count=len(sanitized_text),
        character_count_truncated=character_count_truncated,
    ).model_dump(mode="json", by_alias=True)


async def check_mac_clipboard_health(reader: ClipboardTextReader) -> bool:
    return await asyncio.to_thread(reader.is_available)


def build_mac_clipboard_read_tool(
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
    *,
    reader: ClipboardTextReader | None = None,
) -> ToolDefinition:
    clipboard_reader = reader if reader is not None else PasteboardClipboardTextReader()

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await read_mac_clipboard(request, clipboard_reader)

    async def health_probe() -> bool:
        return await check_mac_clipboard_health(clipboard_reader)

    return ToolDefinition(
        name="mac.clipboard.read",
        title="Mac clipboard text read",
        description=(
            "Read bounded plaintext from the active Mac clipboard when this opt-in tool is enabled."
        ),
        tool_version="1.0.0",
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=MacClipboardReadInput,
        output_model=MacClipboardReadOutput,
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


def _empty_output() -> dict[str, Any]:
    return MacClipboardReadOutput(
        status="empty",
        text=None,
        text_truncated=False,
        character_count=0,
        character_count_truncated=False,
    ).model_dump(mode="json", by_alias=True)


def _unsupported_output() -> dict[str, Any]:
    return MacClipboardReadOutput(
        status="unsupported",
        text=None,
        text_truncated=False,
        character_count=0,
        character_count_truncated=False,
    ).model_dump(mode="json", by_alias=True)


def _contains_file_url(value: str) -> bool:
    return "file://" in value.casefold()


def _sanitize_clipboard_text(value: str) -> str:
    allowed_controls = {"\n", "\r", "\t"}
    return "".join(
        character
        if character in allowed_controls or (ord(character) >= 0x20 and ord(character) != 0x7F)
        else " "
        for character in value
    )
