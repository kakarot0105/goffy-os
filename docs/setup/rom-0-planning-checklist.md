# ROM-0 Planning And DSU Staging Checklist

Status: source-backed planning checklist as of 2026-07-21.

This guide exists to keep GOFFY moving toward a real ROM without accidentally
turning feasibility work into a destructive flashing session. It does not
authorize unlocking, flashing, rooting, erasing, boot-image patching, or exploit
tools.

## Current Device

The connected phone has been observed as:

- Model: `moto g - 2025`
- Codename: `kansas`
- Product: `kansas_g_sys`
- SoC: MediaTek `MT6835`
- Carrier property: `tracfone`
- Android release: `16`
- Treble: `true`
- Dynamic partitions: `true`
- DSU package: `true`
- DSU `START_INSTALL` activity: `true`
- Bootloader state: locked

The current ROM status is blocked until bootloader eligibility and stock restore
are proven.

Manual evidence validation is documented in
[`rom-0-manual-gates.md`](rom-0-manual-gates.md).

## Generate The Checklist

Run the read-only probe and generate a planning checklist:

```bash
.venv/bin/python scripts/rom_feasibility_probe.py --device-serial <device-serial> --json > .goffy-validation/rom-feasibility.json
.venv/bin/python scripts/create_rom_planning_checklist.py .goffy-validation/rom-feasibility.json > .goffy-validation/rom-0-checklist.md
```

The probe command uses `adb` for allowlisted read-only property reads. The
checklist command only reads the saved probe JSON. It does not use `adb`,
`fastboot`, network, root, flashing tools, or shell execution.

Generated checklists include a "Reuse Prior Art" section. This section is not an
import manifest; it is a safety gate that labels each public source as reusable,
pattern-only, inspect-only, or blocked.

## Restore Source Priority

- Primary: Motorola Software Fix Rescue.
  Source: https://en-us.support.motorola.com/app/softwarefix
  Reason: official Motorola route for software repair and rescue.
  Constraint: Motorola documents Software Fix as a Windows PC download.

- Procedure guide: Motorola Rescue Software Update.
  Source: https://en-us.support.motorola.com/app/answers/detail/a_id/167770
  Reason: Motorola documents that Rescue matches firmware after reading the
  phone identifier, downloads a large firmware package, and factory-resets the
  device.

- Secondary evidence only: Lolinet Lenomola Kansas mirror.
  Source: https://mirrors.lolinet.com/firmware/lenomola/2025/kansas/official/RETUS/
  Reason: it lists Kansas firmware archives, but it is not Motorola's official
  rescue path. Use it only for filename research unless a package is downloaded,
  hash-recorded, and matched to this exact unit.

Stock restore is not complete until the exact archive, build, source URL,
SHA-256, and rollback steps are recorded.

## First GSI/DSU Candidate Order

- Candidate 1: Google Android 16 GSI through DSU Loader or command-line DSU.
  Source: https://developer.android.com/topic/generic-system-image/releases
  License note: use under Google's GSI download terms; do not redistribute.
  Reason: official Android 16 ARM64 GSI is the safest first boot experiment,
  and the releases page publishes SHA-256 checksums.
  Risk: Google validates Android 16 GSI binaries on Pixel devices, not this Moto
  Kansas / MediaTek device.

- Candidate 2: TrebleDroid / ponces AOSP GSI.
  Source: https://github.com/ponces/treble_aosp
  License note: Apache-2.0 repo license; verify release artifact licenses before
  reuse.
  Reason: mature community GSI path when official GSI is too limited.
  Risk: the repo was archived in 2026 and release notes mention device-specific
  issues such as missing internet on some devices.

- Candidate 3: DSU Sideloader.
  Source: https://github.com/VegaBobo/DSU-Sideloader
  License note: Apache-2.0.
  Reason: helper app if built-in DSU Loader is hidden or too limited.
  Risk: it still requires unlocked bootloader, dynamic partitions, a local GSI
  file, and storage access.

Prefer Android 16 ARM64 for the ROM-0 baseline because the phone is already on
Android 16. Do not jump to Android 17 until Android 16 GSI behavior is measured.

## Reuse Prior Art

- Official Motorola MTK kernel source.
  Source: https://github.com/MotorolaMobilityLLC/kernel-mtk
  Decision: `BLOCKED_UNTIL_EXACT_KANSAS_BUILD_MATCH`.
  Reason: it is the official Motorola MTK kernel publication, and a related
  `MMI-W1VKS36H.9-12-1` tag exists, but current search has not found exact
  `kansas` or installed-build `W1VKS36H.9-12-9-8-2` source evidence. Do not
  copy or build kernel code until exact build provenance is found.

- Exact Kansas recovery/device-tree candidate.
  Source: https://github.com/councilcj/android_device_motorola_kansas
  Decision: `INSPECT_ONLY_DO_NOT_IMPORT`.
  Reason: the repo has no repository-level license metadata, appears to be a
  generated recovery tree, includes prebuilt kernel/dtb/dtbo artifacts, and
  contains anti-rollback-bypass settings. It can inform manual comparison only.

- Related Motorola LineageOS device trees.
  Sources: https://github.com/LineageOS/android_device_motorola_fogo and
  https://github.com/LineageOS/android_device_motorola_pnangn
  Decision: `REUSE_PATTERNS_ONLY_NOT_DEVICE_CONFIG`.
  Reason: these concrete repositories can teach structure and extraction
  patterns, but they have no GitHub license metadata in the current scan and
  target other devices/SoCs. They must not be copied as Kansas configuration.

## Manual Gates

- Full user data backup is complete.
- OEM unlocking is visible and enabled in Developer options.
- Motorola official bootloader eligibility flow accepts this exact unit.
- Stock restore is proven through Motorola Software Fix or a verified firmware
  archive.
- The stock restore package SHA-256 is recorded.
- A rollback procedure exists before any bootloader state change.
- The user explicitly approves the next destructive step.

## Staging Templates Not Included Yet

GOFFY intentionally withholds exact unlock, flash, erase, root, and boot-image
patch commands until the manual gates are complete. The checklist generator can
emit DSU staging templates only after the input JSON includes structured stock
restore evidence:

- `source_url`
- `archive_name`
- `sha256`
- `rollback_doc`

Even then, those templates are device-mutating and approval gated. They are not
safe to execute automatically.

## Source Notes

- Motorola says many recent devices support its bootloader unlock program, but
  service-provider-exclusive models can be restricted:
  https://en-us.support.motorola.com/app/answers/detail/a_id/89973
- Motorola's bootloader warning says unlocking or modifying the OS can render a
  device unusable:
  https://en-us.support.motorola.com/euf/assets/docs/Bootloader-Legal_Agreement_and_Warning.pdf
- Motorola carrier unlock guidance says not all phones can be unlocked due to
  carrier/network/software limitations:
  https://en-us.support.motorola.com/app/answers/detail/a_id/97714
- AOSP documents that bootloader unlock requires OEM unlock eligibility and
  performs a factory reset:
  https://source.android.com/docs/core/architecture/bootloader/locking_unlocking
- Android DSU can boot a GSI guest OS while allowing return to the current system
  image, but it requires dynamic partitions and trusted images:
  https://developer.android.com/topic/dsu
- Android GSI is a pure AOSP implementation for app validation and development:
  https://developer.android.com/topic/generic-system-image
