package dev.goffy.os.localmodel

import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull

fun interface LocalModelTextGenerator {
    suspend fun generate(prompt: String, policy: LocalModelRuntimePolicy): String
}

class GatedLocalModelRuntimeAdapter(
    private val policyProvider: () -> LocalModelRuntimePolicy,
    private val modelFile: File,
    private val modelRoot: File,
    private val textGenerator: LocalModelTextGenerator,
) {
    constructor(
        policy: LocalModelRuntimePolicy = LocalModelRuntimePolicy(),
        modelFile: File,
        modelRoot: File,
        textGenerator: LocalModelTextGenerator,
    ) : this(
        policyProvider = { policy },
        modelFile = modelFile,
        modelRoot = modelRoot,
        textGenerator = textGenerator,
    )

    suspend fun observeUnsupportedCommand(command: String): LocalModelIntentObservation {
        val policy = policyProvider()
        val disabled = disabledObservationIfNeeded(policy)
        if (disabled != null) return disabled

        val normalizedCommand = command.trim()
        validateRuntimeInput(normalizedCommand, policy)?.let { return it }

        val prompt = localModelRoutingPrompt(normalizedCommand)
        if (!isSafeLocalModelPrompt(prompt, policy)) {
            return LocalModelIntentObservation.Rejected(
                "Generated local model prompt is outside safety bounds.",
            )
        }

        val rawOutput = try {
            withTimeoutOrNull(policy.generationTimeoutMillis) {
                textGenerator.generate(prompt, policy)
            } ?: return LocalModelIntentObservation.Rejected(
                "Local model generation timed out before producing a safe routing observation.",
            )
        } catch (_: LocalModelOutputLimitExceeded) {
            return LocalModelIntentObservation.Rejected(
                "Model output exceeded the local routing output budget.",
            )
        } catch (cancellation: CancellationException) {
            throw cancellation
        } catch (_: Exception) {
            return LocalModelIntentObservation.Rejected(
                "Local model runtime failed without producing a safe routing observation.",
            )
        }
        return evaluateLocalModelRoutingOutput(
            command = normalizedCommand,
            output = rawOutput,
            policy = policy,
        )
    }

    private fun validateRuntimeInput(
        command: String,
        policy: LocalModelRuntimePolicy,
    ): LocalModelIntentObservation.Rejected? {
        if (!isSafeLocalModelPrompt(command, policy)) {
            return LocalModelIntentObservation.Rejected(
                "Command is outside local model prompt safety bounds.",
            )
        }
        if (!isSafeLocalModelCandidateText(command)) {
            return LocalModelIntentObservation.Rejected(
                "Normalized command is outside local candidate quality bounds.",
            )
        }
        if (!modelRoot.isDirectory) {
            return LocalModelIntentObservation.Rejected(
                "Approved local model directory is unavailable.",
            )
        }
        if (!modelFile.isUnder(modelRoot)) {
            return LocalModelIntentObservation.Rejected(
                "Local model file must stay under the approved app-owned model directory.",
            )
        }
        if (!modelFile.name.endsWith(".litertlm")) {
            return LocalModelIntentObservation.Rejected("Local model file must be a .litertlm file.")
        }
        if (!modelFile.isFile) {
            return LocalModelIntentObservation.Rejected("Local model file is unavailable.")
        }
        if (modelFile.length() !in 1L..policy.maxModelFileBytes) {
            return LocalModelIntentObservation.Rejected(
                "Local model file exceeds the GOFFY LITE size budget.",
            )
        }
        return null
    }
}

fun localModelRoutingPrompt(command: String): String =
    "Return exactly JSON: {\"route\":\"PHONE\",\"confidence\":0.70}. " +
        "Allowed route values: PHONE, MAC, CLOUD. No markdown. Command: $command"

private fun disabledObservationIfNeeded(
    policy: LocalModelRuntimePolicy,
): LocalModelIntentObservation.Disabled? =
    if (policy.enabled) {
        null
    } else {
        LocalModelIntentObservation.Disabled(
            "Local model fallback is disabled; deterministic routing remains authoritative.",
        )
    }

private fun File.isUnder(root: File): Boolean {
    val canonicalRoot = root.canonicalFile.path.trimEnd(File.separatorChar)
    val canonicalPath = canonicalFile.path
    return canonicalPath.startsWith("$canonicalRoot${File.separator}")
}

internal class LocalModelOutputLimitExceeded : RuntimeException()
