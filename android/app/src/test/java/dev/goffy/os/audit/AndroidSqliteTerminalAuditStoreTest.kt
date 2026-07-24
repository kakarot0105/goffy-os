package dev.goffy.os.audit

import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteConstraintException
import android.os.Build
import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GOFFY_PROTOCOL_VERSION
import dev.goffy.os.protocol.GOFFY_ROM_CHECKLIST_TOOL
import dev.goffy.os.protocol.GOFFY_ROM_STATUS_TOOL
import dev.goffy.os.protocol.MAC_APPS_LIST_TOOL
import dev.goffy.os.protocol.MAC_CLIPBOARD_READ_TOOL
import dev.goffy.os.protocol.MAC_FILES_LARGEST_TOOL
import dev.goffy.os.protocol.MAC_PROCESSES_LIST_TOOL
import dev.goffy.os.protocol.PHONE_BATTERY_STATUS_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_FORGET_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_LIST_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_REMEMBER_TOOL
import dev.goffy.os.protocol.PHONE_MEMORY_UPDATE_TOOL
import dev.goffy.os.protocol.PHONE_OCR_READ_TOOL
import dev.goffy.os.protocol.PHONE_QR_READ_TOOL
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
    fun databaseAcceptsMacClipboardSafeMetadata() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val clipboardRecord = record(index = 1, recordedAtEpochMillis = 100).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = MAC_CLIPBOARD_READ_TOOL,
            permission = AuditPermission.SAFE,
        )

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(clipboardRecord, store.upsert(clipboardRecord))
            assertEquals(listOf(clipboardRecord), store.load().records)
        }
    }

    @Test
    fun databaseAcceptsLargestMacFilesSafeMetadata() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val largestFilesRecord = record(index = 1, recordedAtEpochMillis = 100).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = MAC_FILES_LARGEST_TOOL,
            permission = AuditPermission.SAFE,
        )

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(largestFilesRecord, store.upsert(largestFilesRecord))
            assertEquals(listOf(largestFilesRecord), store.load().records)
        }
    }

    @Test
    fun databaseAcceptsMacProcessesSafeMetadata() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val processRecord = record(index = 1, recordedAtEpochMillis = 100).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = MAC_PROCESSES_LIST_TOOL,
            permission = AuditPermission.SAFE,
        )

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(processRecord, store.upsert(processRecord))
            assertEquals(listOf(processRecord), store.load().records)
        }
    }

    @Test
    fun databaseAcceptsMacAppsSafeMetadata() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val appsRecord = record(index = 1, recordedAtEpochMillis = 100).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = MAC_APPS_LIST_TOOL,
            permission = AuditPermission.SAFE,
        )

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(appsRecord, store.upsert(appsRecord))
            assertEquals(listOf(appsRecord), store.load().records)
        }
    }

    @Test
    fun databaseAcceptsGoffyRomSafeMetadata() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val romStatusRecord = record(index = 1, recordedAtEpochMillis = 100).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = GOFFY_ROM_STATUS_TOOL,
            permission = AuditPermission.SAFE,
        )
        val romChecklistRecord = record(index = 2, recordedAtEpochMillis = 200).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = GOFFY_ROM_CHECKLIST_TOOL,
            permission = AuditPermission.SAFE,
        )

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(romStatusRecord, store.upsert(romStatusRecord))
            assertEquals(romChecklistRecord, store.upsert(romChecklistRecord))
            assertEquals(listOf(romStatusRecord, romChecklistRecord), store.load().records)
        }
    }

    @Test
    fun databaseAcceptsForegroundQrAndOcrSafeMetadata() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val qrRecord = record(index = 1, recordedAtEpochMillis = 100).copy(
            toolName = PHONE_QR_READ_TOOL,
        )
        val ocrRecord = record(index = 2, recordedAtEpochMillis = 200).copy(
            toolName = PHONE_OCR_READ_TOOL,
        )

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(qrRecord, store.upsert(qrRecord))
            assertEquals(ocrRecord, store.upsert(ocrRecord))
            assertEquals(listOf(qrRecord, ocrRecord), store.load().records)
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
                assertEquals(10, cursor.getInt(0))
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

    @Test
    fun migratesVersionFiveToolConstraintBeforeWritingMacAppsRows() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val databasePath = application.getDatabasePath(databaseName).absolutePath
        val first = record(index = 1, recordedAtEpochMillis = 100)
        val appCatalogRecord = record(index = 2, recordedAtEpochMillis = 300).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = MAC_APPS_LIST_TOOL,
            permission = AuditPermission.SAFE,
        )

        SQLiteDatabase.openOrCreateDatabase(databasePath, null).use { database ->
            createLegacyVersionFiveAuditTable(database)
            database.insertOrThrow("terminal_audit", null, first.toContentValues())
            database.execSQL("PRAGMA user_version = 5")
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(listOf(first), store.load().records)
            assertEquals(appCatalogRecord, store.upsert(appCatalogRecord))
            assertEquals(listOf(first, appCatalogRecord), store.load().records)
        }

        SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READONLY).use { database ->
            database.rawQuery("PRAGMA user_version", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(10, cursor.getInt(0))
            }
        }
    }

    @Test
    fun migratesVersionSixToolConstraintBeforeWritingPhoneMemoryRows() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val databasePath = application.getDatabasePath(databaseName).absolutePath
        val first = record(index = 1, recordedAtEpochMillis = 100)
        val memoryListRecord = record(index = 2, recordedAtEpochMillis = 200).copy(
            toolName = PHONE_MEMORY_LIST_TOOL,
            permission = AuditPermission.SAFE,
        )
        val memoryRememberRecord = record(index = 3, recordedAtEpochMillis = 300).copy(
            toolName = PHONE_MEMORY_REMEMBER_TOOL,
            permission = AuditPermission.CONFIRM,
            approvalOutcome = AuditApprovalOutcome.APPROVED,
        )

        SQLiteDatabase.openOrCreateDatabase(databasePath, null).use { database ->
            createLegacyVersionSixAuditTable(database)
            database.insertOrThrow("terminal_audit", null, first.toContentValues())
            database.execSQL("PRAGMA user_version = 6")
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(listOf(first), store.load().records)
            assertEquals(memoryListRecord, store.upsert(memoryListRecord))
            assertEquals(memoryRememberRecord, store.upsert(memoryRememberRecord))
            assertEquals(listOf(first, memoryListRecord, memoryRememberRecord), store.load().records)
        }

        SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READONLY).use { database ->
            database.rawQuery("PRAGMA user_version", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(10, cursor.getInt(0))
            }
        }
    }

    @Test
    fun migratesVersionNineToolConstraintBeforeWritingGoffyRomChecklistRows() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val databasePath = application.getDatabasePath(databaseName).absolutePath
        val first = record(index = 1, recordedAtEpochMillis = 100)
        val romChecklistRecord = record(index = 2, recordedAtEpochMillis = 200).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = GOFFY_ROM_CHECKLIST_TOOL,
            permission = AuditPermission.SAFE,
        )

        SQLiteDatabase.openOrCreateDatabase(databasePath, null).use { database ->
            createLegacyVersionNineAuditTable(database)
            database.insertOrThrow("terminal_audit", null, first.toContentValues())
            database.execSQL("PRAGMA user_version = 9")
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(listOf(first), store.load().records)
            assertEquals(romChecklistRecord, store.upsert(romChecklistRecord))
            assertEquals(listOf(first, romChecklistRecord), store.load().records)
        }

        SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READONLY).use { database ->
            database.rawQuery("PRAGMA user_version", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(10, cursor.getInt(0))
            }
        }
    }

    @Test
    fun migratesVersionSevenToolConstraintBeforeWritingPerMemoryRows() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val databasePath = application.getDatabasePath(databaseName).absolutePath
        val first = record(index = 1, recordedAtEpochMillis = 100)
        val memoryForgetRecord = record(index = 2, recordedAtEpochMillis = 200).copy(
            toolName = PHONE_MEMORY_FORGET_TOOL,
            permission = AuditPermission.CONFIRM,
            approvalOutcome = AuditApprovalOutcome.APPROVED,
        )
        val memoryUpdateRecord = record(index = 3, recordedAtEpochMillis = 300).copy(
            toolName = PHONE_MEMORY_UPDATE_TOOL,
            permission = AuditPermission.CONFIRM,
            approvalOutcome = AuditApprovalOutcome.APPROVED,
        )

        SQLiteDatabase.openOrCreateDatabase(databasePath, null).use { database ->
            createLegacyVersionSevenAuditTable(database)
            database.insertOrThrow("terminal_audit", null, first.toContentValues())
            database.execSQL("PRAGMA user_version = 7")
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(listOf(first), store.load().records)
            assertEquals(memoryForgetRecord, store.upsert(memoryForgetRecord))
            assertEquals(memoryUpdateRecord, store.upsert(memoryUpdateRecord))
            assertEquals(listOf(first, memoryForgetRecord, memoryUpdateRecord), store.load().records)
        }

        SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READONLY).use { database ->
            database.rawQuery("PRAGMA user_version", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(10, cursor.getInt(0))
            }
        }
    }

    @Test
    fun migratesVersionEightToolConstraintBeforeWritingGoffyRomStatusRows() = runTest {
        val application = RuntimeEnvironment.getApplication()
        val databaseName = uniqueDatabaseName()
        application.deleteDatabase(databaseName)
        val databasePath = application.getDatabasePath(databaseName).absolutePath
        val first = record(index = 1, recordedAtEpochMillis = 100)
        val romStatusRecord = record(index = 2, recordedAtEpochMillis = 200).copy(
            executionTarget = ExecutionTarget.MAC,
            toolName = GOFFY_ROM_STATUS_TOOL,
            permission = AuditPermission.SAFE,
        )

        SQLiteDatabase.openOrCreateDatabase(databasePath, null).use { database ->
            createLegacyVersionEightAuditTable(database)
            database.insertOrThrow("terminal_audit", null, first.toContentValues())
            database.execSQL("PRAGMA user_version = 8")
        }

        AndroidSqliteTerminalAuditStore(application, databaseName).useStore { store ->
            assertEquals(listOf(first), store.load().records)
            assertEquals(romStatusRecord, store.upsert(romStatusRecord))
            assertEquals(listOf(first, romStatusRecord), store.load().records)
        }

        SQLiteDatabase.openDatabase(databasePath, null, SQLiteDatabase.OPEN_READONLY).use { database ->
            database.rawQuery("PRAGMA user_version", null).use { cursor ->
                assertTrue(cursor.moveToFirst())
                assertEquals(10, cursor.getInt(0))
            }
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

    private fun createLegacyVersionFiveAuditTable(database: SQLiteDatabase) {
        database.execSQL(
            "CREATE TABLE terminal_audit (" +
                "task_id TEXT PRIMARY KEY NOT NULL CHECK (length(task_id) = 36), " +
                "schema_version INTEGER NOT NULL CHECK (schema_version = $SCHEMA_VERSION), " +
                "recorded_at_epoch_millis INTEGER NOT NULL CHECK (recorded_at_epoch_millis > 0), " +
                "protocol_version TEXT NOT NULL CHECK (length(protocol_version) BETWEEN 1 AND 32), " +
                "source_surface TEXT NOT NULL CHECK (source_surface = 'TERMINAL_TIMELINE'), " +
                "execution_target TEXT NOT NULL CHECK (execution_target IN ('PHONE', 'MAC')), " +
                "tool_name TEXT, " +
                "permission TEXT CHECK (permission IN ('SAFE', 'CONFIRM')), " +
                "terminal_phase TEXT NOT NULL CHECK (terminal_phase IN " +
                "('VERIFIED', 'UNVERIFIED', 'FAILED', 'CANCELLED')), " +
                "approval_outcome TEXT NOT NULL CHECK (approval_outcome IN " +
                "('NOT_REQUIRED', 'APPROVED', 'DENIED', 'EXPIRED', 'CANCELLED')), " +
                "event_kinds TEXT NOT NULL CHECK (length(event_kinds) <= 255), " +
                "CHECK ((tool_name IS NULL AND permission IS NULL) OR " +
                "(tool_name IN " +
                "('mac.clipboard.read', 'mac.files.largest', 'mac.files.list', " +
                "'mac.processes.list', 'mac.system_info', 'git.status') AND " +
                "execution_target = 'MAC' AND permission = 'SAFE') OR " +
                "(tool_name IN ('phone.battery.status', 'phone.device.info', " +
                "'phone.ocr.read', 'phone.qr.read') AND " +
                "execution_target = 'PHONE' AND permission = 'SAFE') OR " +
                "(tool_name IN " +
                "('phone.flashlight.set', 'phone.note.create', 'phone.timer.create') AND " +
                "execution_target = 'PHONE' AND permission = 'CONFIRM')), " +
                "CHECK (permission = 'CONFIRM' OR approval_outcome = 'NOT_REQUIRED'))",
        )
    }

    private fun createLegacyVersionSixAuditTable(database: SQLiteDatabase) {
        database.execSQL(
            "CREATE TABLE terminal_audit (" +
                "task_id TEXT PRIMARY KEY NOT NULL CHECK (length(task_id) = 36), " +
                "schema_version INTEGER NOT NULL CHECK (schema_version = $SCHEMA_VERSION), " +
                "recorded_at_epoch_millis INTEGER NOT NULL CHECK (recorded_at_epoch_millis > 0), " +
                "protocol_version TEXT NOT NULL CHECK (length(protocol_version) BETWEEN 1 AND 32), " +
                "source_surface TEXT NOT NULL CHECK (source_surface = 'TERMINAL_TIMELINE'), " +
                "execution_target TEXT NOT NULL CHECK (execution_target IN ('PHONE', 'MAC')), " +
                "tool_name TEXT, " +
                "permission TEXT CHECK (permission IN ('SAFE', 'CONFIRM')), " +
                "terminal_phase TEXT NOT NULL CHECK (terminal_phase IN " +
                "('VERIFIED', 'UNVERIFIED', 'FAILED', 'CANCELLED')), " +
                "approval_outcome TEXT NOT NULL CHECK (approval_outcome IN " +
                "('NOT_REQUIRED', 'APPROVED', 'DENIED', 'EXPIRED', 'CANCELLED')), " +
                "event_kinds TEXT NOT NULL CHECK (length(event_kinds) <= 255), " +
                "CHECK ((tool_name IS NULL AND permission IS NULL) OR " +
                "(tool_name IN " +
                "('mac.apps.list', 'mac.clipboard.read', 'mac.files.largest', 'mac.files.list', " +
                "'mac.processes.list', 'mac.system_info', 'git.status') AND " +
                "execution_target = 'MAC' AND permission = 'SAFE') OR " +
                "(tool_name IN ('phone.battery.status', 'phone.device.info', " +
                "'phone.ocr.read', 'phone.qr.read') AND " +
                "execution_target = 'PHONE' AND permission = 'SAFE') OR " +
                "(tool_name IN " +
                "('phone.flashlight.set', 'phone.note.create', 'phone.timer.create') AND " +
                "execution_target = 'PHONE' AND permission = 'CONFIRM')), " +
                "CHECK (permission = 'CONFIRM' OR approval_outcome = 'NOT_REQUIRED'))",
        )
    }

    private fun createLegacyVersionSevenAuditTable(database: SQLiteDatabase) {
        database.execSQL(
            "CREATE TABLE terminal_audit (" +
                "task_id TEXT PRIMARY KEY NOT NULL CHECK (length(task_id) = 36), " +
                "schema_version INTEGER NOT NULL CHECK (schema_version = $SCHEMA_VERSION), " +
                "recorded_at_epoch_millis INTEGER NOT NULL CHECK (recorded_at_epoch_millis > 0), " +
                "protocol_version TEXT NOT NULL CHECK (length(protocol_version) BETWEEN 1 AND 32), " +
                "source_surface TEXT NOT NULL CHECK (source_surface = 'TERMINAL_TIMELINE'), " +
                "execution_target TEXT NOT NULL CHECK (execution_target IN ('PHONE', 'MAC')), " +
                "tool_name TEXT, " +
                "permission TEXT CHECK (permission IN ('SAFE', 'CONFIRM')), " +
                "terminal_phase TEXT NOT NULL CHECK (terminal_phase IN " +
                "('VERIFIED', 'UNVERIFIED', 'FAILED', 'CANCELLED')), " +
                "approval_outcome TEXT NOT NULL CHECK (approval_outcome IN " +
                "('NOT_REQUIRED', 'APPROVED', 'DENIED', 'EXPIRED', 'CANCELLED')), " +
                "event_kinds TEXT NOT NULL CHECK (length(event_kinds) <= 255), " +
                "CHECK ((tool_name IS NULL AND permission IS NULL) OR " +
                "(tool_name IN " +
                "('mac.apps.list', 'mac.clipboard.read', 'mac.files.largest', 'mac.files.list', " +
                "'mac.processes.list', 'mac.system_info', 'git.status') AND " +
                "execution_target = 'MAC' AND permission = 'SAFE') OR " +
                "(tool_name IN ('phone.battery.status', 'phone.device.info', " +
                "'phone.memory.list', 'phone.ocr.read', 'phone.qr.read') AND " +
                "execution_target = 'PHONE' AND permission = 'SAFE') OR " +
                "(tool_name IN " +
                "('phone.flashlight.set', 'phone.memory.forget_all', " +
                "'phone.memory.remember', 'phone.note.create', 'phone.timer.create') AND " +
                "execution_target = 'PHONE' AND permission = 'CONFIRM')), " +
                "CHECK (permission = 'CONFIRM' OR approval_outcome = 'NOT_REQUIRED'))",
        )
    }

    private fun createLegacyVersionEightAuditTable(database: SQLiteDatabase) {
        database.execSQL(
            "CREATE TABLE terminal_audit (" +
                "task_id TEXT PRIMARY KEY NOT NULL CHECK (length(task_id) = 36), " +
                "schema_version INTEGER NOT NULL CHECK (schema_version = $SCHEMA_VERSION), " +
                "recorded_at_epoch_millis INTEGER NOT NULL CHECK (recorded_at_epoch_millis > 0), " +
                "protocol_version TEXT NOT NULL CHECK (length(protocol_version) BETWEEN 1 AND 32), " +
                "source_surface TEXT NOT NULL CHECK (source_surface = 'TERMINAL_TIMELINE'), " +
                "execution_target TEXT NOT NULL CHECK (execution_target IN ('PHONE', 'MAC')), " +
                "tool_name TEXT, " +
                "permission TEXT CHECK (permission IN ('SAFE', 'CONFIRM')), " +
                "terminal_phase TEXT NOT NULL CHECK (terminal_phase IN " +
                "('VERIFIED', 'UNVERIFIED', 'FAILED', 'CANCELLED')), " +
                "approval_outcome TEXT NOT NULL CHECK (approval_outcome IN " +
                "('NOT_REQUIRED', 'APPROVED', 'DENIED', 'EXPIRED', 'CANCELLED')), " +
                "event_kinds TEXT NOT NULL CHECK (length(event_kinds) <= 255), " +
                "CHECK ((tool_name IS NULL AND permission IS NULL) OR " +
                "(tool_name IN " +
                "('mac.apps.list', 'mac.clipboard.read', 'mac.files.largest', 'mac.files.list', " +
                "'mac.processes.list', 'mac.system_info', 'git.status') AND " +
                "execution_target = 'MAC' AND permission = 'SAFE') OR " +
                "(tool_name IN ('phone.battery.status', 'phone.device.info', " +
                "'phone.memory.list', 'phone.ocr.read', 'phone.qr.read') AND " +
                "execution_target = 'PHONE' AND permission = 'SAFE') OR " +
                "(tool_name IN " +
                "('phone.flashlight.set', 'phone.memory.forget', 'phone.memory.forget_all', " +
                "'phone.memory.remember', 'phone.memory.update', 'phone.note.create', " +
                "'phone.timer.create') AND " +
                "execution_target = 'PHONE' AND permission = 'CONFIRM')), " +
                "CHECK (permission = 'CONFIRM' OR approval_outcome = 'NOT_REQUIRED'))",
        )
    }

    private fun createLegacyVersionNineAuditTable(database: SQLiteDatabase) {
        database.execSQL(
            "CREATE TABLE terminal_audit (" +
                "task_id TEXT PRIMARY KEY NOT NULL CHECK (length(task_id) = 36), " +
                "schema_version INTEGER NOT NULL CHECK (schema_version = $SCHEMA_VERSION), " +
                "recorded_at_epoch_millis INTEGER NOT NULL CHECK (recorded_at_epoch_millis > 0), " +
                "protocol_version TEXT NOT NULL CHECK (length(protocol_version) BETWEEN 1 AND 32), " +
                "source_surface TEXT NOT NULL CHECK (source_surface = 'TERMINAL_TIMELINE'), " +
                "execution_target TEXT NOT NULL CHECK (execution_target IN ('PHONE', 'MAC')), " +
                "tool_name TEXT, " +
                "permission TEXT CHECK (permission IN ('SAFE', 'CONFIRM')), " +
                "terminal_phase TEXT NOT NULL CHECK (terminal_phase IN " +
                "('VERIFIED', 'UNVERIFIED', 'FAILED', 'CANCELLED')), " +
                "approval_outcome TEXT NOT NULL CHECK (approval_outcome IN " +
                "('NOT_REQUIRED', 'APPROVED', 'DENIED', 'EXPIRED', 'CANCELLED')), " +
                "event_kinds TEXT NOT NULL CHECK (length(event_kinds) <= 255), " +
                "CHECK ((tool_name IS NULL AND permission IS NULL) OR " +
                "(tool_name IN " +
                "('goffy.rom.status', 'mac.apps.list', 'mac.clipboard.read', " +
                "'mac.files.largest', 'mac.files.list', " +
                "'mac.processes.list', 'mac.system_info', 'git.status') AND " +
                "execution_target = 'MAC' AND permission = 'SAFE') OR " +
                "(tool_name IN ('phone.battery.status', 'phone.device.info', " +
                "'phone.memory.list', 'phone.ocr.read', 'phone.qr.read') AND " +
                "execution_target = 'PHONE' AND permission = 'SAFE') OR " +
                "(tool_name IN " +
                "('phone.flashlight.set', 'phone.memory.forget', 'phone.memory.forget_all', " +
                "'phone.memory.remember', 'phone.memory.update', 'phone.note.create', " +
                "'phone.timer.create') AND " +
                "execution_target = 'PHONE' AND permission = 'CONFIRM')), " +
                "CHECK (permission = 'CONFIRM' OR approval_outcome = 'NOT_REQUIRED'))",
        )
    }
}
