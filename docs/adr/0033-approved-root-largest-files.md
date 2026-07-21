# ADR 0033: Approved-root largest-file scan

## Status

Accepted.

## Context

GOFFY needs Jarvis-style Mac assistance such as "Find the largest files on my
Mac" without creating a generic shell or broad filesystem authority. The existing
`mac.files.list` tool already defines explicit approved roots, bounded relative
paths, hidden-file defaults, symlink handling, SAFE metadata, and Android schema
discovery checks.

## Decision

Add `mac.files.largest` as an optional SAFE Hub/MCP tool registered only when
`GOFFY_MAC_FILES_ROOTS` is configured. The tool reuses approved-root policy,
accepts root index, relative path, bounded result count, bounded scan depth, and
hidden-file preference, then returns top regular files by relative path and size.

The tool must:

- read metadata only, never file contents
- never expose absolute root paths
- reject traversal and symlink path components
- skip symlink entries instead of following targets
- stop at fixed result, depth, and scan-count bounds
- report truncation and skipped-entry counts

Android invokes only the default approved root in this slice through exact
deterministic commands and verifies the Hub schema before execution.

## Consequences

This provides a useful Mac cleanup/discovery capability without introducing
unrestricted filesystem or shell access. Richer root/path selection, deletion,
moving files, and file-content reads remain separate future policy decisions.
