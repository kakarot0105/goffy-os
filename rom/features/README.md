# GOFFY ROM Feature Payload

This directory records the features GOFFY intends to include in ROM-0 once the
Moto G feasibility gates are satisfied.

The payload is intentionally conservative:

- GOFFY remains a non-privileged system app.
- GOFFY remains user-selectable as HOME.
- Camera and microphone remain foreground and user-approved only.
- App-private memory forget tools are included only as exact approval-gated
  GOFFY SQLite mutations.
- Local models remain disabled by default and non-authoritative until accepted.
- Unlock, flash, wipe, bootloader, root, platform-signing, and unrestricted
  shell behavior remain blocked.

Validate the payload with:

```bash
.venv/bin/python scripts/validate_rom_feature_payload.py
```

This descriptor is not a flashable image and does not modify the phone.
