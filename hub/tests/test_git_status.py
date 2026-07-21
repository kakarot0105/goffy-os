from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from goffy_hub.registry import MAX_TOOL_OUTPUT_BYTES, ToolRegistry
from goffy_hub.tools import git_status
from goffy_hub.tools.git_status import (
    ApprovedGitRepo,
    GitStatusInput,
    build_git_status_tool,
    read_git_status,
)


@pytest.mark.asyncio
async def test_git_status_returns_bounded_repo_metadata(tmp_path: Path) -> None:
    repo = ApprovedGitRepo(index=0, name=tmp_path.name, path=tmp_path)
    result = await read_git_status(
        GitStatusInput(max_changes=10),
        (repo,),
        Path(sys.executable),
    )

    assert result["status"] == "available"
    assert result["repoIndex"] == 0
    assert result["repoName"] == tmp_path.name
    assert result["branch"] == "main"
    assert result["clean"] is False
    assert result["stagedCount"] == 1
    assert result["unstagedCount"] == 1
    assert result["untrackedCount"] == 1
    assert result["conflictCount"] == 0
    assert result["approvedRepos"] == [{"repoIndex": 0, "name": tmp_path.name}]
    assert {change["path"] for change in result["changes"]} == {
        "private-plan.txt",
        "staged.txt",
        "tracked.txt",
    }
    assert "do-not-read" not in str(result)
    assert str(tmp_path) not in str(result)


@pytest.mark.asyncio
async def test_git_status_can_ignore_untracked_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = ApprovedGitRepo(index=0, name=tmp_path.name, path=tmp_path)
    calls: list[bool] = []

    def fake_status(
        _git_executable: Path,
        _repo_path: Path,
        include_untracked: bool,
        _timeout_seconds: float,
    ) -> str:
        calls.append(include_untracked)
        return "# branch.oid (initial)\n# branch.head main\n"

    monkeypatch.setattr(git_status, "_run_git_status", fake_status)

    result = await read_git_status(
        GitStatusInput(include_untracked=False),
        (repo,),
        Path(sys.executable),
    )

    assert result["clean"] is True
    assert result["untrackedCount"] == 0
    assert result["changes"] == []
    assert calls == [False]


@pytest.mark.asyncio
async def test_git_status_truncates_change_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = ApprovedGitRepo(index=0, name=tmp_path.name, path=tmp_path)

    def many_untracked_files(
        _git_executable: Path,
        _repo_path: Path,
        _include_untracked: bool,
        _timeout_seconds: float,
    ) -> str:
        return "\n".join(
            [
                "# branch.oid (initial)",
                "# branch.head main",
                "? file-0.txt",
                "? file-1.txt",
                "? file-2.txt",
                "? file-3.txt",
                "? file-4.txt",
            ]
        )

    monkeypatch.setattr(git_status, "_run_git_status", many_untracked_files)

    result = await read_git_status(
        GitStatusInput(max_changes=2),
        (repo,),
        Path(sys.executable),
    )

    assert result["truncated"] is True
    assert result["untrackedCount"] == 5
    assert len(result["changes"]) == 2


@pytest.mark.asyncio
async def test_git_status_truncates_to_registry_output_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(git_status, "_resolve_git_executable", lambda: Path(sys.executable))

    def large_status(
        _git_executable: Path,
        _repo_path: Path,
        _include_untracked: bool,
        _timeout_seconds: float,
    ) -> str:
        long_path = "a" * 220
        return "\n".join(
            [
                "# branch.oid 0123456789abcdef0123456789abcdef01234567",
                "# branch.head main",
                *[f"? {index:02d}-{long_path}" for index in range(32)],
            ]
        )

    monkeypatch.setattr(git_status, "_run_git_status", large_status)
    registry = ToolRegistry()
    registry.register(build_git_status_tool((tmp_path,), timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    result = await registry.invoke("git.status", {"repoIndex": 0, "maxChanges": 32})
    output_bytes = len(
        json.dumps(
            result.structured_content,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )

    assert output_bytes <= MAX_TOOL_OUTPUT_BYTES
    assert result.structured_content["truncated"] is True
    assert len(result.structured_content["changes"]) < 32


@pytest.mark.asyncio
async def test_git_status_marks_truncated_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = ApprovedGitRepo(index=0, name=tmp_path.name, path=tmp_path)
    long_name = "a" * 220

    def long_untracked_file(
        _git_executable: Path,
        _repo_path: Path,
        _include_untracked: bool,
        _timeout_seconds: float,
    ) -> str:
        return "\n".join(["# branch.oid (initial)", "# branch.head main", f"? {long_name}"])

    monkeypatch.setattr(git_status, "_run_git_status", long_untracked_file)

    result = await read_git_status(GitStatusInput(), (repo,), Path(sys.executable))

    assert result["changes"] == [
        {
            "path": "a" * 160,
            "pathTruncated": True,
            "indexStatus": "?",
            "workingTreeStatus": "?",
            "kind": "untracked",
        }
    ]


@pytest.mark.asyncio
async def test_git_status_rejects_unconfigured_repo_index(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repo_index"):
        await read_git_status(GitStatusInput(repo_index=1), (), Path(sys.executable))


@pytest.mark.asyncio
async def test_git_status_tool_registers_with_safe_mcp_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(git_status, "_resolve_git_executable", lambda: Path(sys.executable))
    registry = ToolRegistry()
    registry.register(build_git_status_tool((tmp_path,), timeout_seconds=1))
    registry.seal()
    await registry.refresh_health()

    capability = registry.describe()[0]

    assert capability.name == "git.status"
    assert capability.meta.permission.value == "SAFE"
    assert capability.annotations.read_only_hint is True
    assert capability.annotations.destructive_hint is False
    assert capability.input_schema["properties"]["repoIndex"]["exclusiveMaximum"] == 8
    assert capability.output_schema["properties"]["changes"]["maxItems"] == 32


@pytest.mark.asyncio
async def test_git_status_direct_helper_requires_configured_repo() -> None:
    with pytest.raises(ValueError, match="repo_index"):
        await read_git_status(GitStatusInput(), (), Path("/usr/bin/git"))


def test_git_status_tool_requires_git_worktree_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Git worktree"):
        build_git_status_tool((tmp_path,), timeout_seconds=1)


@pytest.fixture(autouse=True)
def fake_git_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_status(
        _git_executable: Path,
        _repo_path: Path,
        _include_untracked: bool,
        _timeout_seconds: float,
    ) -> str:
        return "\n".join(
            [
                "# branch.oid 0123456789abcdef0123456789abcdef01234567",
                "# branch.head main",
                "1 .M N... 100644 100644 100644 "
                "0123456789abcdef0123456789abcdef01234567 "
                "0123456789abcdef0123456789abcdef01234567 tracked.txt",
                "1 A. N... 000000 100644 100644 "
                "0000000000000000000000000000000000000000 "
                "0123456789abcdef0123456789abcdef01234567 staged.txt",
                "? private-plan.txt",
            ]
        )

    monkeypatch.setattr(git_status, "_run_git_status", fake_status)
