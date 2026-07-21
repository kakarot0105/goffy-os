# GOFFY Product Overlay

This directory contains starter templates for including GOFFY in a future
AOSP/GSI-derived build as a non-privileged system app.

Files:

- [`AndroidProducts.mk.template`](AndroidProducts.mk.template) registers the
  `goffy_gsi_phone` product makefile and a lab-only `userdebug` lunch choice.
- [`goffy_gsi_phone.mk.template`](goffy_gsi_phone.mk.template) declares product
  identity and inherits the package list.
- [`goffy_product_packages.mk.template`](goffy_product_packages.mk.template)
  includes only the `GoffyOS` module.
- [`goffy-product-overlay.json`](goffy-product-overlay.json) records the safe
  packaging contract.

Validation:

```bash
.venv/bin/python scripts/validate_rom_product_overlay.py
.venv/bin/python scripts/create_aosp_product_import.py --aosp-root /path/to/aosp --apk /path/to/GoffyOS-signed.apk
```

The import command is a plan by default. Execute mode requires
`--execute --confirm-aosp-tree-mutation`, an existing AOSP root, and an externally
signed APK. It writes only:

- `device/goffy/goffy_gsi_phone/AndroidProducts.mk`
- `device/goffy/goffy_gsi_phone/goffy_gsi_phone.mk`
- `device/goffy/goffy_gsi_phone/goffy_product_packages.mk`
- `vendor/goffy/apps/GoffyOS/Android.bp`
- `vendor/goffy/apps/GoffyOS/GoffyOS.apk`

Policy:

- This is not a flashable image.
- Do not add unlock, flash, root, or verity-disabling commands.
- Do not add platform signing, OTA keys, `eng` lunch choices, or privileged
  permissions.
- Keep GOFFY included through `PRODUCT_PACKAGES += GoffyOS`.
- Keep privileged/system authority changes in a separate reviewed descriptor
  version.
