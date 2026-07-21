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
