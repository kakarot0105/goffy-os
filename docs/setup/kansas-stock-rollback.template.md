# Kansas Stock Rollback Template

Copy this template to `docs/setup/kansas-stock-rollback.md` only when the exact
stock firmware archive and SHA-256 are known. Do not include IMEI, serial number,
unlock tokens, account data, screenshots with identifiers, or private paths.

## Device Baseline

- Model: moto g - 2025
- Codename: kansas
- Product: kansas_g_sys
- Hardware SKU: XT2513V
- Build fingerprint:
- Android release/build:
- Carrier/channel:
- ROM feasibility probe file:

## Stock Restore Source

- Source: https://en-us.support.motorola.com/app/softwarefix
- Firmware archive:
- Local storage location: outside git or under `.goffy-validation`

## SHA-256 Evidence

- SHA-256:
- Hash command output:

## Rollback Procedure

1. Keep the phone charged and connected.
2. Restore with Motorola Software Fix before attempting another ROM path.
3. Reboot and verify Android boots normally.
4. Re-run the GOFFY ROM feasibility probe.

## Data Wipe Expectations

- Bootloader unlock may wipe all user data.
- Stock restore may wipe app data, pairing state, photos, downloads, and local
  GOFFY notes.
- Backups must be verified before destructive approval is requested.

## Approval Record

- Destructive approval status: not granted by this document.
- Human reviewer:
- Review timestamp:
- Notes:
