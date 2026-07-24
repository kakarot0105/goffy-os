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
- Hardware SKU: `XT2513V`
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
- OEM unlock properties: `ro.oem_unlock_supported` blank,
  `sys.oem_unlock_allowed` blank
- Bootloader: `ro.boot.flash.locked=1`,
  `ro.boot.vbmeta.device_state=locked`

Current automated probe:

```bash
.venv/bin/python scripts/rom_feasibility_probe.py --device-serial <device-serial> --json > .goffy-validation/rom-feasibility-current.json
.venv/bin/python scripts/create_rom_planning_checklist.py .goffy-validation/rom-feasibility-current.json
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
- `ro.oem_unlock_supported` and `sys.oem_unlock_allowed` are currently blank
  in the read-only probe, so they do not prove eligibility.

Do not flash, root, boot custom images, patch boot/init_boot, or run exploit
tools while this remains true.

Motorola says many recent devices support bootloader unlocking but restrictions
exist for service-provider-exclusive models. This unit reports `tracfone`, so
eligibility must be confirmed through Motorola's official unlock process before
we treat ROM work as possible.

Manual unlock checks can now be recorded as redacted local evidence:

```bash
.venv/bin/python scripts/create_rom_unlock_eligibility_evidence.py \
  --oem-unlocking-visible yes \
  --oem-unlocking-enabled yes \
  --probe-json .goffy-validation/rom-feasibility-current.json \
  --motorola-eligibility eligible \
  --output .goffy-validation/rom-unlock-eligibility-evidence.json
```

This evidence still does not authorize unlocking. It only lets the ROM-0 manual
gate template consume the observed OEM-toggle and Motorola eligibility result
after binding it to the current public Moto probe identity. Re-record unlock
evidence if the current ROM probe is regenerated more than 24 hours after the
manual unlock check.

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

To refresh the current read-only probe and produce a single safe "what do I do
next?" packet for the human checks, run:

```bash
.venv/bin/python scripts/refresh_rom0_action_packet.py
```

The packet is read-only/template-only. It summarizes missing OEM or Motorola
unlock eligibility, stock-restore evidence, read-only fastboot evidence, and
official GSI candidate evidence, links those actions to the typed GOFFY evidence
helpers, regenerates the manual bootloader visibility guide and ordered operator
checklist, redacts the device serial placeholder, and rejects any unlock, flash,
erase, or bootloader-reboot command authority. The refresh command reports
`BLOCKED` while ROM gates are missing, the bootloader probe is still locked, or
manual bootloader-mode fastboot visibility has not been recorded; that is
expected and safer than claiming success before ROM-0 is ready.

To regenerate only the ordered operator checklist from the latest refresh report,
run:

```bash
.venv/bin/python scripts/create_rom0_operator_checklist.py
```

The checklist is non-destructive. It consumes
`.goffy-validation/rom-0-refresh-report.json`, writes JSON/Markdown under
`.goffy-validation`, and explicitly blocks any unlock, DSU, flash, or boot
decision from advancing before exact stock restore evidence exists.

The phone can now ask the Hub for bounded versions of this local state through
`goffy.rom.status`, `goffy.rom.checklist`, and `goffy.rom.features`. In Android, use
`Show GOFFY ROM status`, `Check GOFFY ROM status`, `Is GOFFY ROM ready?`, or
`What are we building now?` for gate status, and use
`Show GOFFY ROM checklist`, `What's left for the GOFFY ROM?`, or
`What ROM-0 steps remain?` for operator next steps. Use
`Show GOFFY ROM features`, `Explain ROM-0 payload`, or
`What features are inserted into the GOFFY ROM?` for the bounded feature payload.
These routes are read-only status reporting. They do not authorize or perform
unlocking, rebooting, flashing, erasing, wiping, booting, or shell execution, and
the checklist/features routes do not expose raw artifact paths or safe command
strings.
The status response includes explicit install-gate statuses for unlock
eligibility, stock restore, official GSI evidence, DSU preflight, fastboot
visibility, and destructive approval. The destructive approval field remains
`WITHHELD`; `romReady` only means ready for manual ROM-0 review, not permission
to install.

To regenerate only the manual bootloader visibility guide without rebooting the
phone, run:

```bash
.venv/bin/python scripts/create_rom_bootloader_visibility_guide.py
```

The guide records blocked/ready/done status for the physical bootloader step and
never emits ADB reboot, fastboot reboot, unlock, flash, erase, wipe, or boot
commands.

To record host fastboot readiness without rebooting the phone, run:

```bash
.venv/bin/python scripts/create_rom_fastboot_evidence.py
```

If the human later manually enters bootloader mode, the same helper can run
`fastboot devices` as a read-only visibility check:

```bash
.venv/bin/python scripts/create_rom_fastboot_evidence.py --manual-bootloader-check
```

The evidence redacts serials and records only `fastboot --version` plus optional
`fastboot devices` output. It never emits unlock, flash, erase, wipe, boot, or
reboot commands.

## First ROM Milestone

Milestone ROM-0 is feasibility, not flashing.

Acceptance criteria:

- `scripts/rom_feasibility_probe.py` passes or reports only documented manual
  unlock blockers.
- Bootloader unlock eligibility result is recorded.
- Stock restore path is documented with source URL and hash.
- Host fastboot evidence is recorded, and manually entered bootloader visibility
  is recorded before any destructive bootloader decision.
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
  too limited and a current release is verified, because the GitHub repo is now
  archived.
- Helper candidate: DSU Sideloader only if built-in DSU Loader is unavailable.
- Generic bootloader-unlock scripts and ROM flashing guides: inspect only.
  Current scans surfaced guides that emit destructive fastboot commands or
  broad device-agnostic instructions. GOFFY reuses official Motorola/Android
  documentation plus its typed local evidence validators instead of importing
  those scripts.

The exact stock package checksum remains open because we have not downloaded or
hash-recorded a restore archive.

When the exact archive is available, create the rollback Markdown from a
redacted draft instead of hand-copying paths or identifiers:

```bash
.venv/bin/python scripts/create_rom_stock_rollback_draft.py \
  --archive ~/Downloads/exact-firmware-archive-name.zip \
  --source-url https://en-us.support.motorola.com/app/softwarefix \
  --probe-json .goffy-validation/rom-feasibility-current.json \
  --output .goffy-validation/kansas-stock-rollback.draft.md
```

The draft generator hashes only the local archive, binds the document to the
current public Moto probe identity, writes only under `.goffy-validation`, and
does not run network, ADB, fastboot, unlock, flash, or root actions. A human must
review the draft before copying it to `docs/setup/kansas-stock-rollback.md`.

After the reviewed Markdown exists, create stock-restore evidence and verify the
rollback bundle before seeding manual gates:

```bash
.venv/bin/python scripts/create_rom_stock_restore_evidence.py \
  --archive ~/Downloads/exact-firmware-archive-name.zip \
  --source-url https://en-us.support.motorola.com/app/softwarefix \
  --rollback-doc docs/setup/kansas-stock-rollback.md \
  --output .goffy-validation/rom-stock-restore-evidence.json

.venv/bin/python scripts/verify_rom_stock_rollback_bundle.py \
  --stock-restore-evidence .goffy-validation/rom-stock-restore-evidence.json \
  --probe-json .goffy-validation/rom-feasibility-current.json \
  --archive ~/Downloads/exact-firmware-archive-name.zip
```

The bundle verifier confirms the rollback Markdown contains the exact archive
name, SHA-256, official Motorola Software Fix source, and current public Moto
probe identity. It never downloads firmware, invokes Software Fix, reboots,
unlocks, flashes, or touches the phone.

## Current Stock Firmware Candidate Evidence

Current stock-candidate scan date: 2026-07-22.

- Installed build from the phone: `W1VKS36H.9-12-9-8-2`,
  incremental `ebe4e3-2b6752`, security patch `2026-06-01`.
- Verizon's Moto G 2025
  [software-update page](https://www.verizon.com/support/motorola-moto-g-update/)
  lists
  `W1VKS36H.9-12-9-8-2` as System Update 12, release date `2026-06-18`,
  Android security patch level June 2026.
- PhoneCopy's public
  [Moto G 5G 2025 device page](https://www.phonecopy.com/en/phones/view/motorola_moto_g_5g_2025)
  corroborates
  `kansas_g_sys/kansas` with `MT6835` and includes
  `w1vks36h.9-12-9-8-2` in observed Android 16 versions.
- Lolinet's
  [Kansas RETUS mirror](https://mirrors.lolinet.com/firmware/lenomola/2025/kansas/official/RETUS/)
  lists nearby archives including
  `XT2513-1_KANSAS_RETUS_16_W1VK36H.9-12...` and
  `XT2513-1_KANSAS_RETUS_16_W1VKS36H.9-12-1...`, but not the exact installed
  `W1VKS36H.9-12-9-8-2` archive.

Decision: nearby firmware is not rollback evidence. ROM-0 remains blocked until
Motorola Software Fix, Verizon/Motorola repair tooling, or a verified firmware
source provides an archive that matches the exact device variant and installed
build, and we record its SHA-256.

The non-destructive candidate matcher can record future manual archive-name
checks without treating filename matches as restore evidence:

```bash
.venv/bin/python scripts/create_rom_stock_candidate_report.py \
  .goffy-validation/rom-feasibility-current.json \
  --candidate <firmware-archive-name.zip> \
  --json \
  --output .goffy-validation/rom-stock-candidates.json
```

Even when an archive name contains the installed build ID, it remains blocked
until variant/source verification, local SHA-256, and rollback documentation are
recorded.

## Current GSI Candidate Evidence

GOFFY now has an offline verifier for the first official Google GSI candidate.
It does not download a GSI, invoke DSU, push files to the phone, reboot, unlock,
flash, or mutate an AOSP checkout. It only hashes an already-downloaded local
archive outside the repo and writes redacted evidence under `.goffy-validation`
after the computed SHA-256 matches Google's release-page checksum.

Before downloading the archive, review Google's official GSI terms yourself and
continue only after you personally accept them.

Current selected Android 16 ARM64 candidate metadata, refreshed from Google's
GSI release page on 2026-07-24:

To detect stale committed metadata before any GSI evidence is recorded, run:

```bash
.venv/bin/python scripts/verify_rom_gsi_metadata_freshness.py
```

The freshness verifier reads only Google's release-page metadata. It does not
download a GSI archive, accept license terms, invoke DSU, push files, reboot,
unlock, flash, or touch the phone.

```bash
.venv/bin/python scripts/create_rom_gsi_candidate_evidence.py \
  --artifact /absolute/path/outside/repo/aosp_arm64-exp-CP11.251209.009.A1-14840729-59a822d9.zip \
  --source-url https://developer.android.com/topic/generic-system-image/releases \
  --download-url https://dl.google.com/developers/android/baklava/images/gsi/aosp_arm64-exp-CP11.251209.009.A1-14840729-59a822d9.zip \
  --expected-sha256 59a822d9a4dd09873009f40c4b97003a2f2dab1b284f2c56b0aaa63dde7e19dd \
  --candidate-name "Official Google Android 16 ARM64 GSI" \
  --android-release 16 \
  --architecture arm64 \
  --output .goffy-validation/rom-gsi-candidate-evidence.json
```

The resulting JSON is candidate integrity evidence only. ROM-0 still requires
manual OEM-unlock eligibility, exact stock restore evidence, and a live
user-approved destructive decision before any bootloader or DSU action.

After exact stock restore evidence and official GSI checksum evidence exist,
create read-only DSU preflight evidence:

```bash
.venv/bin/python scripts/create_rom_dsu_preflight_evidence.py \
  --probe-json .goffy-validation/rom-feasibility-current.json \
  --stock-restore-evidence .goffy-validation/rom-stock-restore-evidence.json \
  --gsi-candidate-evidence .goffy-validation/rom-gsi-candidate-evidence.json \
  --output .goffy-validation/rom-dsu-preflight-evidence.json
```

The preflight uses official Android DSU and GSI documentation as the operating
path, records whether the current probe still shows Treble, dynamic partitions,
the Android Dynamic System package, and a DSU start-install activity, and keeps
install authority `WITHHELD`. It does not import DSU Sideloader or ADB installer
scripts, open DSU, push images, install, reboot, unlock, flash, wipe, or root.

## Current Reuse Prior Art Decisions

Current reuse scan date: 2026-07-22.

Read-only source refresh on 2026-07-22:

- Connected phone reports `ro.boot.hardware.sku=XT2513V`.
- `git ls-remote` against `MotorolaMobilityLLC/kernel-mtk` found
  `MMI-W1VKS36H.9-12-1`, but no `kansas` ref and no exact installed
  `W1VKS36H.9-12-9-8-2` ref.
- GitHub metadata reports `ponces/treble_aosp` as Apache-2.0 but archived, so
  it stays a secondary GSI reference/candidate, not an actively maintained base.
- DSU Sideloader remains useful prior art for later UX, but it is not imported
  into the ROM-0 refresh path because that path must stay read-only and
  non-installing.

- Official kernel candidate: `MotorolaMobilityLLC/kernel-mtk`.
  Decision: `BLOCKED_UNTIL_EXACT_KANSAS_BUILD_MATCH`.
  Reason: it is the official Motorola MTK kernel publication, and a related
  `MMI-W1VKS36H.9-12-1` tag exists, but current search did not locate exact
  `kansas` or installed-build `W1VKS36H.9-12-9-8-2` evidence. Do not build or
  copy kernel code until a branch, tag, or release note matches this unit.

- Exact Kansas device-tree candidate:
  `councilcj/android_device_motorola_kansas`.
  Decision: `INSPECT_ONLY_DO_NOT_IMPORT`.
  Reason: the repository targets `kansas`, but it has no repository-level
  license metadata, appears generated for recovery, includes prebuilt
  kernel/dtb/dtbo artifacts, and contains anti-rollback-bypass settings. It may
  be useful for manual comparison, but GOFFY must not import code, binaries, or
  generated files from it.

- Related Motorola LineageOS device trees:
  `LineageOS/android_device_motorola_fogo` and
  `LineageOS/android_device_motorola_pnangn`.
  Decision: `REUSE_PATTERNS_ONLY_NOT_DEVICE_CONFIG`.
  Reason: these concrete repositories can teach AOSP/Lineage product structure
  and extraction patterns, but they have no GitHub license metadata in the
  current scan and target different devices/SoCs. Copying configuration would
  be unsafe for boot, radio, camera, verified boot, and recovery behavior.

These decisions are emitted by
[`scripts/create_rom_planning_checklist.py`](scripts/create_rom_planning_checklist.py)
under "Reuse Prior Art" so generated ROM-0 checklists carry the same reuse gate.
The current refresh helper reuses GOFFY's typed probe, evidence, and packet
validators instead of external installer or flashing automation.

## ROM Packaging Readiness

GOFFY now has a ROM-side system-app package descriptor in
[`rom/system-app/goffy-system-app.json`](rom/system-app/goffy-system-app.json).
GOFFY also has a ROM-0 feature payload contract in
[`rom/features/goffy-rom-features.json`](rom/features/goffy-rom-features.json).
That contract records the exact Jarvis-like features intended for first ROM
insertion: GOFFY HOME, visible agent timeline, secure Mac Hub pairing, local
phone tools, foreground voice/camera/QR/OCR, disabled-by-default local intent
fallback, ROM status, and charging dock awake behavior. Its validator blocks
privileged authority, platform signing, ROM/system destructive actions,
background camera/microphone, unreviewed Android permissions, unreviewed MCP
tools, and unlock/flash/root/verity behavior. ROM status/checklist MCP entries
are read-only metadata surfaces only. App-private memory forget tools
are recorded separately as exact approval-gated GOFFY SQLite mutations, not ROM
or phone-data deletion.
It intentionally targets a non-privileged system app first:

- No platform signing.
- The Gradle release artifact is unsigned and must be signed with a dedicated
  GOFFY release key before ROM import.
- No `priv-app` permission grants.
- No signature or privileged Android permissions.
- The ROM descriptor and validator now require `dev.goffy.os/.MainActivity` to
  stay exported and user-selectable as Android HOME, while still keeping GOFFY
  non-privileged and user-approved for camera/microphone access.
- Camera remains foreground and user-approved only.
- The Android manifest declares a separate Home-shell intent filter so GOFFY can
  be selected as the home surface when installed or preinstalled.
- Physical Moto validation after debug reinstall showed `dev.goffy.os/.MainActivity`
  in both Android HOME and normal LAUNCHER query results.

The descriptor is validated by:

```bash
.venv/bin/python scripts/validate_rom_system_app.py
.venv/bin/python scripts/validate_rom_feature_payload.py
.venv/bin/python scripts/create_aosp_product_import.py \
  --aosp-root /path/to/aosp \
  --apk .goffy-validation/rom-signing/GoffyOS-signed.apk \
  --apk-verification-json .goffy-validation/rom-signing/release-apk-verification.json
```

This prepares GOFFY for inclusion in a future AOSP/GSI build tree without
claiming that the Moto can be flashed yet.

The AOSP import command is a dry-run planner unless both `--execute` and
`--confirm-aosp-tree-mutation` are supplied. It copies only the reviewed product
templates and an externally signed `GoffyOS.apk`, refuses the unsigned Gradle
release artifact by default, requires an APK Signature Scheme v2/v3 signing
block, rejects debug build artifacts, and refuses to overwrite different existing
AOSP files.

Before importing, create a local signing plan without storing keys or passwords
in the repo, sign the APK with the generated `apksigner` command, then verify
the signed artifact:

```bash
./android/gradlew -p android :app:assembleRelease --no-daemon
.venv/bin/python scripts/create_rom_release_signing_plan.py \
  --keystore /absolute/path/outside/repo/goffy-release.jks
.venv/bin/python scripts/verify_rom_release_apk.py \
  --apk .goffy-validation/rom-signing/GoffyOS-signed.apk
```

The plan uses the Android SDK `apksigner`, requires keystore passwords through
environment variable names only, writes plan JSON under `.goffy-validation`, and
does not sign, flash, unlock, erase, or mutate an AOSP checkout. The APK
verifier checks an already signed artifact and records only hash, size, and
v2/v3 signature evidence.

Use the readiness reporter to summarize ROM-0 blockers without touching the
phone or an AOSP checkout:

```bash
.venv/bin/python scripts/create_rom_manual_gates_template.py
.venv/bin/python scripts/verify_rom0_readiness.py \
  --probe-json .goffy-validation/rom-feasibility-current.json \
  --manual-gates-json .goffy-validation/rom-0-manual-gates.json \
  --fastboot-evidence-json .goffy-validation/rom-fastboot-evidence.json \
  --gsi-candidate-evidence-json .goffy-validation/rom-gsi-candidate-evidence.json \
  --dsu-preflight-evidence-json .goffy-validation/rom-dsu-preflight-evidence.json \
  --signing-plan-json .goffy-validation/rom-signing/release-signing-plan.json \
  --apk-verification-json .goffy-validation/rom-signing/release-apk-verification.json \
  --signed-apk .goffy-validation/rom-signing/GoffyOS-signed.apk \
  --aosp-root /path/to/aosp \
  --evidence-root .
```

The reporter requires redacted fastboot evidence but still withholds unlock,
flash, erase, boot, reboot, and root authority. A passing report means the
evidence is ready for human review, not that destructive ROM work has been
approved.

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
