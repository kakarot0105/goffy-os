# ADR 0031: Approved Git Status Tool

## Status

Accepted

## Context

Jarvis-like development workflows need the Mac Hub to answer basic repository
questions before GOFFY can safely run tests, review diffs, or prepare pull
requests. A generic shell command is blocked by policy, and a broad Git library
would add dependency weight before the required surface is clear.

Reuse-first review:

- GitPython: https://github.com/gitpython-developers/gitpython, BSD-3-Clause,
  mature, but it still shells out for many operations and would add a new
  runtime dependency for one status snapshot.
- Dulwich: https://github.com/jelmer/dulwich, Apache-2.0 OR GPL-2.0-or-later,
  mature pure-Python Git implementation, but heavier than needed for a bounded
  read-only status snapshot.
- pygit2/libgit2: https://www.pygit2.org/, GPLv2 with linking exception,
  mature, but adds native-library packaging and licensing review complexity.
- Git porcelain v2: https://git-scm.com/docs/git-status, designed as stable
  script-readable status output.

## Decision

Add `git.status` as an optional SAFE Hub/MCP tool. The tool is registered only
when `GOFFY_GIT_REPO_ROOTS` contains one or more existing absolute directories
that look like Git worktree roots. Clients select a `repoIndex`, `maxChanges`,
and whether to include untracked files. They cannot supply paths or command
arguments.

The implementation executes the locally resolved Git binary with fixed
arguments:

```text
git status --porcelain=v2 --branch --no-renames --untracked-files=<all|no>
```

Execution uses `subprocess.run` with `shell=False`, an approved repo working
directory, a short timeout, a minimal environment, no network operation, no
credential prompt, and bounded output parsing. The structured result returns
repo index/name, branch and upstream ref-name metadata, clean state, change
counts, bounded change paths, truncation state, and approved repo display names.
It never returns the absolute approved root, file contents, diffs, remote URLs,
remote configuration, secrets, or command text.

## Consequences

- `git.status` is disabled until the operator explicitly configures approved
  repositories.
- This slice does not run tests, read diffs, commit, push, fetch, or mutate Git
  state.
- The security scanner keeps `subprocess` blocked everywhere except the audited
  fixed-argument Git status module; `shell=True` remains blocked there too.
- Android routing and UI for `git.status` is a separate follow-up so the Hub/MCP
  authority can be reviewed first.
- Future `git.diff`, `git.test`, `git.commit`, or GitHub tools need separate
  schemas, permission levels, approvals, and verification.
