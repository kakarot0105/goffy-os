# ADR 0034: Safe Mac Process List Tool

## Status

Accepted.

## Context

GOFFY needs Jarvis-style answers to explicit questions such as "What's running
on my Mac?" without creating process-control authority, shell access, or a broad
host-inspection channel. Reuse-first review found `psutil` to be the right base
library: it is mature, cross-platform, Python-native, and distributed under a
permissive BSD-style license. Shell commands such as `ps`, `top`, or
Activity Monitor automation were rejected because they would require parsing
human output or automating a broader system surface.

Sources reviewed:

- `psutil` repository: https://github.com/giampaolo/psutil
- `psutil` package metadata: https://pypi.org/project/psutil/
- `psutil` documentation: https://psutil.readthedocs.io/

## Decision

Add `mac.processes.list` as a default SAFE Hub/MCP tool on macOS Hub hosts only.
Non-macOS hosts do not register it, and direct health/execution checks fail
closed. The tool accepts only `maxEntries`, bounded from 1 through 25, and
returns a bounded snapshot sorted by RSS memory. Each entry contains PID,
sanitized process-name basename, status, RSS bytes, and optional start time.

The tool must not return command lines, executable paths, environment variables,
open files, network connections, current working directories, or user names. It
must catch common process-race and access-denied errors, report skipped counts,
and cap total scanning. Health checks must prove only `psutil` availability and
must not enumerate processes.

Android invokes only exact deterministic process-list commands after discovery
proves version, target, permission, schema, and safety annotations. Android
rejects path-like process names, displays only bounded metadata, does not speak
process names aloud, and stores only redacted terminal audit metadata.

## Consequences

The user gets a real, useful Mac-awareness capability with no generic shell,
process control, or hidden background scan. Future process filtering, app
opening, killing, restart, or per-process actions require separate typed tools,
permission classification, approval UX, audit semantics, and verification.
