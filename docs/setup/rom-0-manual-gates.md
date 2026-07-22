# ROM-0 Manual Gates

Status: required before any bootloader unlock, DSU staging, or custom ROM work.

This document defines the evidence GOFFY needs before a human even reviews a
destructive ROM step. It is not approval to unlock, flash, erase, root, or boot a
custom image.

## Manual Action Packet

Start with a packet generated from the latest read-only ROM probe:

```bash
.venv/bin/python scripts/create_rom0_manual_action_packet.py \
  .goffy-validation/rom-feasibility-current.json \
  --output .goffy-validation/rom-0-manual-action-packet.md
```

The packet is a local checklist for the human operator. It identifies missing
stock-restore and OEM/Motorola unlock-eligibility evidence, gives the exact
GOFFY evidence-helper commands to run after manual checks, and refuses to emit
unlock, flash, erase, fastboot-reboot, root, or boot-image mutation commands.
It may also consume already-created redacted evidence:

```bash
.venv/bin/python scripts/create_rom0_manual_action_packet.py \
  .goffy-validation/rom-feasibility-current.json \
  --unlock-eligibility-evidence .goffy-validation/rom-unlock-eligibility-evidence.json \
  --stock-restore-evidence .goffy-validation/rom-stock-restore-evidence.json \
  --output .goffy-validation/rom-0-manual-action-packet.md
```

## Evidence File

Create a local JSON file under `.goffy-validation/`, not in the repo:

```bash
.venv/bin/python scripts/create_rom_manual_gates_template.py \
  --probe-json .goffy-validation/rom-feasibility-current.json
```

This writes `.goffy-validation/rom-0-manual-gates.template.json` with safe
blocked defaults: backup and OEM unlock are `false`, Motorola eligibility is
`unknown`, destructive approval is `not_requested`, and `target_device` is
seeded from the latest read-only ROM probe. It never runs ADB, fastboot, unlock,
flash, root, shell, or network actions.

After creating stock-restore evidence, seed the template with the exact
redacted restore, unlock-eligibility, and target-device fields:

```bash
.venv/bin/python scripts/create_rom_manual_gates_template.py \
  --probe-json .goffy-validation/rom-feasibility-current.json \
  --unlock-eligibility-evidence .goffy-validation/rom-unlock-eligibility-evidence.json \
  --stock-restore-evidence .goffy-validation/rom-stock-restore-evidence.json \
  --output .goffy-validation/rom-0-manual-gates.json
```

The generator rejects sensitive keys, unsupported stock-restore fields,
non-Motorola restore URLs, invalid archive/checksum/path values, and symlinked
`.goffy-validation` output roots. It writes only under `.goffy-validation`
unless `--stdout` is used for review.

```json
{
  "schema_version": "goffy.rom-manual-gates.v1",
  "backup_confirmed": true,
  "oem_unlocking_enabled": true,
  "motorola_unlock_eligibility": "eligible",
  "destructive_approval": "not_requested",
  "target_device": {
    "model": "moto g - 2025",
    "codename": "kansas",
    "product": "kansas_g_sys",
    "hardware_sku": "XT2513V",
    "build_fingerprint": "motorola/kansas_g_sys/kansas:16/W1VKS36H.9-12-9-8-2/ebe4e3-2b6752:user/release-keys",
    "carrier": "tracfone"
  },
  "stock_restore": {
    "source_url": "https://en-us.support.motorola.com/app/softwarefix",
    "archive_name": "exact-firmware-archive-name.zip",
    "sha256": "64 lowercase or uppercase hex characters",
    "rollback_doc": "docs/setup/kansas-stock-rollback.md"
  }
}
```

Do not include IMEI, serial number, tokens, passwords, private keys, screenshots
with identifiers, or carrier-account data.

## Validate Evidence

```bash
.venv/bin/python scripts/validate_rom_manual_gates.py \
  .goffy-validation/rom-0-manual-gates.json \
  --probe-json .goffy-validation/rom-feasibility-current.json
```

The validator:

- Reads only the JSON file and referenced rollback Markdown.
- Requires backup confirmation.
- Requires OEM unlocking to be enabled.
- Requires Motorola unlock eligibility to be recorded as `eligible`.
- Requires the public target-device baseline from the ROM probe: model,
  codename, product, hardware SKU, build fingerprint, and carrier/channel.
- Fails closed without the ROM probe baseline and requires every
  `target_device` value to match that probe.
- Requires codename `kansas`, product `kansas_g_sys`, and a build fingerprint
  containing `kansas_g_sys`.
- Requires the official Motorola Software Fix stock restore source URL.
- Requires a firmware archive filename, not a path.
- Requires a 64-character SHA-256.
- Requires an existing rollback Markdown file inside this repo.
- Requires the rollback Markdown headings in
  `docs/setup/kansas-stock-rollback.template.md`.
- Requires the rollback Markdown to include the exact archive filename and
  SHA-256 from the JSON evidence.
- Requires the rollback Markdown to include the exact public target-device
  values from the JSON evidence.
- Rejects sensitive keys such as `imei`, `serial`, `token`, `password`,
  `secret`, `credential`, `meid`, `iccid`, and similar private identifiers.
- Rejects unknown `target_device` keys instead of preserving free-form device
  metadata.
- Rejects unknown `stock_restore` keys instead of preserving local archive paths
  or free-form restore metadata.
- Never runs `adb`, `fastboot`, shell commands, unlock commands, flash commands,
  root tools, or network calls.

Passing validation means only `READY_FOR_HUMAN_REVIEW`. It does not mean GOFFY
may unlock or flash the phone.

## Unlock Eligibility Evidence Helper

After manually checking Developer options and Motorola's bootloader eligibility
page, create redacted evidence without storing IMEI, serial number, unlock data,
tokens, screenshots, or account details:

```bash
.venv/bin/python scripts/create_rom_unlock_eligibility_evidence.py \
  --oem-unlocking-visible yes \
  --oem-unlocking-enabled yes \
  --motorola-eligibility eligible \
  --operator-note-code checked_no_identifiers_stored \
  --output .goffy-validation/rom-unlock-eligibility-evidence.json
```

This helper only records manual observations. It does not run ADB, fastboot,
unlock, flash, erase, root, shell, or network actions, and it does not authorize
destructive work. It stores only a closed-set note code, not free-form text.

## Stock Restore Evidence Helper

After downloading the exact stock restore archive locally, generate a redacted
evidence fragment without committing the archive or its local path:

```bash
.venv/bin/python scripts/create_rom_stock_restore_evidence.py \
  --archive ~/Downloads/exact-firmware-archive-name.zip \
  --source-url https://en-us.support.motorola.com/app/softwarefix \
  --rollback-doc docs/setup/kansas-stock-rollback.md \
  --output .goffy-validation/rom-stock-restore-evidence.json
```

The helper hashes the local archive, records only the archive filename, accepts
only the official Motorola Software Fix source URL, rejects source URLs with
credentials, query, or fragment components, writes only under a non-symlinked
`.goffy-validation` path when `--output` is used, and performs no network, ADB,
fastboot, unlock, flash, or root action.

Do not create stock-restore evidence from nearby firmware names. For the current
Moto G 2025 `kansas` unit, public source checks on 2026-07-21 confirmed the
installed build `W1VKS36H.9-12-9-8-2` in Verizon and PhoneCopy metadata, while
the Lolinet Kansas RETUS mirror only exposed nearby archives. Nearby firmware is
not rollback evidence; ROM-0 still requires an exact archive plus SHA-256.

To compare archive names from a manually inspected source without downloading or
flashing anything, create a candidate report:

```bash
.venv/bin/python scripts/create_rom_stock_candidate_report.py \
  .goffy-validation/rom-feasibility-current.json \
  --source-url https://mirrors.lolinet.com/firmware/lenomola/2025/kansas/official/RETUS/ \
  --candidate XT2513-1_KANSAS_RETUS_16_W1VKS36H.9-12-1_subsidy-DEFAULT.zip \
  --json \
  --output .goffy-validation/rom-stock-candidates.json
```

The candidate report is not manual-gate evidence. It only records whether an
archive filename appears to contain the connected phone's codename and installed
build ID on filename token boundaries. A filename match is still not exact
variant proof; manual gates still require the official Motorola Software Fix
URL, local archive, SHA-256, and rollback document.

## Rollback Doc Requirements

Start from [`kansas-stock-rollback.template.md`](kansas-stock-rollback.template.md).
Keep filled rollback documents uncommitted unless a human security review has
confirmed that they contain only public ROM-0 baseline evidence and no private
identifiers.

The rollback Markdown should record:

- Exact phone model, codename, product, hardware SKU, build fingerprint, Android
  release/build, and carrier.
- Restore source URL.
- Firmware archive name.
- SHA-256 command output.
- Where the archive is stored locally.
- Motorola Software Fix result or restore-tool result.
- How to return from a failed DSU/GSI attempt.
- What data is expected to be wiped.
- Who approved any later destructive action and when.

Keep private identifiers out of the rollback document.
