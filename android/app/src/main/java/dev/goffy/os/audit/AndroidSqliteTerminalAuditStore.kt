package dev.goffy.os.audit

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.protocol.ExecutionTarget
import java.util.UUID

class AndroidSqliteTerminalAuditStore(
    context: Context,
    databaseName: String = DATABASE_NAME,
) : TerminalAuditStore {
    private val helper = AuditDatabaseHelper(context.applicationContext, databaseName)

    override suspend fun load(): ClosedTerminalAuditLoadResult =
        helper.readableDatabase.loadRecords()

    override suspend fun upsert(record: ClosedTerminalAuditRecord): ClosedTerminalAuditRecord {
        val database = helper.writableDatabase
        database.beginTransaction()
        return try {
            val values = ContentValues().apply {
                put(COLUMN_SCHEMA_VERSION, record.schemaVersion)
                put(COLUMN_TASK_ID, record.taskId.toString())
                put(COLUMN_RECORDED_AT_EPOCH_MILLIS, record.recordedAtEpochMillis)
                put(COLUMN_PROTOCOL_VERSION, record.protocolVersion)
                put(COLUMN_SOURCE_SURFACE, record.sourceSurface.name)
                put(COLUMN_EXECUTION_TARGET, record.executionTarget.name)
                put(COLUMN_TOOL_NAME, record.toolName)
                put(COLUMN_PERMISSION, record.permission?.name)
                put(COLUMN_TERMINAL_PHASE, record.phase.name)
                put(COLUMN_APPROVAL_OUTCOME, record.approvalOutcome.name)
                put(COLUMN_EVENT_KINDS, record.eventKinds.joinToString(EVENT_KIND_SEPARATOR) { it.name })
            }
            val rowId = database.insertWithOnConflict(
                TABLE_AUDIT,
                null,
                values,
                SQLiteDatabase.CONFLICT_REPLACE,
            )
            check(rowId != -1L) { "audit record upsert failed" }
            database.trimToNewestRows()
            val stored = database.readRecord(record.taskId)
                ?: throw IllegalStateException("upserted audit record could not be re-read")
            check(stored == record) { "audit record failed post-write verification" }
            database.setTransactionSuccessful()
            stored
        } finally {
            database.endTransaction()
        }
    }

    override fun close() = helper.close()

    private fun SQLiteDatabase.loadRecords(): ClosedTerminalAuditLoadResult = query(
        TABLE_AUDIT,
        PROJECTION,
        null,
        null,
        null,
        null,
        "$COLUMN_RECORDED_AT_EPOCH_MILLIS ASC, $COLUMN_TASK_ID ASC",
    ).use { cursor ->
        val records = mutableListOf<ClosedTerminalAuditRecord>()
        var discarded = 0
        while (cursor.moveToNext()) {
            val record = runCatching { cursor.readRecord() }.getOrNull()
            if (record == null) {
                discarded += 1
            } else {
                records += record
            }
        }
        ClosedTerminalAuditLoadResult(records = records, discardedCorruptRows = discarded)
    }

    private fun SQLiteDatabase.readRecord(taskId: UUID): ClosedTerminalAuditRecord? = query(
        TABLE_AUDIT,
        PROJECTION,
        "$COLUMN_TASK_ID = ?",
        arrayOf(taskId.toString()),
        null,
        null,
        null,
        "1",
    ).use { cursor ->
        if (!cursor.moveToFirst()) return@use null
        cursor.readRecord()
    }

    private fun SQLiteDatabase.trimToNewestRows() {
        query(
            TABLE_AUDIT,
            arrayOf(COLUMN_TASK_ID),
            null,
            null,
            null,
            null,
            "$COLUMN_RECORDED_AT_EPOCH_MILLIS DESC, $COLUMN_TASK_ID DESC",
        ).use { cursor ->
            var index = 0
            while (cursor.moveToNext()) {
                if (index >= MAX_ROWS) {
                    delete(
                        TABLE_AUDIT,
                        "$COLUMN_TASK_ID = ?",
                        arrayOf(cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_TASK_ID))),
                    )
                }
                index += 1
            }
        }
    }

    private fun android.database.Cursor.readRecord(): ClosedTerminalAuditRecord {
        val rawToolName = getString(getColumnIndexOrThrow(COLUMN_TOOL_NAME))
        val rawPermission = getString(getColumnIndexOrThrow(COLUMN_PERMISSION))
        val rawEvents = getString(getColumnIndexOrThrow(COLUMN_EVENT_KINDS))
        return ClosedTerminalAuditRecord(
            schemaVersion = getInt(getColumnIndexOrThrow(COLUMN_SCHEMA_VERSION)),
            taskId = UUID.fromString(getString(getColumnIndexOrThrow(COLUMN_TASK_ID))),
            recordedAtEpochMillis = getLong(getColumnIndexOrThrow(COLUMN_RECORDED_AT_EPOCH_MILLIS)),
            protocolVersion = getString(getColumnIndexOrThrow(COLUMN_PROTOCOL_VERSION)),
            sourceSurface = AuditSourceSurface.valueOf(
                getString(getColumnIndexOrThrow(COLUMN_SOURCE_SURFACE)),
            ),
            executionTarget = ExecutionTarget.valueOf(
                getString(getColumnIndexOrThrow(COLUMN_EXECUTION_TARGET)),
            ),
            toolName = rawToolName,
            permission = rawPermission?.let(AuditPermission::valueOf),
            phase = TerminalAuditPhase.valueOf(
                getString(getColumnIndexOrThrow(COLUMN_TERMINAL_PHASE)),
            ),
            approvalOutcome = AuditApprovalOutcome.valueOf(
                getString(getColumnIndexOrThrow(COLUMN_APPROVAL_OUTCOME)),
            ),
            eventKinds = rawEvents.parseEventKinds(),
        )
    }

    private fun String.parseEventKinds(): List<TaskEventKind> =
        if (isBlank()) {
            emptyList()
        } else {
            split(EVENT_KIND_SEPARATOR)
                .map(String::trim)
                .filter(String::isNotEmpty)
                .map(TaskEventKind::valueOf)
        }

    private class AuditDatabaseHelper(
        context: Context,
        databaseName: String,
    ) : SQLiteOpenHelper(context, databaseName, null, DATABASE_VERSION) {
        override fun onCreate(database: SQLiteDatabase) {
            createAuditTable(database)
        }

        override fun onUpgrade(database: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            if (oldVersion !in 1 until DATABASE_VERSION || newVersion != DATABASE_VERSION) {
                error("No audit database migration exists from $oldVersion to $newVersion")
            }
            database.execSQL("ALTER TABLE $TABLE_AUDIT RENAME TO $TABLE_AUDIT_V1")
            createAuditTable(database)
            database.execSQL(
                "INSERT OR IGNORE INTO $TABLE_AUDIT (${PROJECTION.joinToString()}) " +
                    "SELECT ${PROJECTION.joinToString()} FROM $TABLE_AUDIT_V1",
            )
            database.execSQL("DROP TABLE $TABLE_AUDIT_V1")
        }

        private fun createAuditTable(database: SQLiteDatabase) {
            database.execSQL(
                "CREATE TABLE $TABLE_AUDIT (" +
                    "$COLUMN_TASK_ID TEXT PRIMARY KEY NOT NULL " +
                    "CHECK (length($COLUMN_TASK_ID) = 36), " +
                    "$COLUMN_SCHEMA_VERSION INTEGER NOT NULL " +
                    "CHECK ($COLUMN_SCHEMA_VERSION = $SCHEMA_VERSION), " +
                    "$COLUMN_RECORDED_AT_EPOCH_MILLIS INTEGER NOT NULL " +
                    "CHECK ($COLUMN_RECORDED_AT_EPOCH_MILLIS > 0), " +
                    "$COLUMN_PROTOCOL_VERSION TEXT NOT NULL " +
                    "CHECK (length($COLUMN_PROTOCOL_VERSION) BETWEEN 1 AND 32), " +
                    "$COLUMN_SOURCE_SURFACE TEXT NOT NULL " +
                    "CHECK ($COLUMN_SOURCE_SURFACE = 'TERMINAL_TIMELINE'), " +
                    "$COLUMN_EXECUTION_TARGET TEXT NOT NULL " +
                    "CHECK ($COLUMN_EXECUTION_TARGET IN ('PHONE', 'MAC')), " +
                    "$COLUMN_TOOL_NAME TEXT, " +
                    "$COLUMN_PERMISSION TEXT CHECK ($COLUMN_PERMISSION IN ('SAFE', 'CONFIRM')), " +
                    "$COLUMN_TERMINAL_PHASE TEXT NOT NULL " +
                    "CHECK ($COLUMN_TERMINAL_PHASE IN " +
                    "('VERIFIED', 'UNVERIFIED', 'FAILED', 'CANCELLED')), " +
                    "$COLUMN_APPROVAL_OUTCOME TEXT NOT NULL " +
                    "CHECK ($COLUMN_APPROVAL_OUTCOME IN " +
                    "('NOT_REQUIRED', 'APPROVED', 'DENIED', 'EXPIRED', 'CANCELLED')), " +
                    "$COLUMN_EVENT_KINDS TEXT NOT NULL " +
                    "CHECK (length($COLUMN_EVENT_KINDS) <= 255), " +
                    "CHECK (($COLUMN_TOOL_NAME IS NULL AND $COLUMN_PERMISSION IS NULL) OR " +
                    "($COLUMN_TOOL_NAME IN " +
                    "('mac.apps.list', 'mac.clipboard.read', 'mac.files.largest', 'mac.files.list', " +
                    "'mac.processes.list', 'mac.system_info', 'git.status') AND " +
                    "$COLUMN_EXECUTION_TARGET = 'MAC' AND $COLUMN_PERMISSION = 'SAFE') OR " +
                    "($COLUMN_TOOL_NAME IN ('phone.battery.status', 'phone.device.info', " +
                    "'phone.memory.list', 'phone.ocr.read', 'phone.qr.read') AND " +
                    "$COLUMN_EXECUTION_TARGET = 'PHONE' AND $COLUMN_PERMISSION = 'SAFE') OR " +
                    "($COLUMN_TOOL_NAME IN " +
                    "('phone.flashlight.set', 'phone.memory.forget', 'phone.memory.forget_all', " +
                    "'phone.memory.remember', 'phone.memory.update', 'phone.note.create', " +
                    "'phone.timer.create') AND " +
                    "$COLUMN_EXECUTION_TARGET = 'PHONE' AND $COLUMN_PERMISSION = 'CONFIRM')), " +
                    "CHECK ($COLUMN_PERMISSION = 'CONFIRM' OR " +
                    "$COLUMN_APPROVAL_OUTCOME = 'NOT_REQUIRED'))",
            )
        }
    }

    private companion object {
        const val DATABASE_NAME = "goffy_terminal_audit.db"
        const val DATABASE_VERSION = 8
        const val TABLE_AUDIT = "terminal_audit"
        const val TABLE_AUDIT_V1 = "terminal_audit_v1"
        const val COLUMN_SCHEMA_VERSION = "schema_version"
        const val COLUMN_TASK_ID = "task_id"
        const val COLUMN_RECORDED_AT_EPOCH_MILLIS = "recorded_at_epoch_millis"
        const val COLUMN_PROTOCOL_VERSION = "protocol_version"
        const val COLUMN_SOURCE_SURFACE = "source_surface"
        const val COLUMN_EXECUTION_TARGET = "execution_target"
        const val COLUMN_TOOL_NAME = "tool_name"
        const val COLUMN_PERMISSION = "permission"
        const val COLUMN_TERMINAL_PHASE = "terminal_phase"
        const val COLUMN_APPROVAL_OUTCOME = "approval_outcome"
        const val COLUMN_EVENT_KINDS = "event_kinds"
        const val EVENT_KIND_SEPARATOR = ","
        const val MAX_ROWS = 50
        val PROJECTION = arrayOf(
            COLUMN_SCHEMA_VERSION,
            COLUMN_TASK_ID,
            COLUMN_RECORDED_AT_EPOCH_MILLIS,
            COLUMN_PROTOCOL_VERSION,
            COLUMN_SOURCE_SURFACE,
            COLUMN_EXECUTION_TARGET,
            COLUMN_TOOL_NAME,
            COLUMN_PERMISSION,
            COLUMN_TERMINAL_PHASE,
            COLUMN_APPROVAL_OUTCOME,
            COLUMN_EVENT_KINDS,
        )
    }
}
