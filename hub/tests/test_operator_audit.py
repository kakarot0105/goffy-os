from __future__ import annotations

import sqlite3
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

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

    snapshot = log.snapshot()

    assert snapshot.storage_kind == "memory"
    assert snapshot.integrity == "volatile"
    assert [event.sequence for event in snapshot.events] == [third.sequence, second.sequence]
    assert first not in snapshot.events


def test_operator_audit_rejects_unbounded_or_unsafe_fields() -> None:
    log = OperatorAuditLog(max_events=2)

    with pytest.raises(ValueError):
        log.record(
            source="pairing\nforged",
            action="bundle.created",
            outcome="succeeded",
            principal_kind="bootstrap",
        )


def test_persistent_operator_audit_survives_reopen_with_hash_chain(tmp_path: Path) -> None:
    database_path = tmp_path / "state" / "operator-audit.sqlite3"
    log = OperatorAuditLog(
        max_events=16,
        database_path=database_path,
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
        outcome="succeeded",
        principal_kind="paired",
    )
    reopened = OperatorAuditLog(max_events=16, database_path=database_path)
    snapshot = reopened.snapshot()

    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
    assert snapshot.storage_kind == "sqlite"
    assert snapshot.integrity == "verified"
    assert [event.sequence for event in snapshot.events] == [second.sequence, first.sequence]
    assert all(event.previous_hash is not None for event in snapshot.events)
    assert all(event.event_hash is not None for event in snapshot.events)


def test_persistent_operator_audit_reports_retention_gap(tmp_path: Path) -> None:
    database_path = tmp_path / "operator-audit.sqlite3"
    log = OperatorAuditLog(
        max_events=2,
        database_path=database_path,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )

    for index in range(3):
        log.record(
            source="mcp",
            action="http.post",
            outcome="succeeded",
            principal_kind="paired",
            detail_code=f"status:20{index}",
        )

    reopened = OperatorAuditLog(max_events=2, database_path=database_path)
    snapshot = reopened.snapshot()

    assert snapshot.integrity == "retention_gap"
    assert [event.sequence for event in snapshot.events] == [3, 2]


def test_persistent_operator_audit_prunes_when_retention_is_lowered(tmp_path: Path) -> None:
    database_path = tmp_path / "operator-audit.sqlite3"
    log = OperatorAuditLog(
        max_events=4,
        database_path=database_path,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )
    for index in range(4):
        log.record(
            source="mcp",
            action="http.post",
            outcome="succeeded",
            principal_kind="paired",
            detail_code=f"status:20{index}",
        )

    reopened = OperatorAuditLog(max_events=2, database_path=database_path)
    snapshot = reopened.snapshot()
    with sqlite3.connect(database_path) as connection:
        row_count = connection.execute("SELECT COUNT(*) FROM operator_audit_events").fetchone()[0]

    assert snapshot.integrity == "retention_gap"
    assert [event.sequence for event in snapshot.events] == [4, 3]
    assert row_count == 2


def test_persistent_operator_audit_verifies_before_startup_pruning(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operator-audit.sqlite3"
    log = OperatorAuditLog(
        max_events=4,
        database_path=database_path,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )
    for index in range(4):
        log.record(
            source="mcp",
            action="http.post",
            outcome="succeeded",
            principal_kind="paired",
            detail_code=f"status:20{index}",
        )

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE operator_audit_events SET action = ? WHERE sequence = 1",
            ("http.delete",),
        )

    reopened = OperatorAuditLog(max_events=2, database_path=database_path)
    snapshot = reopened.snapshot()
    with sqlite3.connect(database_path) as connection:
        row_count = connection.execute("SELECT COUNT(*) FROM operator_audit_events").fetchone()[0]

    assert snapshot.integrity == "tamper_detected"
    assert row_count == 4


def test_persistent_operator_audit_detects_tampering(tmp_path: Path) -> None:
    database_path = tmp_path / "operator-audit.sqlite3"
    log = OperatorAuditLog(
        max_events=16,
        database_path=database_path,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )
    log.record(
        source="pairing",
        action="bundle.created",
        outcome="succeeded",
        principal_kind="bootstrap",
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE operator_audit_events SET action = ? WHERE sequence = 1",
            ("bundle.forged",),
        )

    reopened = OperatorAuditLog(max_events=16, database_path=database_path)

    assert reopened.snapshot().integrity == "tamper_detected"


def test_persistent_operator_audit_detects_tail_truncation(tmp_path: Path) -> None:
    database_path = tmp_path / "operator-audit.sqlite3"
    log = OperatorAuditLog(
        max_events=16,
        database_path=database_path,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )
    log.record(
        source="pairing",
        action="bundle.created",
        outcome="succeeded",
        principal_kind="bootstrap",
    )
    log.record(
        source="mcp",
        action="http.post",
        outcome="succeeded",
        principal_kind="paired",
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM operator_audit_events WHERE sequence = 2")

    reopened = OperatorAuditLog(max_events=16, database_path=database_path)

    assert reopened.snapshot().integrity == "tamper_detected"


def test_persistent_operator_audit_detects_tail_truncation_with_rewritten_tip(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operator-audit.sqlite3"
    log = OperatorAuditLog(
        max_events=16,
        database_path=database_path,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )
    first = log.record(
        source="pairing",
        action="bundle.created",
        outcome="succeeded",
        principal_kind="bootstrap",
    )
    log.record(
        source="mcp",
        action="http.post",
        outcome="succeeded",
        principal_kind="paired",
    )

    with sqlite3.connect(database_path) as connection:
        connection.execute("DELETE FROM operator_audit_events WHERE sequence = 2")
        connection.execute(
            """
            UPDATE operator_audit_metadata
            SET value = ?
            WHERE key = 'chain_tip_sequence'
            """,
            (str(first.sequence),),
        )
        connection.execute(
            """
            UPDATE operator_audit_metadata
            SET value = ?
            WHERE key = 'chain_tip_hash'
            """,
            (first.event_hash,),
        )

    reopened = OperatorAuditLog(max_events=16, database_path=database_path)

    assert reopened.snapshot().integrity == "tamper_detected"


def test_persistent_operator_audit_assigns_sequences_from_database_tip(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operator-audit.sqlite3"
    first_writer = OperatorAuditLog(
        max_events=16,
        database_path=database_path,
        clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
    )
    overlapping_writer = OperatorAuditLog(
        max_events=16,
        database_path=database_path,
        clock=lambda: datetime(2026, 7, 14, 12, 1, tzinfo=UTC),
    )

    first = first_writer.record(
        source="pairing",
        action="bundle.created",
        outcome="succeeded",
        principal_kind="bootstrap",
    )
    second = overlapping_writer.record(
        source="mcp",
        action="http.post",
        outcome="succeeded",
        principal_kind="paired",
    )
    reopened = OperatorAuditLog(max_events=16, database_path=database_path)
    snapshot = reopened.snapshot()

    assert [event.sequence for event in snapshot.events] == [2, 1]
    assert second.sequence == 2
    assert second.previous_hash == first.event_hash
    assert snapshot.integrity == "verified"


def test_persistent_operator_audit_serializes_overlapping_writers(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "operator-audit.sqlite3"
    writer_count = 4
    events_per_writer = 5
    logs = tuple(
        OperatorAuditLog(
            max_events=64,
            database_path=database_path,
            clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=UTC),
        )
        for _ in range(writer_count)
    )
    start = threading.Barrier(writer_count)

    def write_events(writer_index: int) -> tuple[int, ...]:
        start.wait(timeout=5)
        sequences: list[int] = []
        for event_index in range(events_per_writer):
            event = logs[writer_index].record(
                source="mcp",
                action="http.post",
                outcome="succeeded",
                principal_kind="paired",
                detail_code=f"writer:{writer_index}:event:{event_index}",
            )
            sequences.append(event.sequence)
        return tuple(sequences)

    with ThreadPoolExecutor(max_workers=writer_count) as executor:
        written_sequences = tuple(
            sequence
            for sequences in executor.map(write_events, range(writer_count))
            for sequence in sequences
        )

    reopened = OperatorAuditLog(max_events=64, database_path=database_path)
    snapshot = reopened.snapshot()
    newest_first_sequences = [event.sequence for event in snapshot.events]
    oldest_first_events = tuple(reversed(snapshot.events))

    assert sorted(written_sequences) == list(range(1, writer_count * events_per_writer + 1))
    assert newest_first_sequences == list(range(writer_count * events_per_writer, 0, -1))
    assert snapshot.integrity == "verified"
    assert oldest_first_events[0].previous_hash is not None
    for previous, current in zip(
        oldest_first_events[:-1],
        oldest_first_events[1:],
        strict=True,
    ):
        assert current.previous_hash == previous.event_hash
