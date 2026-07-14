package dev.goffy.os.hub

import android.os.Build
import java.io.File
import java.time.Instant
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [Build.VERSION_CODES.O])
class AndroidHubCredentialStoreTest {
    @Test
    fun encryptedRecordRoundTripsAcrossStoreReopenWithoutPlaintextResidue() {
        val context = RuntimeEnvironment.getApplication()
        credentialFile().delete()
        val cipher = XorCredentialCipher()
        val credential = credential()

        AndroidHubCredentialStore(context, true, cipher).save(credential)
        val diskBytes = credentialFile().readBytes()
        val reopened = AndroidHubCredentialStore(context, true, cipher).load()

        assertFalse(diskBytes.toString(Charsets.UTF_8).contains(ACCESS_TOKEN))
        assertFalse(diskBytes.toString(Charsets.UTF_8).contains(credential.endpoint))
        assertTrue(reopened is HubCredentialLoadResult.Loaded)
        assertTrue((reopened as HubCredentialLoadResult.Loaded).credential.sameAuthority(credential))
        assertFalse(reopened.toString().contains(ACCESS_TOKEN))
    }

    @Test
    fun tamperedRecordFailsClosedAndIsDeleted() {
        val context = RuntimeEnvironment.getApplication()
        credentialFile().delete()
        val cipher = XorCredentialCipher()
        AndroidHubCredentialStore(context, true, cipher).save(credential())
        credentialFile().appendBytes(byteArrayOf(0x01))
        cipher.rejectNextOpen = true

        val result = AndroidHubCredentialStore(context, true, cipher).load()

        assertEquals(HubCredentialLoadResult.Corrupt, result)
        assertFalse(credentialFile().exists())
        assertTrue(cipher.keyDeleted)
    }

    @Test
    fun forgetDeletesRecordAndKeySoRestartRestoresNothing() {
        val context = RuntimeEnvironment.getApplication()
        credentialFile().delete()
        val cipher = XorCredentialCipher()
        val store = AndroidHubCredentialStore(context, true, cipher)
        store.save(credential())

        store.clear()
        val reopened = AndroidHubCredentialStore(context, true, cipher).load()

        assertEquals(HubCredentialLoadResult.Empty, reopened)
        assertFalse(credentialFile().exists())
        assertTrue(cipher.keyDeleted)
    }

    private fun credential(): StoredHubCredential = StoredHubCredential.create(
        endpoint = "ws://127.0.0.1:8787/ws/v1",
        credentialId = UUID.fromString("22222222-2222-4222-8222-222222222222"),
        deviceId = "goffy-android-test",
        accessToken = ACCESS_TOKEN,
        createdAt = Instant.parse("2026-07-13T16:00:00Z"),
        allowInsecureLoopback = true,
    )

    private fun credentialFile(): File = File(
        RuntimeEnvironment.getApplication().noBackupFilesDir,
        "paired-hub-credential.v1",
    )

    private class XorCredentialCipher : CredentialCipher {
        var rejectNextOpen = false
        var keyDeleted = false

        override fun seal(plaintext: ByteArray): ByteArray =
            byteArrayOf(MARKER) + plaintext.map { (it.toInt() xor MASK).toByte() }.toByteArray()

        override fun open(ciphertext: ByteArray): ByteArray {
            if (rejectNextOpen) error("simulated authentication failure")
            require(ciphertext.firstOrNull() == MARKER)
            return ciphertext.drop(1).map { (it.toInt() xor MASK).toByte() }.toByteArray()
        }

        override fun deleteKey() {
            keyDeleted = true
        }

        private companion object {
            const val MARKER: Byte = 0x51
            const val MASK = 0x5A
        }
    }

    private companion object {
        const val ACCESS_TOKEN = "paired-access-token-abcdefghijklmnopqrstuvwxyz0123456789"
    }
}
