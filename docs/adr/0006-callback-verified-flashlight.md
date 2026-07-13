# ADR 0006: Callback-verified Android flashlight

- Status: Accepted
- Date: 2026-07-13

## Context

GOFFY needs a low-latency local flashlight action that is safe on a 4 GB phone.
Opening a camera stream, retaining camera resources, or running a background
service would add unnecessary privacy, lifecycle, and battery risk. Android's
CameraManager can change torch state without opening a camera and reports state
through a callback.

## Decision

- Route only anchored on/off commands to
  `PHONE / phone.flashlight.set / CONFIRM`.
- Bind approval to the task, tool, exact Boolean state, and expiry; consume it once.
- Request no `CAMERA` permission and open no camera stream. Declare flash hardware
  optional so devices without it can still install GOFFY and fail the tool visibly.
- Select candidates with back-facing flash capability, prefer a logical camera,
  then use stable camera-ID ordering. Do not expose the camera ID in tool output.
- Register a short-lived `TorchCallback`, observe the initial state, avoid a set call
  if already correct, otherwise call `setTorchMode`, and wait for the matching state.
- Always unregister on success, failure, timeout, or cancellation.
- Bound callback verification to three seconds; timeout cancels the source and
  triggers the same cleanup path.
- Return only `enabled` and `stateChanged`; keep proof in the separate verification
  event. `VERIFIED` means the callback observed the approved state at completion.
- Run no polling, service, receiver, camera preview, or retained background job.

## Consequences

The tool has no idle CPU or network cost and no image-capture authority. Verification
is real but point-in-time: torch ownership is not exclusive, and Android may turn it
off if another app uses camera resources or the GOFFY process exits. Multi-camera and
Moto OEM behavior still require physical testing.

## References

- [CameraManager torch API](https://developer.android.com/reference/android/hardware/camera2/CameraManager#setTorchMode(java.lang.String,%20boolean))
- [TorchCallback](https://developer.android.com/reference/android/hardware/camera2/CameraManager.TorchCallback)
- [Camera characteristics](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics)
- [Optional hardware features](https://developer.android.com/guide/topics/manifest/uses-feature-element)
