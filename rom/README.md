# GOFFY ROM Integration

This directory holds ROM-side integration artifacts for installing GOFFY into a
future AOSP/GSI-derived image.

Current policy:

- Package GOFFY as a non-privileged system app first.
- Do not grant signature or privileged permissions.
- Do not sign GOFFY with the platform key.
- Do not add a `privapp-permissions` allowlist until a narrow ROM tool requires
  it and a separate security review approves it.
- Keep the Android app fallback installable by normal APK flows.

Integration targets:

- [`system-app/`](system-app/) defines the non-privileged GOFFY APK import.
- [`product/`](product/) defines starter AOSP product-overlay templates that add
  `GoffyOS` through `PRODUCT_PACKAGES` without unlock, flash, root, platform-key,
  or privileged-permission behavior.

Safe import planning:

```bash
.venv/bin/python scripts/create_aosp_product_import.py \
  --aosp-root /path/to/aosp \
  --apk /path/to/GoffyOS-signed.apk
```

The command above is dry-run only. To copy the reviewed templates and signed APK
into an existing AOSP tree, add both `--execute` and
`--confirm-aosp-tree-mutation`. The importer validates the ROM descriptors first,
refuses the default unsigned Gradle APK, requires an APK Signature Scheme v2/v3
signing block, rejects debug build artifacts, and will not overwrite different
existing AOSP files.
