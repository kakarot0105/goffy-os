# ADR 0017: Foreground QR pairing scanner

- Status: Accepted
- Date: 2026-07-14

## Context

GOFFY Hub can now emit a versioned `goffy.pairing.bundle.v1` payload that is
safe to transfer as a QR code during USB-loopback onboarding. Android still
required manual JSON entry, which is too error-prone for phone-first setup.

Adding camera access is a security decision. GOFFY must not create background
camera behavior, generic camera capture, or an automatic pairing shortcut that
bypasses the existing typed bundle parser.

## Decision

- Add the Android `CAMERA` permission and declare camera hardware optional.
- Use CameraX preview and image analysis only inside a visible pairing scanner.
- Use ML Kit's bundled barcode model so first-use scanning does not depend on a
  later network model download.
- Configure the decoder for QR codes only.
- Use a latest-frame-only analyzer at 1280x720 for old-phone responsiveness.
- Release analysis and unbind CameraX when the scanner closes, the Activity
  stops, or one payload is captured.
- Treat scanned text as input only: fill the existing bounded pairing-bundle
  field and require the user to tap `Pair phone` before redemption.
- Keep trusted LAN, certificate pin onboarding, and token rotation out of scope.

## Consequences

The user can complete USB-loopback pairing without a cloud clipboard or manual
copying. The scanner increases APK size because the ML Kit model is bundled, but
the model and camera pipeline load only while the visible scanner panel is active.

The existing parser remains the authorization boundary. Non-GOFFY QR contents,
raw challenges, endpoint substitutions, expired challenges, and extra fields must
continue to fail before any credential is issued.

## Rejected alternatives

- Use the Google code scanner API: it is permissionless, but GOFFY needs a visible
  custom pairing panel and explicit lifecycle/audit language for this OS shell.
- Use the unbundled Play Services ML Kit dependency: it reduces APK size but can
  fail the first pairing attempt until a model download completes.
- Automatically redeem immediately after scan: that would merge camera capture
  with credential issuance and remove a visible user checkpoint.
