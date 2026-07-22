package dev.goffy.os.phone

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import dev.goffy.os.protocol.MAX_PHONE_MEMORY_LIST_ENTRIES
import dev.goffy.os.protocol.MAX_PHONE_MEMORY_ROWS
import dev.goffy.os.protocol.PHONE_MEMORY_STATUS_AVAILABLE
import dev.goffy.os.protocol.PhoneMemoryEntry
import dev.goffy.os.protocol.PhoneMemoryDeleted
import dev.goffy.os.protocol.PhoneMemoryForgotten
import dev.goffy.os.protocol.PhoneMemoryList
import dev.goffy.os.protocol.PhoneMemoryRemembered
import dev.goffy.os.protocol.PhoneMemoryUpdated
import dev.goffy.os.protocol.matchesMemoryProvenanceContract
import dev.goffy.os.protocol.matchesMemoryTextContract

class AndroidSqliteMemoryStore(
    context: Context,
    private val nowMillis: () -> Long = System::currentTimeMillis,
) : MemoryStore {
    private val helper = MemoryDatabaseHelper(context.applicationContext)

    override suspend fun remember(text: String, provenance: String): PhoneMemoryRemembered {
        require(text.matchesMemoryTextContract()) { "memory text does not match the local contract" }
        require(provenance.matchesMemoryProvenanceContract()) {
            "memory provenance does not match the local contract"
        }
        val createdAt = nowMillis()
        require(createdAt > 0) { "memory timestamp must be positive" }
        val database = helper.writableDatabase
        database.beginTransaction()
        return try {
            val values = ContentValues().apply {
                put(COLUMN_TEXT, text)
                put(COLUMN_PROVENANCE, provenance)
                put(COLUMN_CREATED_AT, createdAt)
            }
            val memoryId = database.insertOrThrow(TABLE_MEMORIES, null, values)
            database.trimToNewestRows()
            val stored = database.readMemory(memoryId)
                ?: throw IllegalStateException("created memory could not be re-read")
            check(stored.text == text && stored.createdAtEpochMillis == createdAt) {
                "created memory failed post-write verification"
            }
            database.setTransactionSuccessful()
            stored
        } finally {
            database.endTransaction()
        }
    }

    override suspend fun list(maxEntries: Int): PhoneMemoryList {
        require(maxEntries in 1..MAX_PHONE_MEMORY_LIST_ENTRIES) {
            "memory list size is outside the local contract"
        }
        val database = helper.readableDatabase
        val total = database.memoryCount()
        val entries = database.query(
            TABLE_MEMORIES,
            arrayOf(COLUMN_ID, COLUMN_TEXT, COLUMN_CREATED_AT, COLUMN_PROVENANCE),
            null,
            null,
            null,
            null,
            "$COLUMN_CREATED_AT DESC, $COLUMN_ID DESC",
            maxEntries.toString(),
        ).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    add(
                        PhoneMemoryEntry(
                            memoryId = cursor.getLong(cursor.getColumnIndexOrThrow(COLUMN_ID)),
                            text = cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_TEXT)),
                            createdAtEpochMillis = cursor.getLong(
                                cursor.getColumnIndexOrThrow(COLUMN_CREATED_AT),
                            ),
                            provenance = cursor.getString(
                                cursor.getColumnIndexOrThrow(COLUMN_PROVENANCE),
                            ),
                        ),
                    )
                }
            }
        }
        return PhoneMemoryList(
            status = PHONE_MEMORY_STATUS_AVAILABLE,
            count = total,
            truncated = total > entries.size,
            entries = entries,
        )
    }

    override suspend fun forget(memoryId: Long): PhoneMemoryDeleted {
        require(memoryId > 0) { "memory ID must be positive" }
        val database = helper.writableDatabase
        database.beginTransaction()
        return try {
            check(database.readMemory(memoryId) != null) { "memory row does not exist" }
            val deleted = database.delete(TABLE_MEMORIES, "$COLUMN_ID = ?", arrayOf(memoryId.toString()))
            check(deleted == 1) { "memory deletion affected $deleted rows" }
            check(database.readMemory(memoryId) == null) { "memory deletion failed post-delete verification" }
            val remaining = database.memoryCount()
            database.setTransactionSuccessful()
            PhoneMemoryDeleted(memoryId = memoryId, deletedCount = deleted, remainingCount = remaining)
        } finally {
            database.endTransaction()
        }
    }

    override suspend fun update(memoryId: Long, text: String, provenance: String): PhoneMemoryUpdated {
        require(memoryId > 0) { "memory ID must be positive" }
        require(text.matchesMemoryTextContract()) { "memory text does not match the local contract" }
        require(provenance.matchesMemoryProvenanceContract()) {
            "memory provenance does not match the local contract"
        }
        val database = helper.writableDatabase
        database.beginTransaction()
        return try {
            val existing = database.readMemory(memoryId)
                ?: throw IllegalStateException("memory row does not exist")
            val values = ContentValues().apply {
                put(COLUMN_TEXT, text)
                put(COLUMN_PROVENANCE, provenance)
            }
            val updated = database.update(TABLE_MEMORIES, values, "$COLUMN_ID = ?", arrayOf(memoryId.toString()))
            check(updated == 1) { "memory update affected $updated rows" }
            val stored = database.readMemory(memoryId)
                ?: throw IllegalStateException("updated memory could not be re-read")
            check(
                stored.text == text &&
                    stored.provenance == provenance &&
                    stored.createdAtEpochMillis == existing.createdAtEpochMillis,
            ) {
                "updated memory failed post-write verification"
            }
            database.setTransactionSuccessful()
            PhoneMemoryUpdated(
                memoryId = stored.memoryId,
                text = stored.text,
                createdAtEpochMillis = stored.createdAtEpochMillis,
                provenance = stored.provenance,
            )
        } finally {
            database.endTransaction()
        }
    }

    override suspend fun forgetAll(): PhoneMemoryForgotten {
        val database = helper.writableDatabase
        database.beginTransaction()
        return try {
            val deleted = database.memoryCount()
            database.delete(TABLE_MEMORIES, null, null)
            val remaining = database.memoryCount()
            check(remaining == 0) { "memory deletion failed post-delete verification" }
            database.setTransactionSuccessful()
            PhoneMemoryForgotten(deletedCount = deleted, remainingCount = remaining)
        } finally {
            database.endTransaction()
        }
    }

    override fun close() = helper.close()

    private fun SQLiteDatabase.readMemory(memoryId: Long): PhoneMemoryRemembered? = query(
        TABLE_MEMORIES,
        arrayOf(COLUMN_ID, COLUMN_TEXT, COLUMN_CREATED_AT, COLUMN_PROVENANCE),
        "$COLUMN_ID = ?",
        arrayOf(memoryId.toString()),
        null,
        null,
        null,
        "1",
    ).use { cursor ->
        if (!cursor.moveToFirst()) return@use null
        PhoneMemoryRemembered(
            memoryId = cursor.getLong(cursor.getColumnIndexOrThrow(COLUMN_ID)),
            text = cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_TEXT)),
            createdAtEpochMillis = cursor.getLong(cursor.getColumnIndexOrThrow(COLUMN_CREATED_AT)),
            provenance = cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_PROVENANCE)),
        )
    }

    private fun SQLiteDatabase.memoryCount(): Int = rawQuery(
        "SELECT COUNT(*) FROM $TABLE_MEMORIES",
        null,
    ).use { cursor ->
        check(cursor.moveToFirst()) { "memory count query returned no rows" }
        cursor.getInt(0).coerceAtMost(MAX_PHONE_MEMORY_ROWS)
    }

    private fun SQLiteDatabase.trimToNewestRows() {
        query(
            TABLE_MEMORIES,
            arrayOf(COLUMN_ID),
            null,
            null,
            null,
            null,
            "$COLUMN_CREATED_AT DESC, $COLUMN_ID DESC",
        ).use { cursor ->
            var index = 0
            while (cursor.moveToNext()) {
                if (index >= MAX_PHONE_MEMORY_ROWS) {
                    delete(
                        TABLE_MEMORIES,
                        "$COLUMN_ID = ?",
                        arrayOf(cursor.getLong(cursor.getColumnIndexOrThrow(COLUMN_ID)).toString()),
                    )
                }
                index += 1
            }
        }
    }

    private class MemoryDatabaseHelper(context: Context) : SQLiteOpenHelper(
        context,
        DATABASE_NAME,
        null,
        DATABASE_VERSION,
    ) {
        override fun onCreate(database: SQLiteDatabase) {
            database.execSQL(
                "CREATE TABLE $TABLE_MEMORIES (" +
                    "$COLUMN_ID INTEGER PRIMARY KEY AUTOINCREMENT, " +
                    "$COLUMN_TEXT TEXT NOT NULL, " +
                    "$COLUMN_PROVENANCE TEXT NOT NULL, " +
                    "$COLUMN_CREATED_AT INTEGER NOT NULL)",
            )
        }

        override fun onUpgrade(database: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            error("No memory database migration exists from $oldVersion to $newVersion")
        }
    }

    private companion object {
        const val DATABASE_NAME = "goffy_memories.db"
        const val DATABASE_VERSION = 1
        const val TABLE_MEMORIES = "memories"
        const val COLUMN_ID = "id"
        const val COLUMN_TEXT = "text"
        const val COLUMN_PROVENANCE = "provenance"
        const val COLUMN_CREATED_AT = "created_at_epoch_millis"
    }
}
