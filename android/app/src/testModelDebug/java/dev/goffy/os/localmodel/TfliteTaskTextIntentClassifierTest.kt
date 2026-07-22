package dev.goffy.os.localmodel

import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class TfliteTaskTextIntentClassifierTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun acceptsOnlyAppOwnedTfliteModelAndReturnsTrimmedCommand() {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot, "router.tflite")

        val normalizedCommand = validateTfliteTaskTextClassifierInput(
            command = "  show my battery status  ",
            modelRoot = modelRoot,
            modelFile = modelFile,
        )

        assertEquals("show my battery status", normalizedCommand)
    }

    @Test
    fun rejectsModelOutsideApprovedRoot() {
        val modelRoot = temporaryFolder.newFolder("models")
        val outsideModel = temporaryFolder.newFile("router.tflite")

        val error = assertThrows(SecurityException::class.java) {
            validateTfliteTaskTextClassifierInput(
                command = "show my battery status",
                modelRoot = modelRoot,
                modelFile = outsideModel,
            )
        }

        assertEquals(
            "TFLite classifier model file must stay under app-owned storage.",
            error.message,
        )
    }

    @Test
    fun rejectsMissingApprovedRoot() {
        val modelRoot = File(temporaryFolder.root, "missing")
        val modelFile = File(modelRoot, "router.tflite")

        val error = assertThrows(IOException::class.java) {
            validateTfliteTaskTextClassifierInput(
                command = "show my battery status",
                modelRoot = modelRoot,
                modelFile = modelFile,
            )
        }

        assertEquals("Approved TFLite classifier model directory is unavailable.", error.message)
    }

    @Test
    fun rejectsWrongExtension() {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = writeModel(modelRoot, "router.bin")

        val error = assertThrows(IllegalArgumentException::class.java) {
            validateTfliteTaskTextClassifierInput(
                command = "show my battery status",
                modelRoot = modelRoot,
                modelFile = modelFile,
            )
        }

        assertEquals("TFLite classifier model file must be a .tflite file.", error.message)
    }

    @Test
    fun rejectsOversizedModel() {
        val modelRoot = temporaryFolder.newFolder("models")
        val modelFile = File(modelRoot, "router.tflite")
        RandomAccessFile(modelFile, "rw").use { file ->
            file.setLength(8L * 1024L * 1024L + 1L)
        }

        val error = assertThrows(IllegalArgumentException::class.java) {
            validateTfliteTaskTextClassifierInput(
                command = "show my battery status",
                modelRoot = modelRoot,
                modelFile = modelFile,
            )
        }

        assertEquals("TFLite classifier model exceeds the GOFFY tiny-model budget.", error.message)
    }

    @Test
    fun mapsAllowedHighConfidenceLabelToCandidate() {
        val observation = tfliteTaskTextCategoriesToObservation(
            normalizedCommand = "show my battery status",
            categories = listOf(
                TfliteTaskTextCategory("phone", 0.91f),
                TfliteTaskTextCategory("mac", 0.08f),
            ),
        )

        assertTrue(observation is LocalModelIntentObservation.Candidate)
        val candidate = (observation as LocalModelIntentObservation.Candidate).candidate
        assertEquals("PHONE", candidate.intentLabel)
        assertEquals(0.91f, candidate.confidence)
    }

    @Test
    fun rejectsUnsupportedTopLabel() {
        val observation = tfliteTaskTextCategoriesToObservation(
            normalizedCommand = "open my settings",
            categories = listOf(TfliteTaskTextCategory("SETTINGS", 0.91f)),
        )

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "TFLite Task Text classifier top label is not a GOFFY route.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun rejectsLowConfidenceRoute() {
        val observation = tfliteTaskTextCategoriesToObservation(
            normalizedCommand = "show my battery status",
            categories = listOf(TfliteTaskTextCategory("PHONE", 0.69f)),
        )

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "TFLite Task Text classifier confidence is below the routing threshold.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    @Test
    fun rejectsAmbiguousTopScore() {
        val observation = tfliteTaskTextCategoriesToObservation(
            normalizedCommand = "show my battery status",
            categories = listOf(
                TfliteTaskTextCategory("PHONE", 0.91f),
                TfliteTaskTextCategory("MAC", 0.91f),
            ),
        )

        assertTrue(observation is LocalModelIntentObservation.Rejected)
        assertEquals(
            "TFLite Task Text classifier returned an ambiguous top score.",
            (observation as LocalModelIntentObservation.Rejected).reason,
        )
    }

    private fun writeModel(root: File, name: String): File =
        File(root, name).also { model ->
            model.writeBytes(byteArrayOf(1, 2, 3))
        }
}
