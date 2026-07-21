# GOFFY System-App Package

This package prepares GOFFY for future ROM integration as a non-privileged
system app.

Files:

- [`goffy-system-app.json`](goffy-system-app.json) records the intended package,
  permissions, install class, home-surface contract, and runtime policy.
- [`Android.bp.template`](Android.bp.template) is a Soong `android_app_import`
  template for an AOSP/GSI-derived build tree.

Validation after a human signs the APK with the generated signing-plan command:

```bash
.venv/bin/python scripts/validate_rom_system_app.py
.venv/bin/python scripts/create_rom_release_signing_plan.py \
  --keystore /absolute/path/outside/repo/goffy-release.jks
.venv/bin/python scripts/verify_rom_release_apk.py \
  --apk .goffy-validation/rom-signing/GoffyOS-signed.apk
```

Policy:

- Keep `privileged` set to `false`.
- Keep `platform_signed` set to `false`.
- Treat `android/app/build/outputs/apk/release/app-release-unsigned.apk` as an
  unsigned build artifact only.
- Sign the APK with a dedicated GOFFY release key outside the repo before
  copying it into an AOSP tree as `GoffyOS.apk`.
- Use `scripts/create_rom_release_signing_plan.py` to create a dry-run plan; the
  plan references `GOFFY_APK_KEYSTORE_PASS` and `GOFFY_APK_KEY_PASS` by name but
  never stores password values.
- Use `scripts/verify_rom_release_apk.py` after signing to record hash, size,
  and v2/v3 signature evidence before AOSP import planning.
- Keep `privileged_permission_allowlist` empty.
- Keep `CAMERA` and `RECORD_AUDIO` foreground and user-approved only.
- Keep `.MainActivity` exported with both `MAIN/LAUNCHER` and
  `MAIN/HOME/DEFAULT` intent filters so a future ROM can present GOFFY as the
  user-selectable home surface without granting privileged authority.
- Re-run the validator after any Android manifest permission change.

This is not a flashable image and does not modify the phone.
