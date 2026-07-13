from __future__ import annotations

from hmac import compare_digest

from goffy_hub.settings import HubSettings

BEARER_PREFIX = "Bearer "


def is_authorized(authorization: str | None, settings: HubSettings) -> bool:
    if settings.auth_token is None or authorization is None:
        return False
    if not authorization.startswith(BEARER_PREFIX):
        return False

    presented = authorization.removeprefix(BEARER_PREFIX)
    expected = settings.auth_token.get_secret_value()
    return bool(presented) and compare_digest(presented, expected)
