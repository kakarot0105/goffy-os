from __future__ import annotations

from datetime import UTC, datetime

import pytest

from goffy_hub.operator_audit import OperatorAuditLog


def test_operator_audit_log_is_bounded_and_newest_first() -> None:
    log = OperatorAuditLog(
        max_events=2,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )

    first = log.record(
        source="pairing",
        action="bundle.created",
        outcome="succeeded",
        principal_kind="bootstrap",
    )
    second = log.record(
        source="mcp",
        action="http.post",
        outcome="rejected",
        principal_kind="none",
        detail_code="status:401",
    )
    third = log.record(
        source="websocket",
        action="connect",
        outcome="succeeded",
        principal_kind="paired",
    )

    assert [event.sequence for event in log.snapshot()] == [third.sequence, second.sequence]
    assert first not in log.snapshot()


def test_operator_audit_rejects_unbounded_or_unsafe_fields() -> None:
    log = OperatorAuditLog(max_events=2)

    with pytest.raises(ValueError):
        log.record(
            source="pairing\nforged",
            action="bundle.created",
            outcome="succeeded",
            principal_kind="bootstrap",
        )
