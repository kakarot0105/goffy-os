# ADR 0014: Android Keystore paired credential

- Status: Accepted
- Date: 2026-07-13

## Context

The Hub returns each paired bearer exactly once. Android therefore needs durable
local authority without putting the bearer in Compose saved state, SQLite audit,
backup, logs, URLs, or plaintext app storage. The phone baseline is API 26 and the
flow must remain lightweight and foreground-only.

## Decision

- Redeem the complete typed challenge JSON through a dedicated HTTP client at
  exact `/pairing/v1/redeem`, derived from the validated `/ws/v1` endpoint.
  Redemption is loopback-only and never retried because the challenge is single-use.
- Keep challenge input in non-saveable, password-masked Compose memory, cap request
  and response JSON at 2 KiB, reject unknown fields, and expose only generic errors.
- Cancel enrollment when the Activity stops, join the canceled job, and remove any
  partial local record. Do not use a service, worker, or background retry.
- Store one versioned credential record containing the exact endpoint,
  `credentialId`, descriptive phone ID, bearer, and creation time. The endpoint is
  part of the authenticated ciphertext and cannot be edited independently.
- Encrypt with a non-exportable Android Keystore AES-256 key restricted to GCM and
  no padding. Use a provider-generated 12-byte IV, a 128-bit tag, fixed versioned
  associated data, and a small magic/version prefix.
- Atomically write the bounded ciphertext under `noBackupFilesDir`. Do not activate
  the link until immediate read-back, decryption, strict decoding, and exact
  authority comparison succeed.
- Restore off the UI thread without probing the network or resuming work. Reuse the
  stored descriptive phone ID after restart; Hub `credentialId` remains the actual
  principal.
- Treat a missing record as unpaired. Treat malformed, oversized, unsupported, or
  undecryptable state as degraded: delete the ciphertext and key, disable Mac
  authority, and require a new challenge.
- Define the original `Forget local link` action as phone-local deletion. Cancel
  and join any enrollment first, delete ciphertext and key, verify local absence,
  and state clearly that bootstrap-admin revocation is still required on the Mac.
  ADR 0015 supersedes this limitation with paired self-revocation.
- Keep manual bearer entry available only in debug builds and memory-only.

## Consequences

Startup adds one bounded local file read and Keystore decrypt, with no polling,
WorkManager, model load, or network request. Pairing adds one foreground HTTP call
and one tiny atomic write. This remains compatible with GOFFY LITE and API 26.

The decrypted bearer remains in the active ViewModel's process memory because the
current WebSocket gateway requires a `HubConfig`; Keystore protects data at rest,
not a rooted or compromised process. Physical Moto G Keystore behavior, guided QR
transfer, trusted Hub certificate/public-key onboarding, and automatic token
rotation schedules remain open. Hub-side paired token rotation is handled by ADR
0018; Android manual rotation UX is handled by ADR 0019.

## Rejected alternatives

- Plain `SharedPreferences` or SQLite: this would persist recoverable authority.
- AndroidX encrypted preferences: direct Keystore AES-GCM keeps the small record and
  API-26 behavior explicit without another runtime dependency.
- Add pairing to `/ws/v1`: ADR 0013 intentionally keeps enrollment separate from
  tool execution.
- Add paired self-revocation in this increment: it required a new Hub authority and
  offline reconciliation contract, so it is recorded separately in ADR 0015.
- Enable LAN pairing with the current challenge: the phone cannot authenticate Hub
  identity until certificate or public-key pin onboarding exists.

## References

- [Android Keystore system](https://developer.android.com/privacy-and-security/keystore)
- [Android cryptography guidance](https://developer.android.com/privacy-and-security/cryptography)
- [Android Auto Backup controls](https://developer.android.com/identity/data/autobackup)
