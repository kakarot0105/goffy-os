from __future__ import annotations

import re
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

MAX_AUDIT_TEXT_LENGTH = 80
AUDIT_TOKEN_PATTERN = re.compile(r"^[a-z0-9_.:-]{1,80}$")

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class OperatorAuditEvent:
    sequence: int
    recorded_at: datetime
    source: str
    action: str
    outcome: str
    principal_kind: str
    credential_id: UUID | None = None
    detail_code: str | None = None


class OperatorAuditLog:
    """Bounded in-memory audit trail for non-secret Hub operator events."""

    def __init__(
        self,
        *,
        max_events: int,
        clock: Clock | None = None,
    ) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self._max_events = max_events
        self._clock = clock or (lambda: datetime.now(UTC))
        self._events: deque[OperatorAuditEvent] = deque()
        self._lock = threading.Lock()
        self._next_sequence = 1

    def record(
        self,
        *,
        source: str,
        action: str,
        outcome: str,
        principal_kind: str,
        credential_id: UUID | None = None,
        detail_code: str | None = None,
    ) -> OperatorAuditEvent:
        with self._lock:
            event = OperatorAuditEvent(
                sequence=self._next_sequence,
                recorded_at=_as_utc(self._clock()),
                source=_audit_token(source),
                action=_audit_token(action),
                outcome=_audit_token(outcome),
                principal_kind=_audit_token(principal_kind),
                credential_id=credential_id,
                detail_code=_audit_token(detail_code) if detail_code is not None else None,
            )
            self._events.append(event)
            self._next_sequence += 1
            while len(self._events) > self._max_events:
                self._events.popleft()
        return event

    def snapshot(self, *, limit: int | None = None) -> tuple[OperatorAuditEvent, ...]:
        with self._lock:
            events = tuple(reversed(self._events))
        if limit is None:
            return events
        if limit <= 0:
            raise ValueError("limit must be positive")
        return events[:limit]


def _audit_token(value: str) -> str:
    normalized = value.strip().lower()
    if AUDIT_TOKEN_PATTERN.fullmatch(normalized) is None:
        raise ValueError("audit field is not a safe bounded token")
    return normalized[:MAX_AUDIT_TEXT_LENGTH]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
