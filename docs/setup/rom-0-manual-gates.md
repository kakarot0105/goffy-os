# ROM-0 Manual Gates

Status: required before any bootloader unlock, DSU staging, or custom ROM work.

This document defines the evidence GOFFY needs before a human even reviews a
destructive ROM step. It is not approval to unlock, flash, erase, root, or boot a
custom image.

## Evidence File

Create a local JSON file under `.goffy-validation/`, not in the repo:

```bash
.venv/bin/python scripts/create_rom_manual_gates_template.py
```

This writes `.goffy-validation/rom-0-manual-gates.template.json` with safe
blocked defaults: backup and OEM unlock are `false`, Motorola eligibility is
`unknown`, and destructive approval is `not_requested`. It never runs ADB,
fastboot, unlock, flash, root, shell, or network actions.

After creating stock-restore evidence, seed the template with the exact
redacted restore fields:

```bash
.venv/bin/python scripts/create_rom_manual_gates_template.py \
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
.venv/bin/python scripts/validate_rom_manual_gates.py .goffy-validation/rom-0-manual-gates.json
```

The validator:

- Reads only the JSON file and referenced rollback Markdown.
- Requires backup confirmation.
- Requires OEM unlocking to be enabled.
- Requires Motorola unlock eligibility to be recorded as `eligible`.
- Requires an HTTPS stock restore source.
- Requires a firmware archive filename, not a path.
- Requires a 64-character SHA-256.
- Requires an existing rollback Markdown file inside this repo.
- Requires the rollback Markdown headings in
  `docs/setup/kansas-stock-rollback.template.md`.
- Requires the rollback Markdown to include the exact archive filename and
  SHA-256 from the JSON evidence.
- Rejects sensitive keys such as `imei`, `serial`, `token`, `password`,
  `secret`, and `credential`.
- Never runs `adb`, `fastboot`, shell commands, unlock commands, flash commands,
  root tools, or network calls.

Passing validation means only `READY_FOR_HUMAN_REVIEW`. It does not mean GOFFY
may unlock or flash the phone.

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

The helper hashes the local archive, records only the archive filename, rejects
source URLs with credentials, query, or fragment components, writes only under a
non-symlinked `.goffy-validation` path when `--output` is used, and performs no
network, ADB, fastboot, unlock, flash, or root action.

Do not create stock-restore evidence from nearby firmware names. For the current
Moto G 2025 `kansas` unit, public source checks on 2026-07-21 confirmed the
installed build `W1VKS36H.9-12-9-8-2` in Verizon and PhoneCopy metadata, while
the Lolinet Kansas RETUS mirror only exposed nearby archives. Nearby firmware is
not rollback evidence; ROM-0 still requires an exact archive plus SHA-256.

## Rollback Doc Requirements

Start from [`kansas-stock-rollback.template.md`](kansas-stock-rollback.template.md).

The rollback Markdown should record:

- Exact phone model, codename, product, Android release, build, and carrier.
- Restore source URL.
- Firmware archive name.
- SHA-256 command output.
- Where the archive is stored locally.
- Motorola Software Fix result or restore-tool result.
- How to return from a failed DSU/GSI attempt.
- What data is expected to be wiped.
- Who approved any later destructive action and when.

Keep private identifiers out of the rollback document.
