# GOFFY OS ROM Feasibility

Status: ROM-first track opened on 2026-07-21.

GOFFY OS should become a real phone operating system when the exact Moto target
can support it safely. Until bootloader, stock restore, and boot validation are
proven, the Android app/default-launcher layer remains the safe bootstrap and
fallback environment.

## Target Device

Read-only ADB evidence from the connected phone:

- Model: `moto g - 2025`
- Codename: `kansas`
- Product: `kansas_g_sys`
- SoC: MediaTek `MT6835`
- Android: `16`, SDK `36`
- Build: `W1VKS36H.9-12-9-8-2`, incremental `ebe4e3-2b6752`
- Carrier property: `tracfone`
- Active slot: `_b`
- Dynamic partitions: `true`
- Treble: `true`
- DSU package: `true`
- DSU `START_INSTALL` activity: `true`
- Verified boot: `green`
- Bootloader: `ro.boot.flash.locked=1`,
  `ro.boot.vbmeta.device_state=locked`

Current automated probe:

```bash
.venv/bin/python scripts/rom_feasibility_probe.py --device-serial <device-serial> --json > .goffy-validation/rom-feasibility.json
.venv/bin/python scripts/create_rom_planning_checklist.py .goffy-validation/rom-feasibility.json
```

The probe is read-only. It does not reboot, run fastboot, unlock, flash, erase,
root, or write to the phone. It redacts the device serial in rendered commands.
The checklist generator only reads the saved probe JSON and emits blocked or
template-only next steps. It will not emit DSU staging templates unless the input
contains structured stock restore evidence: `source_url`, `archive_name`,
`sha256`, and `rollback_doc`.

## Product Direction

The ROM path has priority over building a polished launcher as the final product.
The launcher/app remains valuable only as:

- A safe place to develop the agent loop, MCP policy, pairing, audit, and tools.
- A fallback for locked-carrier devices where flashing is not possible.
- A bootstrap app that can be preinstalled or privileged later inside a GOFFY ROM.
- A real-device validation harness before any destructive bootloader or flashing work.

The preferred ROM sequence is:

1. Prove bootloader unlock eligibility for this exact unit.
2. Obtain a stock restore path before any destructive action.
3. Try the least-destructive GSI/DSU route first.
4. If GSI works, build GOFFY as a system/privileged app plus first-boot setup.
5. Only after GSI limits are clear, consider full device-tree ROM bring-up.

## Current Blocker

The phone is currently locked:

- `ro.boot.flash.locked=1`
- `ro.boot.vbmeta.device_state=locked`
- `ro.boot.verifiedbootstate=green`

Do not flash, root, boot custom images, patch boot/init_boot, or run exploit
tools while this remains true.

Motorola says many recent devices support bootloader unlocking but restrictions
exist for service-provider-exclusive models. This unit reports `tracfone`, so
eligibility must be confirmed through Motorola's official unlock process before
we treat ROM work as possible.

## Reuse-First ROM Strategy

Before writing device-specific ROM code, reuse mature work where possible:

- Use Android GSI/DSU first because the phone reports Treble and dynamic
  partitions.
- Reuse AOSP/LineageOS build infrastructure instead of inventing an OS build
  system.
- Reuse public Motorola kernel/device/vendor sources only after matching
  `kansas`, `MT6835`, and the installed Android generation.
- Reuse existing GSI projects only after checking license, maintainership,
  Android version, reported Moto/MediaTek issues, and revert path.
- Build device-tree/vendor bring-up from scratch only if GSI/DSU is inadequate
  and matching source material exists.

## Required Gates

No destructive ROM work until all gates are satisfied:

- User confirms full data backup is complete.
- OEM unlocking is visible/enabled on the phone.
- Motorola unlock-token eligibility is confirmed for this exact unit.
- Stock firmware/recovery package matching `kansas_g_sys` is downloaded and
  hash-recorded.
- We have documented how to recover with Motorola Rescue or stock fastboot images.
- `adb` and `fastboot` both see the device in their respective modes.
- The first ROM experiment has a written rollback plan.

The ROM-0 planning and DSU staging guide is in
[`docs/setup/rom-0-planning-checklist.md`](docs/setup/rom-0-planning-checklist.md).
Manual restore/unlock evidence requirements are in
[`docs/setup/rom-0-manual-gates.md`](docs/setup/rom-0-manual-gates.md).

## First ROM Milestone

Milestone ROM-0 is feasibility, not flashing.

Acceptance criteria:

- `scripts/rom_feasibility_probe.py` passes or reports only documented manual
  unlock blockers.
- Bootloader unlock eligibility result is recorded.
- Stock restore path is documented with source URL and hash.
- First GSI/DSU candidate list is selected with licenses and known Moto/MediaTek
  risks.
- A no-flash planning checklist exists, with DSU staging templates emitted only
  after structured stock restore evidence exists.

## Current ROM-0 Source Decisions

- Primary restore source: Motorola Software Fix Rescue, because it is the
  official Motorola restore route. Current limitation: Motorola documents the
  download as Windows PC only.
- Secondary firmware evidence: Lolinet Kansas RETUS mirror, because it lists
  Kansas archives but is not an official restore authority.
- First GSI candidate: official Google Android 16 ARM64 GSI through Android DSU,
  using Google's release page SHA-256 before any boot attempt.
- Second GSI candidate: TrebleDroid / ponces AOSP GSI only if official GSI is
  too limited.
- Helper candidate: DSU Sideloader only if built-in DSU Loader is unavailable.

The exact stock package checksum remains open because we have not downloaded or
hash-recorded a restore archive.

## ROM Packaging Readiness

GOFFY now has a ROM-side system-app package descriptor in
[`rom/system-app/goffy-system-app.json`](rom/system-app/goffy-system-app.json).
It intentionally targets a non-privileged system app first:

- No platform signing.
- The Gradle release artifact is unsigned and must be signed with a dedicated
  GOFFY release key before ROM import.
- No `priv-app` permission grants.
- No signature or privileged Android permissions.
- Camera remains foreground and user-approved only.
- The Android manifest declares a separate Home-shell intent filter so GOFFY can
  be selected as the home surface when installed or preinstalled.
- Physical Moto validation after debug reinstall showed `dev.goffy.os/.MainActivity`
  in both Android HOME and normal LAUNCHER query results.

The descriptor is validated by:

```bash
.venv/bin/python scripts/validate_rom_system_app.py
.venv/bin/python scripts/create_aosp_product_import.py --aosp-root /path/to/aosp --apk /path/to/GoffyOS-signed.apk
```

This prepares GOFFY for inclusion in a future AOSP/GSI build tree without
claiming that the Moto can be flashed yet.

The AOSP import command is a dry-run planner unless both `--execute` and
`--confirm-aosp-tree-mutation` are supplied. It copies only the reviewed product
templates and an externally signed `GoffyOS.apk`, refuses the unsigned Gradle
release artifact by default, requires an APK Signature Scheme v2/v3 signing
block, rejects debug build artifacts, and refuses to overwrite different existing
AOSP files.

## Source Notes

- Motorola bootloader support states that many recent devices are supported but
  service-provider-exclusive models can be restricted:
  https://en-us.support.motorola.com/app/answers/detail/a_id/89973
- Motorola's bootloader legal warning says unlocking or modifying the OS can
  render a device unusable and void warranty/support:
  https://en-us.support.motorola.com/euf/assets/docs/Bootloader-Legal_Agreement_and_Warning.pdf
- Android GSI requirements include unlocked bootloader, Treble compliance, and
  Android 9+ launch/update expectations:
  https://developer.android.com/topic/generic-system-image
- Android DSU can boot a GSI-like guest OS without corrupting the current system
  image, but it depends on dynamic partitions and trusted images:
  https://developer.android.com/topic/dsu
- AOSP GSI documentation describes GSI as a pure Android/Treble implementation
  used to validate vendor interfaces:
  https://source.android.com/docs/core/tests/vts/gsi

## Current Decision

GOFFY should not invest heavily in launcher polish until ROM-0 answers whether
this Moto G can boot a recoverable GSI/custom system. The immediate engineering
work should be ROM feasibility, stock restore preparation, GSI candidate
selection, and safe boot validation.
