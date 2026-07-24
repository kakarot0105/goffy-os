# ADR 0039: Read-Only GOFFY ROM Status

## Status

Accepted.

## Context

GOFFY is now ROM-first, but ROM-0 is intentionally blocked until bootloader,
stock restore, fastboot visibility, and GSI evidence are proven for the exact
Moto target. The phone still needs to answer "what are we building now?" from
current local project evidence without turning that question into a flashing or
shell-control surface.

## Decision

Add `goffy.rom.status` as a default SAFE Hub/MCP tool and Android MAC route.
The tool accepts no arguments and reads only fixed artifact names under the
configured GOFFY repo root:

- `.goffy-validation/rom-0-refresh-report.json`
- `.goffy-validation/rom-0-operator-checklist.json`

The Hub returns bounded structured fields for ROM-0 status, stale-report state,
unlock, stock, GSI, DSU preflight, fastboot, approval gates, blocker count,
visible blockers, and next action. Missing, stale, malformed, or unsafe-display
evidence produces schema-valid not-ready status. The tool rejects symlinked
validation directories and never accepts user-supplied paths.

Android exact-checks the capability schema/version/permission before invocation,
displays the bounded result in the timeline, reads a short speech summary when
requested, and stores only closed audit metadata.

## Consequences

- GOFFY can report its own ROM-readiness state through the same observable
  Hub/Android tool loop used by other MAC tasks.
- ROM status remains separate from ROM authority. No unlock, reboot, flash,
  erase, wipe, boot, shell, or arbitrary artifact-read capability is introduced.
- The default Hub registry grows by one SAFE tool, so exact tool-list and health
  tests include `goffy.rom.status`.
- Physical Moto smoke for this route remains future work.
