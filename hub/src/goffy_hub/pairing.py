from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import UUID, uuid4

from goffy_hub.credentials import CredentialStore, IssuedCredential, PairedCredential

CHALLENGE_DIGEST_DOMAIN = b"goffy-pairing-challenge-v1\x00"
PAIRING_CHALLENGE_TTL_SECONDS = 120
MAX_PENDING_CHALLENGES = 3
MAX_CHALLENGE_FAILURES = 5
MIN_GENERATED_PAIRING_TOKEN_LENGTH = 32

Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]
IdFactory = Callable[[], UUID]


class PairingError(Exception):
    """Base class for pairing failures safe to map to generic API errors."""


class PairingBusyError(PairingError):
    pass


class InvalidPairingChallengeError(PairingError):
    pass


class PairingAttemptLimitError(PairingError):
    pass


@dataclass(frozen=True, slots=True)
class PairingChallenge:
    challenge_id: UUID
    pairing_token: str = field(repr=False)
    expires_at: datetime


@dataclass(slots=True)
class _PendingChallenge:
    token_digest: bytes
    expires_at: datetime
    failed_attempts: int = 0


class PairingService:
    def __init__(
        self,
        credential_store: CredentialStore,
        *,
        clock: Clock | None = None,
        token_factory: TokenFactory | None = None,
        id_factory: IdFactory | None = None,
        challenge_ttl_seconds: int = PAIRING_CHALLENGE_TTL_SECONDS,
    ) -> None:
        if challenge_ttl_seconds <= 0:
            raise ValueError("pairing challenge TTL must be positive")
        self._credential_store = credential_store
        self._clock = clock or _utc_now
        self._token_factory = token_factory or (lambda: token_urlsafe(32))
        self._id_factory = id_factory or uuid4
        self._challenge_ttl = timedelta(seconds=challenge_ttl_seconds)
        self._pending: dict[UUID, _PendingChallenge] = {}
        self._lock = asyncio.Lock()

    async def begin(self) -> PairingChallenge:
        pairing_token = self._token_factory()
        if len(pairing_token) < MIN_GENERATED_PAIRING_TOKEN_LENGTH:
            raise PairingError("generated pairing token is too short")

        now = _as_utc(self._clock())
        async with self._lock:
            self._prune_expired(now)
            if len(self._pending) >= MAX_PENDING_CHALLENGES:
                raise PairingBusyError("pending pairing challenge limit reached")
            challenge_id = self._id_factory()
            expires_at = now + self._challenge_ttl
            self._pending[challenge_id] = _PendingChallenge(
                token_digest=_challenge_digest(pairing_token),
                expires_at=expires_at,
            )
        return PairingChallenge(
            challenge_id=challenge_id,
            pairing_token=pairing_token,
            expires_at=expires_at,
        )

    async def complete(
        self,
        challenge_id: UUID,
        pairing_token: str,
        device_id: str,
        display_name: str,
    ) -> IssuedCredential:
        now = _as_utc(self._clock())
        async with self._lock:
            pending = self._pending.get(challenge_id)
            if pending is None or now >= pending.expires_at:
                self._pending.pop(challenge_id, None)
                raise InvalidPairingChallengeError("pairing challenge is invalid")

            presented_digest = _challenge_digest(pairing_token)
            if not compare_digest(presented_digest, pending.token_digest):
                pending.failed_attempts += 1
                if pending.failed_attempts >= MAX_CHALLENGE_FAILURES:
                    self._pending.pop(challenge_id, None)
                    raise PairingAttemptLimitError("pairing attempt limit reached")
                raise InvalidPairingChallengeError("pairing challenge is invalid")

            self._pending.pop(challenge_id)

        return await asyncio.to_thread(self._credential_store.issue, device_id, display_name)

    async def list_credentials(self) -> tuple[PairedCredential, ...]:
        return await asyncio.to_thread(self._credential_store.list_credentials)

    async def check_store(self) -> None:
        await asyncio.to_thread(self._credential_store.active_count)

    async def revoke(self, credential_id: UUID) -> PairedCredential | None:
        return await asyncio.to_thread(self._credential_store.revoke, credential_id)

    def _prune_expired(self, now: datetime) -> None:
        for challenge_id, pending in tuple(self._pending.items()):
            if now >= pending.expires_at:
                self._pending.pop(challenge_id, None)


def _challenge_digest(token: str) -> bytes:
    return hashlib.sha256(CHALLENGE_DIGEST_DOMAIN + token.encode("utf-8")).digest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise PairingError("pairing timestamps must be timezone-aware")
    return value.astimezone(UTC)
