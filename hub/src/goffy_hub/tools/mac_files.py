from __future__ import annotations

import os
from contextlib import suppress
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
DEFAULT_LARGEST_ENTRIES = 10
MAX_LARGEST_ENTRIES = 25
DEFAULT_LARGEST_DEPTH = 4
MAX_LARGEST_DEPTH = 8
MAX_LARGEST_SCAN_ENTRIES = 5_000
MAX_RELATIVE_PATH_CHARS = 512
MAX_ENTRY_NAME_CHARS = 96
MAX_LARGEST_RELATIVE_PATH_CHARS = 192
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


class MacFilesLargestInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    root_index: int = Field(default=0, ge=0, lt=MAX_APPROVED_ROOTS)
    relative_path: str = Field(default="", max_length=MAX_RELATIVE_PATH_CHARS)
    max_entries: int = Field(default=DEFAULT_LARGEST_ENTRIES, ge=1, le=MAX_LARGEST_ENTRIES)
    max_depth: int = Field(default=DEFAULT_LARGEST_DEPTH, ge=0, le=MAX_LARGEST_DEPTH)
    include_hidden: bool = False

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return MacFilesListInput.validate_relative_path(value)


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


class MacFilesLargestEntryOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    relative_path: str
    path_truncated: bool
    name: str
    name_truncated: bool
    size_bytes: int = Field(ge=0)
    modified_epoch_seconds: int | None


class MacFilesLargestOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    status: str
    root_index: int
    root_name: str
    relative_path: str
    max_depth: int
    scanned_entries: int = Field(ge=0)
    skipped_entries: int = Field(ge=0)
    truncated: bool
    approved_roots: list[MacFilesApprovedRootOutput] = Field(max_length=MAX_APPROVED_ROOTS)
    entries: list[MacFilesLargestEntryOutput] = Field(max_length=MAX_LARGEST_ENTRIES)


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


async def find_largest_mac_files(
    request: BaseModel,
    approved_roots: tuple[ApprovedMacFilesRoot, ...],
) -> dict[str, Any]:
    parsed = cast(MacFilesLargestInput, request)
    root = _root_for_index(parsed.root_index, approved_roots)
    _reject_symlink_components(root.path, parsed.relative_path)
    target = _safe_target(root.path, parsed.relative_path)
    if not target.is_dir():
        raise ValueError("relative_path must point to a directory")

    scan = _largest_file_entries(
        target=target,
        max_entries=parsed.max_entries,
        max_depth=parsed.max_depth,
        include_hidden=parsed.include_hidden,
    )
    return MacFilesLargestOutput(
        status="available",
        root_index=root.index,
        root_name=root.name,
        relative_path=parsed.relative_path,
        max_depth=parsed.max_depth,
        scanned_entries=scan.scanned_entries,
        skipped_entries=scan.skipped_entries,
        truncated=scan.truncated,
        approved_roots=[
            MacFilesApprovedRootOutput(root_index=item.index, name=item.name)
            for item in approved_roots
        ],
        entries=scan.entries,
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


def build_mac_files_largest_tool(
    approved_root_paths: tuple[Path, ...],
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    approved_roots = _approved_roots_for_tool(
        approved_root_paths,
        tool_name="mac.files.largest",
    )

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await find_largest_mac_files(request, approved_roots)

    async def health_probe() -> bool:
        return await check_mac_files_health(approved_roots)

    return ToolDefinition(
        name="mac.files.largest",
        title="Mac largest approved-root files",
        description=(
            "Find the largest regular files under an explicitly approved Mac directory with "
            "bounded traversal, no file-content reads, and no symlink following."
        ),
        tool_version="1.0.0",
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=MacFilesLargestInput,
        output_model=MacFilesLargestOutput,
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


@dataclass(frozen=True, slots=True)
class _LargestEntryCollection:
    entries: list[MacFilesLargestEntryOutput]
    scanned_entries: int
    skipped_entries: int
    truncated: bool


def _approved_roots(paths: tuple[Path, ...]) -> tuple[ApprovedMacFilesRoot, ...]:
    return _approved_roots_for_tool(paths, tool_name="mac.files.list")


def _approved_roots_for_tool(
    paths: tuple[Path, ...],
    *,
    tool_name: str,
) -> tuple[ApprovedMacFilesRoot, ...]:
    if not paths or len(paths) > MAX_APPROVED_ROOTS:
        raise ValueError(f"{tool_name} requires 1..{MAX_APPROVED_ROOTS} approved roots")
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


def _reject_symlink_components(root: Path, relative_path: str) -> None:
    if not relative_path:
        return
    current = root
    for part in Path(relative_path).parts:
        current = current / part
        try:
            if current.is_symlink():
                raise ValueError("relative_path must not traverse symlinks")
        except OSError as exc:
            raise ValueError("relative_path cannot be inspected safely") from exc


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


def _largest_file_entries(
    target: Path,
    *,
    max_entries: int,
    max_depth: int,
    include_hidden: bool,
) -> _LargestEntryCollection:
    stack: list[tuple[int, str, int]] = [(_open_directory_no_follow(target), "", 0)]
    candidates: list[MacFilesLargestEntryOutput] = []
    scanned_entries = 0
    skipped_entries = 0
    scan_truncated = False

    try:
        while stack and not scan_truncated:
            directory_fd, directory_relative_path, depth = stack.pop()
            try:
                try:
                    with os.scandir(directory_fd) as entries:
                        children = sorted(
                            (entry.name for entry in entries),
                            key=str.casefold,
                            reverse=True,
                        )
                except OSError:
                    skipped_entries += 1
                    continue

                for name in children:
                    if not include_hidden and name.startswith("."):
                        continue
                    if scanned_entries >= MAX_LARGEST_SCAN_ENTRIES:
                        scan_truncated = True
                        break
                    scanned_entries += 1
                    try:
                        stat_result = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    except OSError:
                        skipped_entries += 1
                        continue

                    mode = stat_result.st_mode
                    relative_path = _join_relative_path(directory_relative_path, name)
                    if S_ISLNK(mode):
                        skipped_entries += 1
                    elif S_ISREG(mode):
                        candidates.append(
                            _largest_entry_output(
                                relative_path,
                                name,
                                stat_result.st_size,
                                stat_result.st_mtime,
                            )
                        )
                    elif S_ISDIR(mode):
                        if depth < max_depth:
                            try:
                                child_fd = _open_directory_no_follow(name, dir_fd=directory_fd)
                            except ValueError:
                                skipped_entries += 1
                            else:
                                stack.append((child_fd, relative_path, depth + 1))
                        else:
                            skipped_entries += 1
            finally:
                os.close(directory_fd)
    finally:
        for pending_fd, _, _ in stack:
            with suppress(OSError):
                os.close(pending_fd)

    candidates.sort(key=lambda entry: (-entry.size_bytes, entry.relative_path.casefold()))
    selected = candidates[:max_entries]
    return _LargestEntryCollection(
        entries=selected,
        scanned_entries=scanned_entries,
        skipped_entries=skipped_entries,
        truncated=scan_truncated or len(candidates) > len(selected),
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


def _largest_entry_output(
    relative_path: str,
    name: str,
    size_bytes: int,
    modified_epoch_seconds: float,
) -> MacFilesLargestEntryOutput:
    bounded_relative_path, path_truncated = _bounded_relative_path(name, relative_path)
    bounded_name = _bounded_text(name, MAX_ENTRY_NAME_CHARS)
    return MacFilesLargestEntryOutput(
        relative_path=bounded_relative_path,
        path_truncated=path_truncated,
        name=bounded_name,
        name_truncated=bounded_name != name,
        size_bytes=size_bytes,
        modified_epoch_seconds=int(modified_epoch_seconds),
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


def _open_directory_no_follow(path: Path | str, dir_fd: int | None = None) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ValueError("secure directory traversal requires O_NOFOLLOW")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow | getattr(os, "O_CLOEXEC", 0)
    try:
        if dir_fd is None:
            return os.open(path, flags)
        return os.open(path, flags, dir_fd=dir_fd)
    except OSError as exc:
        raise ValueError("directory cannot be opened without following symlinks") from exc


def _join_relative_path(directory_relative_path: str, name: str) -> str:
    return name if not directory_relative_path else f"{directory_relative_path}/{name}"


def _bounded_relative_path(name: str, relative_path: str) -> tuple[str, bool]:
    candidate = _bounded_text(relative_path, MAX_LARGEST_RELATIVE_PATH_CHARS)
    if _is_safe_relative_output_path(candidate):
        return candidate, candidate != relative_path

    bounded_name = _bounded_text(name, MAX_ENTRY_NAME_CHARS)
    fallback = f"truncated/{bounded_name}"
    if _is_safe_relative_output_path(fallback):
        return fallback, True
    return "truncated/unnamed", True


def _is_safe_relative_output_path(value: str) -> bool:
    return (
        bool(value)
        and len(value) <= MAX_LARGEST_RELATIVE_PATH_CHARS
        and not value.startswith("/")
        and all(
            part not in {"", ".", ".."}
            and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in part)
            for part in value.split("/")
        )
    )
