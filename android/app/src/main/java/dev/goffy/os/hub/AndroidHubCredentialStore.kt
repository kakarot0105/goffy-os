package dev.goffy.os.hub

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

internal interface CredentialCipher {
    fun seal(plaintext: ByteArray): ByteArray

    fun open(ciphertext: ByteArray): ByteArray

    fun deleteKey()
}

class AndroidHubCredentialStore internal constructor(
    context: Context,
    private val allowInsecureLoopback: Boolean,
    private val cipher: CredentialCipher = AndroidKeystoreCredentialCipher(),
    private val json: Json = strictJson(),
) : HubCredentialStore {
    private val credentialFile = AtomicFile(
        File(context.noBackupFilesDir, CREDENTIAL_FILE_NAME),
    )

    @Synchronized
    override fun load(): HubCredentialLoadResult {
        if (!credentialFile.baseFile.exists()) return HubCredentialLoadResult.Empty
        return try {
            val sealed = credentialFile.openRead().use(::readBounded)
            val plaintext = cipher.open(sealed)
            if (plaintext.size > MAX_PLAINTEXT_BYTES) throw IllegalArgumentException("record too large")
            val value = json.parseToJsonElement(plaintext.toString(Charsets.UTF_8)).jsonObject
            val schemaVersion = value.requiredInt("schemaVersion")
            value.requireExactKeys(recordKeysFor(schemaVersion))
            val wire = StoredCredentialWire(
                schemaVersion = schemaVersion,
                endpoint = value.requiredString("endpoint"),
                credentialId = value.requiredString("credentialId"),
                deviceId = value.requiredString("deviceId"),
                accessToken = value.requiredString("accessToken"),
                createdAt = value.requiredString("createdAt"),
                tokenIssuedAt = if (schemaVersion == SCHEMA_VERSION) {
                    value.requiredString("tokenIssuedAt")
                } else {
                    value.requiredString("createdAt")
                },
                hubIdentity = value.requiredObject("hubIdentity"),
            )
            if (wire.schemaVersion !in SUPPORTED_SCHEMA_VERSIONS) {
                throw IllegalArgumentException("schema mismatch")
            }
            val identity = wire.hubIdentity
            identity.requireExactKeys(HUB_IDENTITY_KEYS)
            if (
                identity.requiredString("schemaVersion") != HubIdentityPin.SCHEMA_VERSION ||
                identity.requiredString("verifiedBy") != HubIdentityPin.VERIFIED_BY ||
                identity.requiredBoolean("trustedLanSupported")
            ) {
                throw IllegalArgumentException("Hub identity is not trusted for local pairing")
            }
            val credential = StoredHubCredential.create(
                endpoint = wire.endpoint,
                credentialId = java.util.UUID.fromString(wire.credentialId),
                deviceId = wire.deviceId,
                accessToken = wire.accessToken,
                createdAt = java.time.Instant.parse(wire.createdAt),
                tokenIssuedAt = java.time.Instant.parse(wire.tokenIssuedAt),
                hubIdentity = HubIdentityPin.create(
                    hubId = java.util.UUID.fromString(identity.requiredString("hubId")),
                    fingerprint = identity.requiredString("fingerprint"),
                    createdAt = java.time.Instant.parse(identity.requiredString("createdAt")),
                ),
                allowInsecureLoopback = allowInsecureLoopback,
            )
            HubCredentialLoadResult.Loaded(credential)
        } catch (_: Exception) {
            credentialFile.delete()
            runCatching(cipher::deleteKey)
            HubCredentialLoadResult.Corrupt
        }
    }

    @Synchronized
    override fun save(credential: StoredHubCredential): StoredHubCredential {
        val plaintext = buildJsonObject {
            put("schemaVersion", SCHEMA_VERSION)
            put("endpoint", credential.endpoint)
            put("credentialId", credential.credentialId.toString())
            put("deviceId", credential.deviceId)
            put("accessToken", credential.accessToken)
            put("createdAt", credential.createdAt.toString())
            put("tokenIssuedAt", credential.tokenIssuedAt.toString())
            put("hubIdentity", buildJsonObject {
                put("schemaVersion", HubIdentityPin.SCHEMA_VERSION)
                put("hubId", credential.hubIdentity.hubId.toString())
                put("fingerprint", credential.hubIdentity.fingerprint)
                put("createdAt", credential.hubIdentity.createdAt.toString())
                put("verifiedBy", HubIdentityPin.VERIFIED_BY)
                put("trustedLanSupported", false)
            })
        }.toString().toByteArray(Charsets.UTF_8)
        if (plaintext.size > MAX_PLAINTEXT_BYTES) {
            throw HubCredentialStoreException("Hub credential record is too large.")
        }
        val sealed = try {
            cipher.seal(plaintext)
        } catch (error: Exception) {
            throw HubCredentialStoreException("Hub credential encryption failed.", error)
        }
        if (sealed.size !in 1..MAX_SEALED_BYTES) {
            throw HubCredentialStoreException("Encrypted Hub credential record is invalid.")
        }

        var output: FileOutputStream? = null
        try {
            output = credentialFile.startWrite()
            output.write(sealed)
            credentialFile.finishWrite(output)
            output = null
        } catch (error: Exception) {
            output?.let(credentialFile::failWrite)
            throw HubCredentialStoreException("Hub credential persistence failed.", error)
        }

        val verified = load()
        if (verified !is HubCredentialLoadResult.Loaded ||
            !verified.credential.sameAuthority(credential)
        ) {
            credentialFile.delete()
            throw HubCredentialStoreException("Hub credential persistence could not be verified.")
        }
        return verified.credential
    }

    @Synchronized
    override fun clear() {
        credentialFile.delete()
        if (credentialFile.baseFile.exists()) {
            throw HubCredentialStoreException("Local Hub credential deletion could not be verified.")
        }
        try {
            cipher.deleteKey()
        } catch (error: Exception) {
            throw HubCredentialStoreException(
                "Local Hub credential was removed, but key cleanup could not be verified.",
                error,
            )
        }
    }

    private fun readBounded(input: java.io.InputStream): ByteArray {
        val output = ByteArrayOutputStream()
        val buffer = ByteArray(1_024)
        var total = 0
        while (true) {
            val read = input.read(buffer)
            if (read == -1) break
            total += read
            if (total > MAX_SEALED_BYTES) throw IllegalArgumentException("record too large")
            output.write(buffer, 0, read)
        }
        return output.toByteArray()
    }

    private class StoredCredentialWire(
        val schemaVersion: Int,
        val endpoint: String,
        val credentialId: String,
        val deviceId: String,
        val accessToken: String,
        val createdAt: String,
        val tokenIssuedAt: String,
        val hubIdentity: JsonObject,
    ) {
        override fun toString(): String =
            "StoredCredentialWire(schemaVersion=$schemaVersion, endpoint=$endpoint, " +
                "credentialId=$credentialId, deviceId=$deviceId, accessToken=REDACTED, " +
                "createdAt=$createdAt, tokenIssuedAt=$tokenIssuedAt, hubIdentity=$hubIdentity)"
    }

    private companion object {
        const val CREDENTIAL_FILE_NAME = "paired-hub-credential.v1"
        const val SCHEMA_VERSION = 3
        const val LEGACY_SCHEMA_VERSION = 2
        const val MAX_PLAINTEXT_BYTES = 8_192
        const val MAX_SEALED_BYTES = 12_288
        val RECORD_KEYS_V2 = setOf(
            "schemaVersion",
            "endpoint",
            "credentialId",
            "deviceId",
            "accessToken",
            "createdAt",
            "hubIdentity",
        )
        val RECORD_KEYS_V3 = RECORD_KEYS_V2 + "tokenIssuedAt"
        val SUPPORTED_SCHEMA_VERSIONS = setOf(LEGACY_SCHEMA_VERSION, SCHEMA_VERSION)
        val HUB_IDENTITY_KEYS = setOf(
            "schemaVersion",
            "hubId",
            "fingerprint",
            "createdAt",
            "verifiedBy",
            "trustedLanSupported",
        )

        fun strictJson() = Json {
            ignoreUnknownKeys = false
            isLenient = false
            explicitNulls = false
        }

        fun JsonObject.requireExactKeys(expected: Set<String>) {
            if (keys != expected) throw SerializationException("unexpected JSON fields")
        }

        fun recordKeysFor(schemaVersion: Int): Set<String> = when (schemaVersion) {
            LEGACY_SCHEMA_VERSION -> RECORD_KEYS_V2
            SCHEMA_VERSION -> RECORD_KEYS_V3
            else -> throw SerializationException("unsupported credential schema")
        }

        fun JsonObject.requiredString(name: String): String {
            val primitive = get(name) as? JsonPrimitive
                ?: throw SerializationException("missing JSON string")
            if (!primitive.isString) throw SerializationException("JSON value must be a string")
            return primitive.content
        }

        fun JsonObject.requiredInt(name: String): Int {
            val primitive = get(name) as? JsonPrimitive
                ?: throw SerializationException("missing JSON number")
            if (primitive.isString) throw SerializationException("JSON value must be a number")
            return primitive.content.toIntOrNull()
                ?: throw SerializationException("JSON number is invalid")
        }

        fun JsonObject.requiredBoolean(name: String): Boolean {
            val primitive = get(name) as? JsonPrimitive
                ?: throw SerializationException("missing JSON Boolean")
            if (primitive.isString || primitive.content !in setOf("true", "false")) {
                throw SerializationException("JSON value must be a Boolean")
            }
            return primitive.content == "true"
        }

        fun JsonObject.requiredObject(name: String): JsonObject =
            get(name) as? JsonObject ?: throw SerializationException("missing JSON object")
    }
}

internal class AndroidKeystoreCredentialCipher : CredentialCipher {
    override fun seal(plaintext: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        cipher.updateAAD(ASSOCIATED_DATA)
        val encrypted = cipher.doFinal(plaintext)
        val iv = cipher.iv
        require(iv.size == GCM_IV_BYTES) { "unexpected GCM IV size" }
        return MAGIC + byteArrayOf(iv.size.toByte()) + iv + encrypted
    }

    override fun open(ciphertext: ByteArray): ByteArray {
        require(ciphertext.size > MAGIC.size + 1 + GCM_IV_BYTES + GCM_TAG_BYTES) {
            "encrypted credential is too short"
        }
        require(ciphertext.copyOfRange(0, MAGIC.size).contentEquals(MAGIC)) {
            "encrypted credential version is invalid"
        }
        val ivLength = ciphertext[MAGIC.size].toInt() and 0xFF
        require(ivLength == GCM_IV_BYTES) { "encrypted credential IV is invalid" }
        val ivStart = MAGIC.size + 1
        val payloadStart = ivStart + ivLength
        val iv = ciphertext.copyOfRange(ivStart, payloadStart)
        val payload = ciphertext.copyOfRange(payloadStart, ciphertext.size)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, loadKey(), GCMParameterSpec(GCM_TAG_BITS, iv))
        cipher.updateAAD(ASSOCIATED_DATA)
        return cipher.doFinal(payload)
    }

    override fun deleteKey() {
        val keyStore = loadedKeyStore()
        if (keyStore.containsAlias(KEY_ALIAS)) keyStore.deleteEntry(KEY_ALIAS)
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = loadedKeyStore()
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return generator.generateKey()
    }

    private fun loadKey(): SecretKey = loadedKeyStore().getKey(KEY_ALIAS, null) as? SecretKey
        ?: throw IllegalStateException("Android Keystore credential key is unavailable")

    private fun loadedKeyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply {
        load(null)
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "dev.goffy.os.paired-hub.v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val GCM_IV_BYTES = 12
        const val GCM_TAG_BYTES = 16
        const val GCM_TAG_BITS = GCM_TAG_BYTES * 8
        val MAGIC = byteArrayOf(0x47, 0x4F, 0x46, 0x31)
        val ASSOCIATED_DATA = "GOFFY paired Hub credential v1".toByteArray(Charsets.UTF_8)
    }
}
