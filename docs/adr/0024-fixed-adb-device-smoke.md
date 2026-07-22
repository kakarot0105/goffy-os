# ADR 0024: Fixed ADB Moto G device smoke automation

## Status

Accepted

## Context

GOFFY needs repeatable real-device evidence for the Moto G without turning the
Mac into a general remote-control surface for the phone. The existing validation
pipeline is intentionally phone-read-only, so it cannot prove install, launch,
typed PHONE commands, visible verification, screenshots, or bounded app logs.

A reuse-first scan found mature Android UI automation projects, including
`openatx/uiautomator2`, `xiaocong/uiautomator`, `openatx/android-uiautomator-server`,
and Appium's UiAutomator2 driver. They are useful for larger QA suites, but this
slice needs a narrow smoke check with no added runtime dependency, no device-side
automation service, and no broad command input surface.

## Decision

- Add a stdlib-only `scripts/run_moto_g_device_smoke.py` runner around fixed
  Android SDK `adb` commands.
- Keep plan mode as the default. Mutating mode requires both `--execute` and
  `--confirm-device-mutation`.
- Resolve `adb` only from the configured Android SDK `platform-tools` path.
  Mutating mode rejects PATH `adb` and alternate repo roots.
- Before mutating, require exactly one authorized Moto G target or an explicit
  `--device-serial`, verify the target model, and pin every ADB command with
  `-s <device-serial>`.
- Restrict mutating mode to the fixed smoke commands: `check my battery level`
  and optional `check my Mac status`.
- When `--include-mac` receives `--debug-hub-token-file`, accept only a
  short-lived ADB-safe raw token file under `.goffy-validation`; the token must
  be one line, 24..120 characters, using only `A-Z`, `a-z`, `0-9`, `.`, `_`, or
  `-`. Type it into the foreground debug-only Hub setup field, and verify the
  fixed `ws://127.0.0.1:8787/ws/v1` endpoint becomes configured before
  submitting the MAC command.
- Use `adb shell uiautomator dump` only to locate the command field, tap the
  fixed UI elements, verify the launch-visible HOME shell and HOME setup card
  markers, reveal the device-map viewport with one bounded scroll, and verify
  markers that appear after the matching command text.
- Treat prior timeline entries as stale. Verification requires a new matching
  task card below `TASK TIMELINE`, then checks the newest matching card markers.
- Save bounded artifacts under `.goffy-validation/device-smoke/`: UI XML,
  screenshot, and at most the last 200 GOFFY process logcat lines.
- Do not clear app data, forget a saved Hub link, start the Hub, or broaden Hub
  network exposure. Do not print or save the debug token in rendered reports.

## Consequences

The script can verify the first Moto G HOME surface, HOME setup card, read-only
device-map viewport, and PHONE smoke path and, when the Hub link is already ready
or a redacted local debug token file is provided, the MAC smoke path without
importing or installing an automation framework. The command surface remains
narrow and reviewable.

This is less expressive than Appium or a full UIAutomator instrumentation test.
It may need app-specific maintenance if the GOFFY Compose hierarchy changes. A
larger QA suite can revisit Appium, Android instrumentation UI Automator, or
`uiautomator2` after physical-device smoke coverage is stable.

## Rejected alternatives

- Add `openatx/uiautomator2`. Rejected for this slice because it runs a
  device-side HTTP service and adds a broader automation dependency surface than
  needed.
- Add `xiaocong/uiautomator`. Rejected because it is older, API-range constrained,
  and still broader than the fixed smoke flow.
- Add Appium UiAutomator2. Rejected because the WebDriver stack is too heavy for
  a single install-launch-command smoke check.
- Build a generic ADB command runner. Rejected because GOFFY must not create
  unrestricted shell or device-control tools.
