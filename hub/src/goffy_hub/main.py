from __future__ import annotations

import uvicorn

from goffy_hub.app import create_app
from goffy_hub.settings import HubSettings


def run() -> None:
    settings = HubSettings.from_environment()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        ws_max_size=settings.max_message_bytes,
        ws_max_queue=8,
        ssl_certfile=str(settings.tls_cert_file) if settings.tls_cert_file else None,
        ssl_keyfile=str(settings.tls_key_file) if settings.tls_key_file else None,
    )


if __name__ == "__main__":
    run()
