# Phone Tools

Android capability implementations expose narrow, typed local tools without a
generic Android-command interface.

The fixed local registry currently exposes:

- `phone.battery.status`, which reads `BatteryManager` once and validates the percentage.
- `phone.device.info`, which returns manufacturer, model, Android release, and SDK level.
- `phone.flashlight.set`, which requires approval and callback-verifies a back-facing torch.
- `phone.note.create`, which requires approval and re-reads app-private SQLite state.
- `phone.timer.create`, which requires approval and dispatches only to an allowlisted system Clock.

The immutable registry owns each MCP-shaped input/output schema, permission, target,
and bounded timeout. The router reads PHONE permissions from it, while the gateway
independently matches the compiled descriptor and typed arguments before source
access. Discovery metadata never authorizes execution; CONFIRM tools retain their
exact-task, exact-argument, expiring, single-use approval boundary.

Battery and device info require no Android permission, run off the UI dispatcher,
and emit a separate verification event. None of the tools polls, runs in the
background, or opens a network connection. Device info never reads serial, IMEI,
Android ID, advertising ID, MAC/IP, fingerprint, SKU, hostname, radio, or account
data. CONFIRM PHONE tools remain local-only and are not exposed by the Hub MCP endpoint.
