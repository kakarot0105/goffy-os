# Phone Tools

Android capability implementations expose narrow, typed local tools without a
generic Android-command interface.

The fixed local registry currently exposes:

- `phone.battery.status`, which reads `BatteryManager` once and validates the percentage.
- `phone.device.info`, which returns manufacturer, model, Android release, and SDK level.

Both tools require no Android permission, run off the UI dispatcher with a
bounded timeout, and emit a separate verification event. They do not register a
receiver, poll, run in the background, or open a network connection. Device info
never reads serial, IMEI, Android ID, advertising ID, MAC/IP, fingerprint, SKU,
hostname, radio, or account data.
