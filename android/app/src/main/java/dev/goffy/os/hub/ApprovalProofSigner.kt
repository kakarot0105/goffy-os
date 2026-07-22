package dev.goffy.os.hub

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64

data class ApprovalSigningPublicKey(
    val algorithm: String,
    val spkiDerBase64: String,
    val spkiSha256: String,
)

data class ApprovalProof(
    val algorithm: String,
    val publicKeySha256: String,
    val signatureBase64: String,
)

interface ApprovalProofSigner {
    fun publicKey(): ApprovalSigningPublicKey

    fun sign(payload: ByteArray): ApprovalProof

    fun deleteKey()
}

class AndroidKeystoreApprovalProofSigner : ApprovalProofSigner {
    override fun publicKey(): ApprovalSigningPublicKey {
        val publicKey = getOrCreateKeyPair().certificate.publicKey.encoded
            ?: throw IllegalStateException("approval public key is unavailable")
        return ApprovalSigningPublicKey(
            algorithm = ALGORITHM,
            spkiDerBase64 = base64(publicKey),
            spkiSha256 = sha256Hex(publicKey),
        )
    }

    override fun sign(payload: ByteArray): ApprovalProof {
        val privateKey = loadPrivateKey()
        val signature = Signature.getInstance(SIGNATURE_ALGORITHM)
        signature.initSign(privateKey)
        signature.update(payload)
        val publicKey = publicKey()
        return ApprovalProof(
            algorithm = ALGORITHM,
            publicKeySha256 = publicKey.spkiSha256,
            signatureBase64 = base64(signature.sign()),
        )
    }

    override fun deleteKey() {
        val keyStore = loadedKeyStore()
        if (keyStore.containsAlias(KEY_ALIAS)) keyStore.deleteEntry(KEY_ALIAS)
    }

    private fun getOrCreateKeyPair(): KeyStore.PrivateKeyEntry {
        val keyStore = loadedKeyStore()
        val existing = keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.PrivateKeyEntry
        if (existing != null) return existing
        val generator = KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_EC,
            ANDROID_KEYSTORE,
        )
        generator.initialize(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .build(),
        )
        generator.generateKeyPair()
        return keyStore.getEntry(KEY_ALIAS, null) as? KeyStore.PrivateKeyEntry
            ?: throw IllegalStateException("approval key generation failed")
    }

    private fun loadPrivateKey(): PrivateKey {
        val entry = loadedKeyStore().getEntry(KEY_ALIAS, null) as? KeyStore.PrivateKeyEntry
            ?: throw IllegalStateException("approval signing key is unavailable")
        return entry.privateKey
    }

    private fun loadedKeyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply {
        load(null)
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "dev.goffy.os.approval-proof.v1"
        const val ALGORITHM = "ECDSA_P256_SHA256"
        const val SIGNATURE_ALGORITHM = "SHA256withECDSA"
    }
}

internal fun sha256Hex(value: ByteArray): String =
    MessageDigest.getInstance("SHA-256")
        .digest(value)
        .joinToString(separator = "") { byte -> "%02x".format(byte.toInt() and 0xff) }

internal fun base64(value: ByteArray): String =
    Base64.getEncoder().encodeToString(value)
