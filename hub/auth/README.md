# Hub Authentication

The shared principal and scope boundary lives in `hub/src/goffy_hub/auth.py`.
Explicitly configured paired mode uses digest-only SQLite credentials, one-time
loopback challenges, stable credential IDs, and immediate WebSocket/MCP
revocation. The bootstrap token becomes pairing-admin-only in this mode.

Android guided pairing, secure mobile credential storage, token rotation, trusted
LAN onboarding, and direct Hub/MCP operator audit remain future work. See
`docs/adr/0013-paired-device-credentials.md` and `docs/setup/hub.md`.
