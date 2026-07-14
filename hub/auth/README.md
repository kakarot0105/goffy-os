# Hub Authentication

The shared principal and scope boundary lives in `hub/src/goffy_hub/auth.py`.
Explicitly configured paired mode uses digest-only SQLite credentials, one-time
loopback challenges, stable credential IDs, and immediate WebSocket/MCP
revocation. The bootstrap token becomes pairing-admin-only in this mode.

Android secure mobile credential storage and a USB-loopback pairing bundle exist
for the current slice. Camera QR scanning, token rotation, trusted LAN onboarding,
and direct Hub/MCP operator audit remain future work. See
`docs/adr/0013-paired-device-credentials.md`, `docs/adr/0014-android-keystore-paired-credential.md`,
`docs/adr/0015-paired-self-revocation.md`, and `docs/setup/hub.md`.
