from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from stat import S_ISDIR, S_ISLNK, S_ISREG
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from goffy_hub.registry import ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations

MAX_APPROVED_ROOTS = 8
MAX_LIST_ENTRIES = 32
MAX_RELATIVE_PATH_CHARS = 512
MAX_ENTRY_NAME_CHARS = 96
MAX_ROOT_NAME_CHARS = 64


@dataclass(frozen=True, slots=True)
class ApprovedMacFilesRoot:
    index: int
    name: str
    path: Path


class MacFilesListInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    root_index: int = Field(default=0, ge=0, lt=MAX_APPROVED_ROOTS)
    relative_path: str = Field(default="", max_length=MAX_RELATIVE_PATH_CHARS)
    max_entries: int = Field(default=25, ge=1, le=MAX_LIST_ENTRIES)
    include_hidden: bool = False

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if "\x00" in value or any(character.isspace() and character != " " for character in value):
            raise ValueError("relative_path contains unsupported control characters")
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("relative_path must stay inside an approved root")
        return "" if value in {"", "."} else value.strip("/")


class MacFilesApprovedRootOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    root_index: int
    name: str


class MacFilesListEntryOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    name: str
    name_truncated: bool
    kind: Literal["file", "directory", "symlink", "other"]
    size_bytes: int | None
    modified_epoch_seconds: int | None


class MacFilesListOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    status: str
    root_index: int
    root_name: str
    relative_path: str
    truncated: bool
    approved_roots: list[MacFilesApprovedRootOutput] = Field(max_length=MAX_APPROVED_ROOTS)
    entries: list[MacFilesListEntryOutput] = Field(max_length=MAX_LIST_ENTRIES)


async def list_mac_files(
    request: BaseModel,
    approved_roots: tuple[ApprovedMacFilesRoot, ...],
) -> dict[str, Any]:
    parsed = cast(MacFilesListInput, request)
    root = _root_for_index(parsed.root_index, approved_roots)
    target = _safe_target(root.path, parsed.relative_path)
    if not target.is_dir():
        raise ValueError("relative_path must point to a directory")

    entries = _directory_entries(
        target,
        max_entries=parsed.max_entries,
        include_hidden=parsed.include_hidden,
    )
    return MacFilesListOutput(
        status="available",
        root_index=root.index,
        root_name=root.name,
        relative_path=parsed.relative_path,
        truncated=entries.truncated,
        approved_roots=[
            MacFilesApprovedRootOutput(root_index=item.index, name=item.name)
            for item in approved_roots
        ],
        entries=entries.entries,
    ).model_dump(mode="json", by_alias=True)


async def check_mac_files_health(approved_roots: tuple[ApprovedMacFilesRoot, ...]) -> bool:
    return bool(approved_roots) and all(root.path.is_dir() for root in approved_roots)


def build_mac_files_list_tool(
    approved_root_paths: tuple[Path, ...],
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    approved_roots = _approved_roots(approved_root_paths)

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await list_mac_files(request, approved_roots)

    async def health_probe() -> bool:
        return await check_mac_files_health(approved_roots)

    return ToolDefinition(
        name="mac.files.list",
        title="Mac approved-root file listing",
        description=(
            "List entries inside explicitly approved Mac directories without following symlink "
            "targets or exposing absolute root paths."
        ),
        tool_version="1.0.0",
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=MacFilesListInput,
        output_model=MacFilesListOutput,
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


@dataclass(frozen=True, slots=True)
class _EntryCollection:
    entries: list[MacFilesListEntryOutput]
    truncated: bool


def _approved_roots(paths: tuple[Path, ...]) -> tuple[ApprovedMacFilesRoot, ...]:
    if not paths or len(paths) > MAX_APPROVED_ROOTS:
        raise ValueError(f"mac.files.list requires 1..{MAX_APPROVED_ROOTS} approved roots")
    roots: list[ApprovedMacFilesRoot] = []
    for index, root in enumerate(paths):
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("approved roots must be existing absolute directories")
        roots.append(
            ApprovedMacFilesRoot(
                index=index,
                name=_bounded_text(root.name or "root", MAX_ROOT_NAME_CHARS),
                path=root.resolve(strict=True),
            )
        )
    if len({root.path for root in roots}) != len(roots):
        raise ValueError("approved roots must be unique")
    return tuple(roots)


def _root_for_index(
    root_index: int,
    approved_roots: tuple[ApprovedMacFilesRoot, ...],
) -> ApprovedMacFilesRoot:
    for root in approved_roots:
        if root.index == root_index:
            return root
    raise ValueError("root_index is not configured")


def _safe_target(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve(strict=True)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("relative_path escapes the approved root") from exc
    return target


def _directory_entries(
    target: Path,
    *,
    max_entries: int,
    include_hidden: bool,
) -> _EntryCollection:
    visible_entries = [
        item
        for item in sorted(target.iterdir(), key=lambda entry: entry.name.casefold())
        if include_hidden or not item.name.startswith(".")
    ]
    selected_entries = visible_entries[:max_entries]
    return _EntryCollection(
        entries=[_entry_output(item) for item in selected_entries],
        truncated=len(visible_entries) > len(selected_entries),
    )


def _entry_output(path: Path) -> MacFilesListEntryOutput:
    stat_result = path.stat(follow_symlinks=False)
    name = _bounded_text(path.name, MAX_ENTRY_NAME_CHARS)
    kind = _entry_kind(stat_result.st_mode)
    return MacFilesListEntryOutput(
        name=name,
        name_truncated=name != path.name,
        kind=kind,
        size_bytes=stat_result.st_size if kind == "file" else None,
        modified_epoch_seconds=int(stat_result.st_mtime),
    )


def _entry_kind(mode: int) -> Literal["file", "directory", "symlink", "other"]:
    if S_ISLNK(mode):
        return "symlink"
    if S_ISDIR(mode):
        return "directory"
    if S_ISREG(mode):
        return "file"
    return "other"


def _bounded_text(value: str, limit: int) -> str:
    sanitized = "".join(" " if ord(character) < 0x20 else character for character in value).strip()
    return sanitized[:limit] or "unnamed"
