package dev.goffy.os.phone

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.matchesNoteTextContract

class AndroidSqliteNoteStore(
    context: Context,
    private val nowMillis: () -> Long = System::currentTimeMillis,
) : NoteStore {
    private val helper = NoteDatabaseHelper(context.applicationContext)

    override suspend fun create(text: String): PhoneNoteCreated {
        require(text.matchesNoteTextContract()) { "note text does not match the local contract" }
        val createdAt = nowMillis()
        require(createdAt > 0) { "note timestamp must be positive" }
        val database = helper.writableDatabase
        database.beginTransaction()
        return try {
            val values = ContentValues().apply {
                put(COLUMN_TEXT, text)
                put(COLUMN_CREATED_AT, createdAt)
            }
            val noteId = database.insertOrThrow(TABLE_NOTES, null, values)
            val stored = database.readNote(noteId)
                ?: throw IllegalStateException("created note could not be re-read")
            check(stored.text == text && stored.createdAtEpochMillis == createdAt) {
                "created note failed post-write verification"
            }
            database.setTransactionSuccessful()
            stored
        } finally {
            database.endTransaction()
        }
    }

    override fun close() = helper.close()

    private fun SQLiteDatabase.readNote(noteId: Long): PhoneNoteCreated? = query(
        TABLE_NOTES,
        arrayOf(COLUMN_ID, COLUMN_TEXT, COLUMN_CREATED_AT),
        "$COLUMN_ID = ?",
        arrayOf(noteId.toString()),
        null,
        null,
        null,
        "1",
    ).use { cursor ->
        if (!cursor.moveToFirst()) return@use null
        PhoneNoteCreated(
            noteId = cursor.getLong(cursor.getColumnIndexOrThrow(COLUMN_ID)),
            text = cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_TEXT)),
            createdAtEpochMillis = cursor.getLong(cursor.getColumnIndexOrThrow(COLUMN_CREATED_AT)),
        )
    }

    private class NoteDatabaseHelper(context: Context) : SQLiteOpenHelper(
        context,
        DATABASE_NAME,
        null,
        DATABASE_VERSION,
    ) {
        override fun onCreate(database: SQLiteDatabase) {
            database.execSQL(
                "CREATE TABLE $TABLE_NOTES (" +
                    "$COLUMN_ID INTEGER PRIMARY KEY AUTOINCREMENT, " +
                    "$COLUMN_TEXT TEXT NOT NULL, " +
                    "$COLUMN_CREATED_AT INTEGER NOT NULL)",
            )
        }

        override fun onUpgrade(database: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
            error("No note database migration exists from $oldVersion to $newVersion")
        }
    }

    private companion object {
        const val DATABASE_NAME = "goffy_notes.db"
        const val DATABASE_VERSION = 1
        const val TABLE_NOTES = "notes"
        const val COLUMN_ID = "id"
        const val COLUMN_TEXT = "text"
        const val COLUMN_CREATED_AT = "created_at_epoch_millis"
    }
}
