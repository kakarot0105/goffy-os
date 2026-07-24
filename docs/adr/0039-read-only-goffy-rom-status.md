# ADR 0039: Read-Only GOFFY ROM Status And Checklist

## Status

Accepted.

## Context

GOFFY is now ROM-first, but ROM-0 is intentionally blocked until bootloader,
stock restore, fastboot visibility, and GSI evidence are proven for the exact
Moto target. The phone still needs to answer "what are we building now?" from
current local project evidence without turning that question into a flashing or
shell-control surface.

## Decision

Add `goffy.rom.status` and `goffy.rom.checklist` as default SAFE Hub/MCP tools
and Android MAC routes. Both tools accept no arguments and read only fixed
artifact names under the configured GOFFY repo root:

- `.goffy-validation/rom-0-refresh-report.json`
- `.goffy-validation/rom-0-operator-checklist.json`

The Hub status tool returns bounded structured fields for ROM-0 status,
stale-report state, unlock, stock, GSI, DSU preflight, fastboot, approval gates,
blocker count, visible blockers, and next action. The checklist tool returns
bounded step counts, safe next-step summaries, visible blockers, and next
action. Missing, stale, malformed, or unsafe-display evidence produces
schema-valid not-ready status. Both tools reject symlinked validation
directories and never accept user-supplied paths.

Android exact-checks the capability schema/version/permission before invocation,
displays the bounded result in the timeline, reads a short speech summary when
requested, and stores only closed audit metadata. Checklist speech names only
the safe next step title, counts, and withheld destructive-action state.

## Consequences

- GOFFY can report its own ROM-readiness state through the same observable
  Hub/Android tool loop used by other MAC tasks.
- ROM status/checklist remains separate from ROM authority. No unlock, reboot,
  flash, erase, wipe, boot, shell, arbitrary artifact-read, raw artifact-path, or
  command-string capability is introduced.
- The default Hub registry grows by SAFE ROM metadata tools, so exact tool-list
  and health tests include `goffy.rom.status` and `goffy.rom.checklist`.
- Physical Moto smoke for the checklist route must verify the phone sees
  `VERIFIED` and the SAFE/MAC tool timeline before this becomes a relied-on
  operator surface.
