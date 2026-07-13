package dev.goffy.os.audit

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteConstraintException
import android.os.Build
import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GOFFY_PROTOCOL_VERSION
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import java.util.UUID
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.TIRAMISU])
class AndroidSqliteTerminalAuditStoreTest {
    @Test
    fun reopensAndRoundTripsStoredAuditRecords() = runTest {
        val databaseName = uniqueDatabaseName()
        RuntimeEnvironment.getApplication().deleteDatabase(databaseName)
        val record = record(index = 1, recordedAtEpochMillis = 1_720_000_000_001)

        AndroidSqliteTerminalAuditStore(RuntimeEnvironment.getApplication(), databaseName).useStore { store ->
            assertEquals(record, store.upsert(record))
        }

        AndroidSqliteTerminalAuditStore(RuntimeEnvironment.getApplication(), databaseName).useStore { store ->
            val loaded = store.load()
            assertEquals(0, loaded.discardedCorruptRows)
            assertEquals(listOf(record), loaded.records)
        }
    }

    @Test
    fun retainsOnlyTheNewestFiftyRowsAfterFiftyFiveWrites() = runTest {
        val databaseName = uniqueDatabaseName()
        RuntimeEnvironment.getApplication().deleteDatabase(databaseName)

        AndroidSqliteTerminalAuditStore(RuntimeEnvironment.getApplication(), databaseName).useStore { store ->
            (1..55).forEach { index ->
                store.upsert(record(index = index, recordedAtEpochMillis = index.toLong()))
            }
            val loaded = store.load()

            assertEquals(0, loaded.discardedCorruptRows)
            assertEquals(50, loaded.records.size)
            assertEquals((6L..55L).toList(), loaded.records.map { it.recordedAtEpochMillis })
        }
    }

    @Test
    fun loadsAuditRowsInChronologicalOrder() = runTest {
        val databaseName = uniqueDatabaseName()
        RuntimeEnvironment.getApplication().deleteDatabase(databaseName)
        val first = record(index = 1, recordedAtEpochMillis = 300)
        val second = record(index = 2, recordedAtEpochMillis = 100)
        val third = record(index = 3, recordedAtEpochMillis = 200)

        AndroidSqliteTerminalAuditStore(RuntimeEnvironment.getApplication(), databaseName).useStore { store ->
            store.upsert(first)
            store.upsert(second)
            store.upsert(third)

            val loaded = store.load()

            assertEquals(listOf(second, third, first), loaded.records)
        }
    }

    @Test
    fun discardsCorruptRowsWithoutDeletingThem() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val valid = record(index = 1, recordedAtEpochMillis = 100)

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            store.upsert(valid)
        }

        val databasePath = application.getDatabasePath(databaseName).absolutePath
        val writable = SQLiteDatabase.openDatabase(
            databasePath,
            null,
            SQLiteDatabase.OPEN_READWRITE,
        )
        try {
            val corruptValues = ContentValues().apply {
                put("task_id", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
                put("schema_version", SCHEMA_VERSION)
                put("recorded_at_epoch_millis", 200L)
                put("protocol_version", GOFFY_PROTOCOL_VERSION)
                put("source_surface", AuditSourceSurface.TERMINAL_TIMELINE.name)
                put("execution_target", ExecutionTarget.PHONE.name)
                put("tool_name", PHONE_BATTERY_STATUS_TOOL)
                put("permission", AuditPermission.SAFE.name)
                put("terminal_phase", TerminalAuditPhase.VERIFIED.name)
                put("approval_outcome", AuditApprovalOutcome.NOT_REQUIRED.name)
                put("event_kinds", TaskEventKind.VERIFY.name)
            }
            writable.insertOrThrow("terminal_audit", null, corruptValues)
        } finally {
            writable.close()
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            val loaded = store.load()

            assertEquals(1, loaded.discardedCorruptRows)
            assertEquals(listOf(valid), loaded.records)
        }

        val readable = SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READONLY)
        try {
            readable.rawQuery("SELECT COUNT(*) FROM terminal_audit", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(2, cursor.getInt(0))
            }
        } finally {
            readable.close()
        }
    }

    @Test
    fun databaseRejectsImpossibleCapabilityMetadata() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            store.upsert(record(index = 1, recordedAtEpochMillis = 100))
        }

        val databasePath = application.getDatabasePath(databaseName).absolutePath
        SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READWRITE).use { database ->
            val impossible = ContentValues().apply {
                put("task_id", "22222222-2222-4222-8222-222222222222")
                put("schema_version", SCHEMA_VERSION)
                put("recorded_at_epoch_millis", 200L)
                put("protocol_version", GOFFY_PROTOCOL_VERSION)
                put("source_surface", AuditSourceSurface.TERMINAL_TIMELINE.name)
                put("execution_target", ExecutionTarget.MAC.name)
                put("tool_name", PHONE_BATTERY_STATUS_TOOL)
                put("permission", AuditPermission.SAFE.name)
                put("terminal_phase", TerminalAuditPhase.VERIFIED.name)
                put("approval_outcome", AuditApprovalOutcome.NOT_REQUIRED.name)
                put("event_kinds", TaskEventKind.VERIFY.name)
            }

            assertThrows(SQLiteConstraintException::class.java) {
                database.insertOrThrow("terminal_audit", null, impossible)
            }
        }
    }

    @Test
    fun typedCompatibilityDiscardsUnknownProtocolWithoutBlockingCurrentWrites() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val first = record(index = 1, recordedAtEpochMillis = 100)
        val second = record(index = 2, recordedAtEpochMillis = 300)

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            store.upsert(first)
        }

        val databasePath = application.getDatabasePath(databaseName).absolutePath
        SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READWRITE).use { database ->
            val unsupported = ContentValues().apply {
                put("task_id", "33333333-3333-4333-8333-333333333333")
                put("schema_version", SCHEMA_VERSION)
                put("recorded_at_epoch_millis", 200L)
                put("protocol_version", "future-test-version")
                put("source_surface", AuditSourceSurface.TERMINAL_TIMELINE.name)
                put("execution_target", ExecutionTarget.PHONE.name)
                put("tool_name", PHONE_BATTERY_STATUS_TOOL)
                put("permission", AuditPermission.SAFE.name)
                put("terminal_phase", TerminalAuditPhase.VERIFIED.name)
                put("approval_outcome", AuditApprovalOutcome.NOT_REQUIRED.name)
                put("event_kinds", TaskEventKind.VERIFY.name)
            }
            database.insertOrThrow("terminal_audit", null, unsupported)
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(second, store.upsert(second))
            val loaded = store.load()
            assertEquals(listOf(first, second), loaded.records)
            assertEquals(1, loaded.discardedCorruptRows)
        }
    }

    @Test
    fun migratesVersionOneProtocolConstraintBeforeWritingCurrentRows() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val databasePath = application.getDatabasePath(databaseName).absolutePath
        val first = record(index = 1, recordedAtEpochMillis = 100)
        val second = record(index = 2, recordedAtEpochMillis = 300)

        SQLiteDatabase.openOrCreateDatabase(databasePath, null).use { database ->
            database.execSQL(
                "CREATE TABLE terminal_audit (" +
                    "task_id TEXT PRIMARY KEY NOT NULL, " +
                    "schema_version INTEGER NOT NULL, " +
                    "recorded_at_epoch_millis INTEGER NOT NULL, " +
                    "protocol_version TEXT NOT NULL CHECK (protocol_version = '$GOFFY_PROTOCOL_VERSION'), " +
                    "source_surface TEXT NOT NULL, execution_target TEXT NOT NULL, " +
                    "tool_name TEXT, permission TEXT, terminal_phase TEXT NOT NULL, " +
                    "approval_outcome TEXT NOT NULL, event_kinds TEXT NOT NULL)",
            )
            database.insertOrThrow("terminal_audit", null, first.toContentValues())
            database.execSQL("PRAGMA user_version = 1")
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(listOf(first), store.load().records)
            assertEquals(second, store.upsert(second))
        }

        SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READWRITE).use { database ->
            database.rawQuery("PRAGMA user_version", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(2, cursor.getInt(0))
            }
            database.insertOrThrow(
                "terminal_audit",
                null,
                record(index = 3, recordedAtEpochMillis = 200)
                    .toContentValues(protocolVersion = "future-test-version"),
            )
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            val loaded = store.load()
            assertEquals(listOf(first, second), loaded.records)
            assertEquals(1, loaded.discardedCorruptRows)
        }
    }

    private suspend fun AndroidSqliteTerminalAuditStore.useStore(
        block: suspend (AndroidSqliteTerminalAuditStore) -> Unit,
    ) {
        try {
            block(this)
        } finally {
            close()
        }
    }

    private fun uniqueDatabaseName(): String = "audit-test-${UUID.randomUUID()}.db"

    private fun record(
        index: Int,
        recordedAtEpochMillis: Long,
    ): ClosedTerminalAuditRecord = ClosedTerminalAuditRecord(
        taskId = UUID.fromString("00000000-0000-4000-8000-${index.toString().padStart(12, '0')}"),
        recordedAtEpochMillis = recordedAtEpochMillis,
        protocolVersion = GOFFY_PROTOCOL_VERSION,
        sourceSurface = AuditSourceSurface.TERMINAL_TIMELINE,
        executionTarget = ExecutionTarget.PHONE,
        toolName = PHONE_BATTERY_STATUS_TOOL,
        permission = AuditPermission.SAFE,
        phase = TerminalAuditPhase.VERIFIED,
        approvalOutcome = AuditApprovalOutcome.NOT_REQUIRED,
        eventKinds = listOf(TaskEventKind.OBSERVE, TaskEventKind.VERIFY),
    )

    private fun ClosedTerminalAuditRecord.toContentValues(
        protocolVersion: String = this.protocolVersion,
    ): ContentValues = ContentValues().apply {
        put("task_id", taskId.toString())
        put("schema_version", schemaVersion)
        put("recorded_at_epoch_millis", recordedAtEpochMillis)
        put("protocol_version", protocolVersion)
        put("source_surface", sourceSurface.name)
        put("execution_target", executionTarget.name)
        put("tool_name", toolName)
        put("permission", permission?.name)
        put("terminal_phase", phase.name)
        put("approval_outcome", approvalOutcome.name)
        put("event_kinds", eventKinds.joinToString(",") { it.name })
    }
}
