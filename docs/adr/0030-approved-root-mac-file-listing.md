# ADR 0030: Approved-Root Mac File Listing

## Status

Accepted

## Context

Jarvis-like Mac workflows need file awareness, but a generic file browser or
shell-backed command would expand authority too quickly. GOFFY needs a first Mac
file capability that is useful for discovery while staying read-only,
allowlisted, and auditable through the existing Hub/MCP boundary.

## Decision

Add `mac.files.list` as an optional SAFE Hub tool. The tool is registered only
when `GOFFY_MAC_FILES_ROOTS` contains one or more existing absolute directories.
Inputs select a `rootIndex`, a relative path, an entry limit, and whether hidden
entries are included. Output returns bounded metadata only: root index/name,
relative path, entry names, entry kind, size for regular files, modification
time, and truncation status. Absolute approved-root paths are not returned.

The implementation uses Python stdlib path APIs, not a third-party file server
and not shell execution. Listed symlink entries are classified with lstat data
and their targets are not followed. Relative paths are resolved against the
approved root and rejected if they escape it.

## Consequences

- File listing remains disabled until the operator explicitly configures roots.
- This slice does not read file contents or mutate files.
- Android routing is intentionally limited to default-root listing commands;
  richer root/path selection still needs separate UX and policy review.
- Future `mac.files.read`, create, move, or search tools need separate schemas,
  permission levels, and review.
