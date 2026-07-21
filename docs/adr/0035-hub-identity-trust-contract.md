# ADR 0035: Hub identity trust contract gate

## Status

Accepted

## Context

GOFFY needs future trusted LAN pairing, but the current pairing slice is still
USB-loopback-only. The existing Hub identity fingerprint gives Android stable
public provenance for the Mac Hub, but it is not a certificate pin, public-key
proof, or TLS trust grant.

A reuse-first scan found mature Android certificate-pinning options, including
OkHttp `CertificatePinner` and TrustKit Android. Those are useful for the later
trusted transport slice, but importing them now would add dependency and
operational complexity without a configured Hub certificate/public key to pin.
Android platform security guidance also makes the trust boundary explicit:
TLS proves possession of a certificate private key only when the client trusts
the certificate chain or configured trust material.

## Decision

- Define `goffy.pairing.bundle.v3` for pairing bundles that include the trust
  contract.
- Add `trustContract` to public Hub identity payloads returned by
  `/admin/v1/hub-identity`, `/admin/v1/pairing/bundles`, and
  `/pairing/v1/redeem`.
- Define the contract as `goffy.hub.trust.v1` with:
  - `proofKind=loopback_fingerprint_only`
  - `transportScope=usb_loopback_only`
  - `publicKeyPinStatus=absent`
  - `certificatePinStatus=absent`
  - `trustedLanSupported=false`
- Require Android pairing redemption to reject bundles or redemption responses
  that omit the contract or claim public-key, certificate, or trusted LAN support.
- Keep encrypted Android paired credentials backward-compatible with the current
  stored Hub identity pin and continue rejecting any stored record that claims
  `trustedLanSupported=true`.

## Consequences

The Hub and Android now expose a machine-validated readiness gate for certificate
or public-key onboarding without pretending trusted LAN is complete. Future work
can upgrade the contract deliberately, with a new ADR, transport proof, Android
pinning implementation, and migration tests.

Existing Android paired credentials do not need to be deleted solely because this
contract was added. New QR pairing payloads and redemption responses must use
`goffy.pairing.bundle.v3` and include the contract.

This does not implement TLS certificate generation, public-key pin transfer,
OkHttp certificate pinning, TrustKit, LAN pairing, or remote Hub identity proof.

## Rejected Alternatives

- Import TrustKit Android now. Rejected because this slice has no certificate or
  public key to pin, and the extra dependency would not improve USB-loopback
  security.
- Wire OkHttp `CertificatePinner` now. Rejected because GOFFY does not yet have a
  trusted LAN hostname or certificate lifecycle.
- Treat the existing fingerprint as LAN trust. Rejected because it is a
  domain-separated local identity fingerprint, not transport proof.
- Bump the Android encrypted credential schema to store the full contract.
  Rejected for this slice because `trustedLanSupported=false` already preserves
  the local-authority boundary and avoiding forced re-pairing is safer.

## References

- Android Developers: Security with network protocols
  https://developer.android.com/privacy-and-security/security-ssl
- OkHttp `CertificatePinner`
  https://square.github.io/okhttp/4.x/okhttp/okhttp3/-certificate-pinner/
- TrustKit Android
  https://github.com/datatheorem/trustkit-android
