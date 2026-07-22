package dev.goffy.os.phone

import android.os.Build
import dev.goffy.os.protocol.PHONE_MEMORY_PROVENANCE_USER_APPROVED
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.TIRAMISU])
class AndroidSqliteMemoryStoreTest {
    @Test
    fun updatesAndDeletesOneExactMemoryWithPostconditionChecks() = runTest {
        val application = RuntimeEnvironment.getApplication()
        application.deleteDatabase("goffy_memories.db")
        var now = 1_720_000_000_000L
        val store = AndroidSqliteMemoryStore(application) { now++ }

        try {
            val first = store.remember("first memory", PHONE_MEMORY_PROVENANCE_USER_APPROVED)
            store.remember("second memory", PHONE_MEMORY_PROVENANCE_USER_APPROVED)

            val updated = store.update(
                first.memoryId,
                "updated first memory",
                PHONE_MEMORY_PROVENANCE_USER_APPROVED,
            )
            assertEquals(first.memoryId, updated.memoryId)
            assertEquals(first.createdAtEpochMillis, updated.createdAtEpochMillis)
            assertEquals("updated first memory", updated.text)

            val deleted = store.forget(first.memoryId)
            assertEquals(first.memoryId, deleted.memoryId)
            assertEquals(1, deleted.deletedCount)
            assertEquals(1, deleted.remainingCount)

            val listed = store.list(20)
            assertEquals(1, listed.count)
            assertTrue(listed.entries.none { it.memoryId == first.memoryId })
            assertEquals("second memory", listed.entries.single().text)
        } finally {
            store.close()
            application.deleteDatabase("goffy_memories.db")
        }
    }
}
