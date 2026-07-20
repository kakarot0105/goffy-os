package dev.goffy.os.qr

import android.content.Context
import android.os.Handler
import android.os.Looper
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
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executor
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

@Composable
fun PairingQrScanner(
    onPayloadScanned: (String) -> Unit,
    onCameraFailure: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val currentOnPayloadScanned = rememberUpdatedState(onPayloadScanned)
    val currentOnCameraFailure = rememberUpdatedState(onCameraFailure)
    val mainExecutor = remember { MainThreadExecutor() }
    val analysisExecutor = remember { Executors.newSingleThreadExecutor() }
    val delivered = remember { AtomicBoolean(false) }
    val scanner = remember {
        val options = BarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .build()
        BarcodeScanning.getClient(options)
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
                bindScannerCamera(
                    context = context,
                    lifecycleOwner = lifecycleOwner,
                    previewView = this,
                    scanner = scanner,
                    analysisExecutor = analysisExecutor,
                    delivered = delivered,
                    mainExecutor = mainExecutor,
                    onPayloadScanned = { currentOnPayloadScanned.value(it) },
                    onCameraFailure = { currentOnCameraFailure.value() },
                )
            }
        },
    )

    DisposableEffect(Unit) {
        onDispose {
            delivered.set(true)
            releaseCamera(context, scanner, analysisExecutor, mainExecutor)
        }
    }
}

private fun bindScannerCamera(
    context: Context,
    lifecycleOwner: LifecycleOwner,
    previewView: PreviewView,
    scanner: BarcodeScanner,
    analysisExecutor: ExecutorService,
    delivered: AtomicBoolean,
    mainExecutor: Executor,
    onPayloadScanned: (String) -> Unit,
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
                        .setTargetResolution(Size(QR_ANALYSIS_WIDTH, QR_ANALYSIS_HEIGHT))
                        .build()
                        .also {
                            it.setAnalyzer(analysisExecutor) { imageProxy ->
                                analyzeQrFrame(
                                    imageProxy = imageProxy,
                                    scanner = scanner,
                                    delivered = delivered,
                                    mainExecutor = mainExecutor,
                                    onPayloadScanned = onPayloadScanned,
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
private fun analyzeQrFrame(
    imageProxy: ImageProxy,
    scanner: BarcodeScanner,
    delivered: AtomicBoolean,
    mainExecutor: Executor,
    onPayloadScanned: (String) -> Unit,
) {
    if (delivered.get()) {
        imageProxy.close()
        return
    }
    val mediaImage = imageProxy.image
    if (mediaImage == null) {
        imageProxy.close()
        return
    }

    try {
        val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
        scanner.process(image)
            .addOnSuccessListener { barcodes ->
                val payload = barcodes.firstNotNullOfOrNull { barcode ->
                    barcode.rawValue
                        ?.takeIf { barcode.format == Barcode.FORMAT_QR_CODE }
                        ?.takeIf { it.isNotBlank() }
                }
                if (payload != null && delivered.compareAndSet(false, true)) {
                    mainExecutor.execute { onPayloadScanned(payload) }
                }
            }
            .addOnCompleteListener { imageProxy.close() }
    } catch (_: RuntimeException) {
        imageProxy.close()
    }
}

private fun releaseCamera(
    context: Context,
    scanner: BarcodeScanner,
    analysisExecutor: ExecutorService,
    mainExecutor: Executor,
) {
    runCatching { scanner.close() }
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

private const val QR_ANALYSIS_WIDTH = 1280
private const val QR_ANALYSIS_HEIGHT = 720
