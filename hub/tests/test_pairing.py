from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

import goffy_hub.pairing as pairing_module
from goffy_hub.credentials import CredentialStore
from goffy_hub.pairing import (
    InvalidPairingChallengeError,
    PairingAttemptLimitError,
    PairingBusyError,
    PairingService,
)

PAIRING_TOKEN = "pairing-token-" + "p" * 32  # noqa: S105
ACCESS_TOKEN = "credential-token-" + "c" * 32  # noqa: S105
CHALLENGE_ID = UUID("30303030-3030-4030-8030-303030303030")
CREDENTIAL_ID = UUID("40404040-4040-4040-8040-404040404040")


@dataclass
class FakeClock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


def build_service(tmp_path: Path, clock: FakeClock) -> PairingService:
    store = CredentialStore(
        tmp_path / "credentials.sqlite3",
        clock=clock,
        token_factory=lambda: ACCESS_TOKEN,
        id_factory=lambda: CREDENTIAL_ID,
    )
    return PairingService(
        store,
        clock=clock,
        token_factory=lambda: PAIRING_TOKEN,
        id_factory=lambda: CHALLENGE_ID,
    )


@pytest.mark.asyncio
async def test_pairing_challenge_succeeds_before_expiry_and_is_single_use(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    service = build_service(tmp_path, clock)
    challenge = await service.begin()
    assert challenge.pairing_token not in repr(challenge)
    clock.now += timedelta(seconds=119)

    issued = await service.complete(
        challenge.challenge_id,
        challenge.pairing_token,
        "setup-observation-1",
        "Moto G",
    )

    assert issued.access_token == ACCESS_TOKEN
    assert issued.credential.credential_id == CREDENTIAL_ID
    with pytest.raises(InvalidPairingChallengeError):
        await service.complete(
            challenge.challenge_id,
            challenge.pairing_token,
            "setup-observation-1",
            "Moto G",
        )
    assert len(await service.list_credentials()) == 1


@pytest.mark.asyncio
async def test_pairing_challenge_expires_at_exact_ttl_boundary(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    service = build_service(tmp_path, clock)
    challenge = await service.begin()
    clock.now += timedelta(seconds=120)

    with pytest.raises(InvalidPairingChallengeError):
        await service.complete(
            challenge.challenge_id,
            challenge.pairing_token,
            "setup-observation-1",
            "Moto G",
        )

    assert await service.list_credentials() == ()


@pytest.mark.asyncio
async def test_fifth_bad_pairing_attempt_invalidates_challenge(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    service = build_service(tmp_path, clock)
    challenge = await service.begin()

    for attempt in range(pairing_module.MAX_CHALLENGE_FAILURES - 1):
        with pytest.raises(InvalidPairingChallengeError):
            await service.complete(
                challenge.challenge_id,
                f"wrong-token-{attempt}",
                "setup-observation-1",
                "Moto G",
            )

    with pytest.raises(PairingAttemptLimitError):
        await service.complete(
            challenge.challenge_id,
            "last-wrong-token",
            "setup-observation-1",
            "Moto G",
        )
    with pytest.raises(InvalidPairingChallengeError):
        await service.complete(
            challenge.challenge_id,
            challenge.pairing_token,
            "setup-observation-1",
            "Moto G",
        )
    assert await service.list_credentials() == ()


@pytest.mark.asyncio
async def test_pending_pairing_challenges_are_bounded(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    challenge_ids = iter(
        UUID(int=value + 1) for value in range(pairing_module.MAX_PENDING_CHALLENGES)
    )
    pairing_tokens = iter(
        f"pairing-token-{value}-" + "p" * 32
        for value in range(pairing_module.MAX_PENDING_CHALLENGES + 1)
    )
    store = CredentialStore(tmp_path / "credentials.sqlite3")
    service = PairingService(
        store,
        clock=clock,
        token_factory=lambda: next(pairing_tokens),
        id_factory=lambda: next(challenge_ids),
    )
    for _index in range(pairing_module.MAX_PENDING_CHALLENGES):
        await service.begin()

    with pytest.raises(PairingBusyError, match="limit"):
        await service.begin()


@pytest.mark.asyncio
async def test_concurrent_redemption_mints_exactly_one_credential(tmp_path: Path) -> None:
    clock = FakeClock(datetime(2026, 7, 13, 12, 0, tzinfo=UTC))
    service = build_service(tmp_path, clock)
    challenge = await service.begin()
    start = asyncio.Event()

    async def redeem() -> str:
        await start.wait()
        try:
            await service.complete(
                challenge.challenge_id,
                challenge.pairing_token,
                "setup-observation-1",
                "Moto G",
            )
        except InvalidPairingChallengeError:
            return "rejected"
        return "issued"

    attempts = [asyncio.create_task(redeem()), asyncio.create_task(redeem())]
    start.set()
    outcomes = await asyncio.gather(*attempts)

    assert sorted(outcomes) == ["issued", "rejected"]
    assert len(await service.list_credentials()) == 1
