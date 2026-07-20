from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import threading
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID

MAX_AUDIT_TEXT_LENGTH = 80
AUDIT_TOKEN_PATTERN = re.compile(r"^[a-z0-9_.:-]{1,80}$")
AUDIT_HASH_DOMAIN = b"goffy-operator-audit-v1\x00"
GENESIS_AUDIT_HASH = b"\x00" * 32
CURRENT_AUDIT_SCHEMA_VERSION = 2
CHAIN_TIP_SEQUENCE_KEY = "chain_tip_sequence"
CHAIN_TIP_HASH_KEY = "chain_tip_hash"

Clock = Callable[[], datetime]


class OperatorAuditStoreError(Exception):
    """Base class for fail-closed operator-audit storage failures."""


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
    previous_hash: str | None = None
    event_hash: str | None = None


@dataclass(frozen=True, slots=True)
class OperatorAuditSnapshot:
    events: tuple[OperatorAuditEvent, ...]
    storage_kind: str
    integrity: str


@dataclass(frozen=True, slots=True)
class _StoredAuditRow:
    event: OperatorAuditEvent
    previous_hash: bytes
    event_hash: bytes


@dataclass(frozen=True, slots=True)
class _AuditChainTip:
    sequence: int
    event_hash: bytes


class OperatorAuditLog:
    """Bounded audit trail for non-secret Hub operator events."""

    def __init__(
        self,
        *,
        max_events: int,
        clock: Clock | None = None,
        database_path: Path | None = None,
    ) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self._max_events = max_events
        self._clock = clock or (lambda: datetime.now(UTC))
        self._database_path = database_path.resolve(strict=False) if database_path else None
        self._events: deque[OperatorAuditEvent] = deque()
        self._lock = threading.Lock()
        self._next_sequence = 1
        self._last_hash = GENESIS_AUDIT_HASH
        self._integrity = "verified"

        if self._database_path is not None:
            if not self._database_path.is_absolute():
                raise OperatorAuditStoreError("operator audit database path must be absolute")
            self._prepare_database_path()
            self._initialize_schema()
            self._load_persistent_events()

    @property
    def storage_kind(self) -> str:
        return "sqlite" if self._database_path is not None else "memory"

    @property
    def integrity(self) -> str:
        return self._integrity if self._database_path is not None else "volatile"

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
            recorded_at = _as_utc(self._clock())
            base_event = OperatorAuditEvent(
                sequence=self._next_sequence,
                recorded_at=recorded_at,
                source=_audit_token(source),
                action=_audit_token(action),
                outcome=_audit_token(outcome),
                principal_kind=_audit_token(principal_kind),
                credential_id=credential_id,
                detail_code=_audit_token(detail_code) if detail_code is not None else None,
            )
            event = (
                self._persist_event(base_event) if self._database_path is not None else base_event
            )
            self._events.append(event)
            self._next_sequence = event.sequence + 1
            while len(self._events) > self._max_events:
                self._events.popleft()
        return event

    def snapshot(self, *, limit: int | None = None) -> OperatorAuditSnapshot:
        with self._lock:
            events = tuple(reversed(self._events))
            storage_kind = self.storage_kind
            integrity = self.integrity
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be positive")
            events = events[:limit]
        return OperatorAuditSnapshot(
            events=events,
            storage_kind=storage_kind,
            integrity=integrity,
        )

    def check_store(self) -> None:
        """Verify persistent audit integrity and write availability without appending."""
        if self._database_path is None:
            return
        with self._lock:
            try:
                with self._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    stored_rows = self._fetch_stored_rows(connection)
                    chain_tip = self._read_chain_tip(connection)
                    integrity = _verify_stored_rows(stored_rows, chain_tip)
            except ValueError as error:
                raise OperatorAuditStoreError(
                    "operator audit database integrity check failed"
                ) from error
            self._integrity = integrity
            if integrity == "tamper_detected":
                raise OperatorAuditStoreError("operator audit database integrity check failed")

    def _persist_event(self, event: OperatorAuditEvent) -> OperatorAuditEvent:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stored_rows = self._fetch_stored_rows(connection)
            chain_tip = self._read_chain_tip(connection)
            integrity = _verify_stored_rows(stored_rows, chain_tip)
            if integrity == "tamper_detected":
                self._integrity = integrity
                raise OperatorAuditStoreError("operator audit database integrity check failed")

            last_row = stored_rows[-1] if stored_rows else None
            previous_hash = last_row.event_hash if last_row is not None else GENESIS_AUDIT_HASH
            sequence = last_row.event.sequence + 1 if last_row is not None else 1
            sequence_event = OperatorAuditEvent(
                sequence=sequence,
                recorded_at=event.recorded_at,
                source=event.source,
                action=event.action,
                outcome=event.outcome,
                principal_kind=event.principal_kind,
                credential_id=event.credential_id,
                detail_code=event.detail_code,
            )
            event_hash = _audit_event_hash(sequence_event, previous_hash)
            persistent_event = OperatorAuditEvent(
                sequence=sequence_event.sequence,
                recorded_at=sequence_event.recorded_at,
                source=sequence_event.source,
                action=sequence_event.action,
                outcome=sequence_event.outcome,
                principal_kind=sequence_event.principal_kind,
                credential_id=sequence_event.credential_id,
                detail_code=sequence_event.detail_code,
                previous_hash=previous_hash.hex(),
                event_hash=event_hash.hex(),
            )
            connection.execute(
                """
                INSERT INTO operator_audit_events (
                    sequence, recorded_at, source, action, outcome, principal_kind,
                    credential_id, detail_code, previous_hash, event_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persistent_event.sequence,
                    _serialize_datetime(persistent_event.recorded_at),
                    persistent_event.source,
                    persistent_event.action,
                    persistent_event.outcome,
                    persistent_event.principal_kind,
                    str(persistent_event.credential_id)
                    if persistent_event.credential_id is not None
                    else None,
                    persistent_event.detail_code,
                    previous_hash,
                    event_hash,
                ),
            )
            self._write_chain_tip(
                connection,
                _AuditChainTip(sequence=persistent_event.sequence, event_hash=event_hash),
            )
            self._prune_oldest(connection)
            stored_rows = self._fetch_stored_rows(connection)
            chain_tip = self._read_chain_tip(connection)
            self._integrity = _verify_stored_rows(stored_rows, chain_tip)
        self._last_hash = event_hash
        return persistent_event

    def _prepare_database_path(self) -> None:
        path = self._require_database_path()
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise OperatorAuditStoreError("operator audit database path must be a regular file")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix" and stat.S_IMODE(path.parent.stat().st_mode) & (
            stat.S_IWGRP | stat.S_IWOTH
        ):
            raise OperatorAuditStoreError(
                "operator audit database parent must not be group/world writable"
            )

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            descriptor = None
        except OSError as error:
            raise OperatorAuditStoreError(
                "operator audit database could not be created safely"
            ) from error
        if descriptor is not None:
            os.close(descriptor)

        if path.is_symlink() or not path.is_file():
            raise OperatorAuditStoreError("operator audit database path must be a regular file")
        if os.name == "posix":
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def _initialize_schema(self) -> None:
        try:
            with self._connect() as connection:
                schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
                if schema_version not in {0, 1, CURRENT_AUDIT_SCHEMA_VERSION}:
                    raise OperatorAuditStoreError("operator audit database schema is unsupported")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operator_audit_events (
                        sequence INTEGER PRIMARY KEY CHECK(sequence > 0),
                        recorded_at TEXT NOT NULL,
                        source TEXT NOT NULL,
                        action TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        principal_kind TEXT NOT NULL,
                        credential_id TEXT,
                        detail_code TEXT,
                        previous_hash BLOB NOT NULL CHECK(length(previous_hash) = 32),
                        event_hash BLOB NOT NULL CHECK(length(event_hash) = 32)
                    ) STRICT
                    """
                )
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(operator_audit_events)")
                }
                if columns != {
                    "sequence",
                    "recorded_at",
                    "source",
                    "action",
                    "outcome",
                    "principal_kind",
                    "credential_id",
                    "detail_code",
                    "previous_hash",
                    "event_hash",
                }:
                    raise OperatorAuditStoreError("operator audit database schema is invalid")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operator_audit_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    ) STRICT
                    """
                )
                metadata_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(operator_audit_metadata)")
                }
                if metadata_columns != {"key", "value"}:
                    raise OperatorAuditStoreError(
                        "operator audit database metadata schema is invalid"
                    )
                if schema_version < CURRENT_AUDIT_SCHEMA_VERSION:
                    self._refresh_chain_tip_metadata(connection)
                connection.execute(f"PRAGMA user_version = {CURRENT_AUDIT_SCHEMA_VERSION}")
        except sqlite3.DatabaseError as error:
            raise OperatorAuditStoreError(
                "operator audit database could not be initialized"
            ) from error

    def _load_persistent_events(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            stored_rows = self._fetch_stored_rows(connection)
            chain_tip = self._read_chain_tip(connection)
            integrity = _verify_stored_rows(stored_rows, chain_tip)
            self._integrity = integrity
            if integrity != "tamper_detected":
                self._prune_oldest(connection)
                stored_rows = self._fetch_stored_rows(connection)
                chain_tip = self._read_chain_tip(connection)
                integrity = _verify_stored_rows(stored_rows, chain_tip)

        self._integrity = integrity
        self._events = deque(row.event for row in stored_rows[-self._max_events :])
        if stored_rows:
            last = stored_rows[-1]
            self._next_sequence = last.event.sequence + 1
            self._last_hash = last.event_hash
        else:
            self._next_sequence = 1
            self._last_hash = GENESIS_AUDIT_HASH

    def _prune_oldest(self, connection: sqlite3.Connection) -> None:
        total_count = int(
            connection.execute("SELECT COUNT(*) FROM operator_audit_events").fetchone()[0]
        )
        delete_count = max(0, total_count - self._max_events)
        if delete_count == 0:
            return
        connection.execute(
            """
            DELETE FROM operator_audit_events
            WHERE sequence IN (
                SELECT sequence FROM operator_audit_events
                ORDER BY sequence ASC
                LIMIT ?
            )
            """,
            (delete_count,),
        )
        if self._integrity == "verified":
            self._integrity = "retention_gap"

    def _fetch_stored_rows(self, connection: sqlite3.Connection) -> tuple[_StoredAuditRow, ...]:
        rows = connection.execute(
            """
            SELECT sequence, recorded_at, source, action, outcome, principal_kind,
                   credential_id, detail_code, previous_hash, event_hash
            FROM operator_audit_events
            ORDER BY sequence ASC
            """,
        ).fetchall()
        return tuple(_row_to_stored_event(row) for row in rows)

    def _read_chain_tip(self, connection: sqlite3.Connection) -> _AuditChainTip | None:
        rows = connection.execute(
            """
            SELECT key, value
            FROM operator_audit_metadata
            WHERE key IN (?, ?)
            """,
            (CHAIN_TIP_SEQUENCE_KEY, CHAIN_TIP_HASH_KEY),
        ).fetchall()
        values = {str(row[0]): str(row[1]) for row in rows}
        if set(values) != {CHAIN_TIP_SEQUENCE_KEY, CHAIN_TIP_HASH_KEY}:
            return None
        try:
            sequence = int(values[CHAIN_TIP_SEQUENCE_KEY])
            event_hash = bytes.fromhex(values[CHAIN_TIP_HASH_KEY])
        except ValueError:
            return None
        if sequence < 0 or len(event_hash) != 32:
            return None
        return _AuditChainTip(sequence=sequence, event_hash=event_hash)

    def _write_chain_tip(
        self,
        connection: sqlite3.Connection,
        chain_tip: _AuditChainTip,
    ) -> None:
        connection.executemany(
            """
            INSERT INTO operator_audit_metadata (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (
                (CHAIN_TIP_SEQUENCE_KEY, str(chain_tip.sequence)),
                (CHAIN_TIP_HASH_KEY, chain_tip.event_hash.hex()),
            ),
        )

    def _refresh_chain_tip_metadata(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            """
            SELECT sequence, event_hash
            FROM operator_audit_events
            ORDER BY sequence DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            chain_tip = _AuditChainTip(sequence=0, event_hash=GENESIS_AUDIT_HASH)
        else:
            event_hash = bytes(cast(bytes, row[1]))
            if len(event_hash) != 32:
                raise OperatorAuditStoreError("operator audit database hash shape is invalid")
            chain_tip = _AuditChainTip(sequence=int(cast(int, row[0])), event_hash=event_hash)
        self._write_chain_tip(connection, chain_tip)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        database_path = self._require_database_path()
        if database_path.is_symlink() or not database_path.is_file():
            raise OperatorAuditStoreError("operator audit database operation failed")
        if os.name == "posix" and stat.S_IMODE(database_path.stat().st_mode) & 0o077:
            raise OperatorAuditStoreError("operator audit database operation failed")
        try:
            connection = sqlite3.connect(
                f"{database_path.as_uri()}?mode=rw",
                timeout=3,
                uri=True,
            )
        except sqlite3.DatabaseError as error:
            raise OperatorAuditStoreError("operator audit database operation failed") from error
        try:
            with connection:
                yield connection
        except sqlite3.DatabaseError as error:
            raise OperatorAuditStoreError("operator audit database operation failed") from error
        finally:
            connection.close()

    def _require_database_path(self) -> Path:
        if self._database_path is None:
            raise OperatorAuditStoreError("operator audit database path is not configured")
        return self._database_path


def _audit_token(value: str) -> str:
    normalized = value.strip().lower()
    if AUDIT_TOKEN_PATTERN.fullmatch(normalized) is None:
        raise ValueError("audit field is not a safe bounded token")
    return normalized[:MAX_AUDIT_TEXT_LENGTH]


def _audit_event_hash(event: OperatorAuditEvent, previous_hash: bytes) -> bytes:
    digest = hashlib.sha256()
    digest.update(AUDIT_HASH_DOMAIN)
    digest.update(previous_hash)
    for field in (
        str(event.sequence),
        _serialize_datetime(event.recorded_at),
        event.source,
        event.action,
        event.outcome,
        event.principal_kind,
        str(event.credential_id) if event.credential_id is not None else "",
        event.detail_code or "",
    ):
        encoded = field.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.digest()


def _verify_stored_rows(
    stored_rows: tuple[_StoredAuditRow, ...],
    chain_tip: _AuditChainTip | None,
) -> str:
    if chain_tip is None:
        return "tamper_detected"
    if not stored_rows:
        return (
            "verified"
            if chain_tip.sequence == 0 and chain_tip.event_hash == GENESIS_AUDIT_HASH
            else "tamper_detected"
        )
    expected_previous = (
        GENESIS_AUDIT_HASH if stored_rows[0].event.sequence == 1 else stored_rows[0].previous_hash
    )
    status = "verified" if stored_rows[0].event.sequence == 1 else "retention_gap"
    for row in stored_rows:
        if row.previous_hash != expected_previous:
            return "tamper_detected"
        if _audit_event_hash(row.event, row.previous_hash) != row.event_hash:
            return "tamper_detected"
        expected_previous = row.event_hash
    last_row = stored_rows[-1]
    if chain_tip.sequence != last_row.event.sequence or chain_tip.event_hash != last_row.event_hash:
        return "tamper_detected"
    return status


def _row_to_stored_event(row: sqlite3.Row | tuple[object, ...]) -> _StoredAuditRow:
    previous_hash = bytes(cast(bytes, row[8]))
    event_hash = bytes(cast(bytes, row[9]))
    if len(previous_hash) != 32 or len(event_hash) != 32:
        raise OperatorAuditStoreError("operator audit database hash shape is invalid")
    event = OperatorAuditEvent(
        sequence=int(cast(int, row[0])),
        recorded_at=_parse_datetime(str(row[1])),
        source=_audit_token(str(row[2])),
        action=_audit_token(str(row[3])),
        outcome=_audit_token(str(row[4])),
        principal_kind=_audit_token(str(row[5])),
        credential_id=UUID(str(row[6])) if row[6] is not None else None,
        detail_code=_audit_token(str(row[7])) if row[7] is not None else None,
        previous_hash=previous_hash.hex(),
        event_hash=event_hash.hex(),
    )
    return _StoredAuditRow(event=event, previous_hash=previous_hash, event_hash=event_hash)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _serialize_datetime(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
