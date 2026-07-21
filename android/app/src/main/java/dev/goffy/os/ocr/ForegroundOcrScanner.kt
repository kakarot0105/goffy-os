package dev.goffy.os.ocr

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Size
import android.view.ViewGroup
import androidx.annotation.OptIn
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import java.util.concurrent.Executor
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

@Composable
fun ForegroundOcrScanner(
    onTextRecognized: (String) -> Unit,
    onRecognitionFailure: () -> Unit,
    onCameraFailure: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val currentOnTextRecognized = rememberUpdatedState(onTextRecognized)
    val currentOnRecognitionFailure = rememberUpdatedState(onRecognitionFailure)
    val currentOnCameraFailure = rememberUpdatedState(onCameraFailure)
    val mainExecutor = remember { MainThreadExecutor() }
    val analysisExecutor = remember { Executors.newSingleThreadExecutor() }
    val delivered = remember { AtomicBoolean(false) }
    val failed = remember { AtomicBoolean(false) }
    val processing = remember { AtomicBoolean(false) }
    val nextAttemptAtMillis = remember { AtomicLong(0) }
    val recognizer = remember {
        TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    }

    AndroidView(
        modifier = modifier,
        factory = { context ->
            PreviewView(context).apply {
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
                implementationMode = PreviewView.ImplementationMode.COMPATIBLE
                scaleType = PreviewView.ScaleType.FILL_CENTER
                bindOcrCamera(
                    context = context,
                    lifecycleOwner = lifecycleOwner,
                    previewView = this,
                    recognizer = recognizer,
                    analysisExecutor = analysisExecutor,
                    delivered = delivered,
                    failed = failed,
                    processing = processing,
                    nextAttemptAtMillis = nextAttemptAtMillis,
                    mainExecutor = mainExecutor,
                    onTextRecognized = { currentOnTextRecognized.value(it) },
                    onRecognitionFailure = { currentOnRecognitionFailure.value() },
                    onCameraFailure = { currentOnCameraFailure.value() },
                )
            }
        },
    )

    DisposableEffect(Unit) {
        onDispose {
            delivered.set(true)
            releaseOcrCamera(context, recognizer, analysisExecutor, mainExecutor)
        }
    }
}

private fun bindOcrCamera(
    context: Context,
    lifecycleOwner: LifecycleOwner,
    previewView: PreviewView,
    recognizer: TextRecognizer,
    analysisExecutor: ExecutorService,
    delivered: AtomicBoolean,
    failed: AtomicBoolean,
    processing: AtomicBoolean,
    nextAttemptAtMillis: AtomicLong,
    mainExecutor: Executor,
    onTextRecognized: (String) -> Unit,
    onRecognitionFailure: () -> Unit,
    onCameraFailure: () -> Unit,
) {
    val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
    cameraProviderFuture.addListener(
        {
            try {
                if (!delivered.get()) {
                    val cameraProvider = cameraProviderFuture.get()
                    val preview = Preview.Builder()
                        .build()
                        .also { it.setSurfaceProvider(previewView.surfaceProvider) }
                    val analysis = ImageAnalysis.Builder()
                        .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                        .setTargetResolution(Size(OCR_ANALYSIS_WIDTH, OCR_ANALYSIS_HEIGHT))
                        .build()
                        .also {
                            it.setAnalyzer(analysisExecutor) { imageProxy ->
                                analyzeOcrFrame(
                                    imageProxy = imageProxy,
                                    recognizer = recognizer,
                                    delivered = delivered,
                                    failed = failed,
                                    processing = processing,
                                    nextAttemptAtMillis = nextAttemptAtMillis,
                                    mainExecutor = mainExecutor,
                                    onTextRecognized = onTextRecognized,
                                    onRecognitionFailure = onRecognitionFailure,
                                )
                            }
                        }

                    cameraProvider.unbindAll()
                    if (!delivered.get()) {
                        cameraProvider.bindToLifecycle(
                            lifecycleOwner,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            analysis,
                        )
                    }
                }
            } catch (_: Exception) {
                onCameraFailure()
            }
        },
        mainExecutor,
    )
}

@OptIn(ExperimentalGetImage::class)
private fun analyzeOcrFrame(
    imageProxy: ImageProxy,
    recognizer: TextRecognizer,
    delivered: AtomicBoolean,
    failed: AtomicBoolean,
    processing: AtomicBoolean,
    nextAttemptAtMillis: AtomicLong,
    mainExecutor: Executor,
    onTextRecognized: (String) -> Unit,
    onRecognitionFailure: () -> Unit,
) {
    if (delivered.get() || failed.get() || !shouldAnalyzeOcrFrame(nextAttemptAtMillis)) {
        imageProxy.close()
        return
    }
    if (!processing.compareAndSet(false, true)) {
        imageProxy.close()
        return
    }
    val mediaImage = imageProxy.image
    if (mediaImage == null) {
        processing.set(false)
        imageProxy.close()
        return
    }

    try {
        val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
        recognizer.process(image)
            .addOnSuccessListener { text ->
                val recognizedText = text.safeRecognizedText()
                if (recognizedText != null && delivered.compareAndSet(false, true)) {
                    mainExecutor.execute { onTextRecognized(recognizedText) }
                }
            }
            .addOnFailureListener {
                if (failed.compareAndSet(false, true)) {
                    mainExecutor.execute { onRecognitionFailure() }
                }
            }
            .addOnCompleteListener {
                processing.set(false)
                imageProxy.close()
            }
    } catch (_: RuntimeException) {
        processing.set(false)
        imageProxy.close()
    }
}

private fun shouldAnalyzeOcrFrame(nextAttemptAtMillis: AtomicLong): Boolean {
    val now = SystemClock.elapsedRealtime()
    while (true) {
        val next = nextAttemptAtMillis.get()
        if (now < next) return false
        if (nextAttemptAtMillis.compareAndSet(next, now + OCR_ANALYSIS_INTERVAL_MILLIS)) {
            return true
        }
    }
}

private fun Text.safeRecognizedText(): String? =
    text.trim()
        .takeIf { it.length >= MIN_RECOGNIZED_TEXT_LENGTH }

private fun releaseOcrCamera(
    context: Context,
    recognizer: TextRecognizer,
    analysisExecutor: ExecutorService,
    mainExecutor: Executor,
) {
    runCatching { recognizer.close() }
    analysisExecutor.shutdown()
    val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
    cameraProviderFuture.addListener(
        { runCatching { cameraProviderFuture.get().unbindAll() } },
        mainExecutor,
    )
}

private class MainThreadExecutor : Executor {
    private val handler = Handler(Looper.getMainLooper())

    override fun execute(command: Runnable) {
        handler.post(command)
    }
}

private const val OCR_ANALYSIS_WIDTH = 1280
private const val OCR_ANALYSIS_HEIGHT = 720
private const val OCR_ANALYSIS_INTERVAL_MILLIS = 900L
private const val MIN_RECOGNIZED_TEXT_LENGTH = 3
