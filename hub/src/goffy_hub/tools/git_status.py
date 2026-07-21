from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from goffy_hub.registry import MAX_TOOL_OUTPUT_BYTES, ToolDefinition
from goffy_protocol import ExecutionTarget, PermissionLevel, ToolAnnotations

MAX_APPROVED_REPOS = 8
MAX_STATUS_CHANGES = 32
MAX_REPO_NAME_CHARS = 64
MAX_GIT_PATH_CHARS = 160
MAX_BRANCH_NAME_CHARS = 96
MAX_UPSTREAM_NAME_CHARS = 128
MAX_GIT_OID_SHORT_CHARS = 16
GIT_STATUS_TIMEOUT_SECONDS = 2.5
GIT_STATUS_KIND = Literal["tracked", "untracked", "conflict"]


@dataclass(frozen=True, slots=True)
class ApprovedGitRepo:
    index: int
    name: str
    path: Path


@dataclass(frozen=True, slots=True)
class _GitChange:
    path: str
    index_status: str
    working_tree_status: str
    kind: GIT_STATUS_KIND


@dataclass(frozen=True, slots=True)
class _GitStatus:
    branch: str | None
    head_oid_short: str | None
    upstream: str | None
    ahead: int | None
    behind: int | None
    changes: list[_GitChange]


class GitStatusInput(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    repo_index: int = Field(default=0, ge=0, lt=MAX_APPROVED_REPOS)
    max_changes: int = Field(default=25, ge=1, le=MAX_STATUS_CHANGES)
    include_untracked: bool = True


class GitStatusApprovedRepoOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    repo_index: int = Field(ge=0, lt=MAX_APPROVED_REPOS)
    name: str = Field(min_length=1, max_length=MAX_REPO_NAME_CHARS)


class GitStatusChangeOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    path: str = Field(min_length=1, max_length=MAX_GIT_PATH_CHARS)
    path_truncated: bool
    index_status: str = Field(min_length=1, max_length=1)
    working_tree_status: str = Field(min_length=1, max_length=1)
    kind: GIT_STATUS_KIND


class GitStatusOutput(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    status: str = Field(min_length=1, max_length=64)
    repo_index: int = Field(ge=0, lt=MAX_APPROVED_REPOS)
    repo_name: str = Field(min_length=1, max_length=MAX_REPO_NAME_CHARS)
    branch: str | None = Field(default=None, max_length=MAX_BRANCH_NAME_CHARS)
    head_oid_short: str | None = Field(default=None, max_length=MAX_GIT_OID_SHORT_CHARS)
    upstream: str | None = Field(default=None, max_length=MAX_UPSTREAM_NAME_CHARS)
    ahead: int | None = Field(default=None, ge=0)
    behind: int | None = Field(default=None, ge=0)
    clean: bool
    staged_count: int = Field(ge=0)
    unstaged_count: int = Field(ge=0)
    untracked_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    truncated: bool
    approved_repos: list[GitStatusApprovedRepoOutput] = Field(max_length=MAX_APPROVED_REPOS)
    changes: list[GitStatusChangeOutput] = Field(max_length=MAX_STATUS_CHANGES)

    @field_validator("repo_name")
    @classmethod
    def bound_repo_name(cls, value: str) -> str:
        return _bounded_required_text(value, MAX_REPO_NAME_CHARS)

    @field_validator("branch")
    @classmethod
    def bound_branch(cls, value: str | None) -> str | None:
        return None if value is None else _bounded_required_text(value, MAX_BRANCH_NAME_CHARS)

    @field_validator("head_oid_short")
    @classmethod
    def bound_oid(cls, value: str | None) -> str | None:
        return None if value is None else _bounded_required_text(value, MAX_GIT_OID_SHORT_CHARS)

    @field_validator("upstream")
    @classmethod
    def bound_upstream(cls, value: str | None) -> str | None:
        return None if value is None else _bounded_required_text(value, MAX_UPSTREAM_NAME_CHARS)


async def read_git_status(
    request: BaseModel,
    approved_repos: tuple[ApprovedGitRepo, ...],
    git_executable: Path,
    timeout_seconds: float = GIT_STATUS_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    parsed = cast(GitStatusInput, request)
    repo = _repo_for_index(parsed.repo_index, approved_repos)
    raw_status = await asyncio.to_thread(
        _run_git_status,
        git_executable,
        repo.path,
        parsed.include_untracked,
        timeout_seconds,
    )
    status = _parse_porcelain_v2(raw_status)
    changes = [_change_output(change) for change in status.changes[: parsed.max_changes]]
    staged_count = sum(
        1 for change in status.changes if change.kind != "untracked" and change.index_status != "."
    )
    unstaged_count = sum(
        1
        for change in status.changes
        if change.kind != "untracked" and change.working_tree_status != "."
    )
    untracked_count = sum(1 for change in status.changes if change.kind == "untracked")
    conflict_count = sum(1 for change in status.changes if change.kind == "conflict")

    output = GitStatusOutput(
        status="available",
        repo_index=repo.index,
        repo_name=repo.name,
        branch=status.branch,
        head_oid_short=status.head_oid_short,
        upstream=status.upstream,
        ahead=status.ahead,
        behind=status.behind,
        clean=not status.changes,
        staged_count=staged_count,
        unstaged_count=unstaged_count,
        untracked_count=untracked_count,
        conflict_count=conflict_count,
        truncated=len(status.changes) > len(changes),
        approved_repos=[
            GitStatusApprovedRepoOutput(repo_index=item.index, name=item.name)
            for item in approved_repos
        ],
        changes=changes,
    )
    while _output_bytes(output) > MAX_TOOL_OUTPUT_BYTES and output.changes:
        output = output.model_copy(update={"changes": output.changes[:-1], "truncated": True})
    if _output_bytes(output) > MAX_TOOL_OUTPUT_BYTES:
        raise ValueError("git.status output exceeds the supported size")
    return output.model_dump(mode="json", by_alias=True)


async def check_git_status_health(
    approved_repos: tuple[ApprovedGitRepo, ...],
    git_executable: Path,
) -> bool:
    return await asyncio.to_thread(_check_git_status_health, approved_repos, git_executable)


def _check_git_status_health(
    approved_repos: tuple[ApprovedGitRepo, ...],
    git_executable: Path,
) -> bool:
    return (
        bool(approved_repos)
        and git_executable.is_file()
        and all(repo.path.is_dir() and _git_marker(repo.path).exists() for repo in approved_repos)
    )


def build_git_status_tool(
    approved_repo_paths: tuple[Path, ...],
    timeout_seconds: float,
    health_timeout_seconds: float = 1.0,
) -> ToolDefinition:
    approved_repos = _approved_repos(approved_repo_paths)
    git_executable = _resolve_git_executable()
    command_timeout_seconds = min(timeout_seconds, GIT_STATUS_TIMEOUT_SECONDS)

    async def handler(request: BaseModel) -> dict[str, Any]:
        return await read_git_status(
            request,
            approved_repos,
            git_executable,
            command_timeout_seconds,
        )

    async def health_probe() -> bool:
        return await check_git_status_health(approved_repos, git_executable)

    return ToolDefinition(
        name="git.status",
        title="Approved Git repository status",
        description=(
            "Read bounded status metadata for explicitly approved local Git repositories without "
            "running arbitrary commands or exposing repository root paths."
        ),
        tool_version="1.0.0",
        permission=PermissionLevel.SAFE,
        execution_target=ExecutionTarget.MAC,
        timeout_seconds=timeout_seconds,
        input_model=GitStatusInput,
        output_model=GitStatusOutput,
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


def _approved_repos(paths: tuple[Path, ...]) -> tuple[ApprovedGitRepo, ...]:
    if not paths or len(paths) > MAX_APPROVED_REPOS:
        raise ValueError(f"git.status requires 1..{MAX_APPROVED_REPOS} approved repos")
    repos: list[ApprovedGitRepo] = []
    for index, root in enumerate(paths):
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("approved Git repos must be existing absolute directories")
        resolved = root.resolve(strict=True)
        if not _git_marker(resolved).exists():
            raise ValueError("approved Git repos must be Git worktree roots")
        repos.append(
            ApprovedGitRepo(
                index=index,
                name=_bounded_required_text(resolved.name or "repo", MAX_REPO_NAME_CHARS),
                path=resolved,
            )
        )
    if len({repo.path for repo in repos}) != len(repos):
        raise ValueError("approved Git repos must be unique")
    return tuple(repos)


def _repo_for_index(
    repo_index: int,
    approved_repos: tuple[ApprovedGitRepo, ...],
) -> ApprovedGitRepo:
    for repo in approved_repos:
        if repo.index == repo_index:
            return repo
    raise ValueError("repo_index is not configured")


def _resolve_git_executable() -> Path:
    resolved = shutil.which("git")
    if resolved is None:
        raise ValueError("git.status requires a git executable")
    return Path(resolved).resolve(strict=True)


def _run_git_status(
    git_executable: Path,
    repo_path: Path,
    include_untracked: bool,
    timeout_seconds: float,
) -> str:
    untracked_mode = "--untracked-files=all" if include_untracked else "--untracked-files=no"
    completed = subprocess.run(  # noqa: S603 - fixed executable and arguments; no shell.
        [
            str(git_executable),
            "status",
            "--porcelain=v2",
            "--branch",
            "--no-renames",
            untracked_mode,
        ],
        cwd=repo_path,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        },
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise ValueError("git.status command failed")
    if len(completed.stdout.encode("utf-8")) > 16_384:
        raise ValueError("git.status output exceeds the supported size")
    return completed.stdout


def _parse_porcelain_v2(raw_status: str) -> _GitStatus:
    branch: str | None = None
    head_oid_short: str | None = None
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    changes: list[_GitChange] = []

    for line in raw_status.splitlines():
        if line.startswith("# branch.oid "):
            oid = line.removeprefix("# branch.oid ").strip()
            head_oid_short = None if oid == "(initial)" else oid[:MAX_GIT_OID_SHORT_CHARS]
            continue
        if line.startswith("# branch.head "):
            value = line.removeprefix("# branch.head ").strip()
            branch = (
                None
                if value == "(detached)"
                else _bounded_required_text(
                    value,
                    MAX_BRANCH_NAME_CHARS,
                )
            )
            continue
        if line.startswith("# branch.upstream "):
            upstream = _bounded_required_text(
                line.removeprefix("# branch.upstream ").strip(),
                MAX_UPSTREAM_NAME_CHARS,
            )
            continue
        if line.startswith("# branch.ab "):
            ahead, behind = _parse_ahead_behind(line)
            continue
        if not line or line.startswith("#"):
            continue
        parsed_change = _parse_change_line(line)
        if parsed_change is not None:
            changes.append(parsed_change)

    return _GitStatus(
        branch=branch,
        head_oid_short=head_oid_short,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        changes=changes,
    )


def _parse_ahead_behind(line: str) -> tuple[int | None, int | None]:
    parts = line.split()
    if len(parts) != 4:
        return None, None
    try:
        ahead = int(parts[2].removeprefix("+"))
        behind = int(parts[3].removeprefix("-"))
    except ValueError:
        return None, None
    return max(ahead, 0), max(behind, 0)


def _parse_change_line(line: str) -> _GitChange | None:
    if line.startswith("? "):
        return _GitChange(
            path=line[2:],
            index_status="?",
            working_tree_status="?",
            kind="untracked",
        )
    if line.startswith("1 "):
        parts = line.split(maxsplit=8)
        if len(parts) != 9 or len(parts[1]) != 2:
            return None
        return _GitChange(
            path=parts[8],
            index_status=parts[1][0],
            working_tree_status=parts[1][1],
            kind="tracked",
        )
    if line.startswith("u "):
        parts = line.split(maxsplit=10)
        if len(parts) != 11 or len(parts[1]) != 2:
            return None
        return _GitChange(
            path=parts[10],
            index_status=parts[1][0],
            working_tree_status=parts[1][1],
            kind="conflict",
        )
    return None


def _change_output(change: _GitChange) -> GitStatusChangeOutput:
    path = _bounded_required_text(change.path, MAX_GIT_PATH_CHARS)
    return GitStatusChangeOutput(
        path=path,
        path_truncated=path != change.path,
        index_status=change.index_status,
        working_tree_status=change.working_tree_status,
        kind=change.kind,
    )


def _output_bytes(output: GitStatusOutput) -> int:
    return len(
        json.dumps(
            output.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _git_marker(root: Path) -> Path:
    return root / ".git"


def _bounded_required_text(value: str, limit: int) -> str:
    sanitized = "".join(" " if ord(character) < 0x20 else character for character in value).strip()
    return sanitized[:limit] or "unnamed"
