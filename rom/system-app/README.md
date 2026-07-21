# GOFFY System-App Package

This package prepares GOFFY for future ROM integration as a non-privileged
system app.

Files:

- [`goffy-system-app.json`](goffy-system-app.json) records the intended package,
  permissions, install class, and runtime policy.
- [`Android.bp.template`](Android.bp.template) is a Soong `android_app_import`
  template for an AOSP/GSI-derived build tree.

Validation:

```bash
.venv/bin/python scripts/validate_rom_system_app.py
```

Policy:

- Keep `privileged` set to `false`.
- Keep `platform_signed` set to `false`.
- Treat `android/app/build/outputs/apk/release/app-release-unsigned.apk` as an
  unsigned build artifact only.
- Sign the APK with a dedicated GOFFY release key outside the repo before
  copying it into an AOSP tree as `GoffyOS.apk`.
- Keep `privileged_permission_allowlist` empty.
- Keep `CAMERA` and `RECORD_AUDIO` foreground and user-approved only.
- Re-run the validator after any Android manifest permission change.

This is not a flashable image and does not modify the phone.
