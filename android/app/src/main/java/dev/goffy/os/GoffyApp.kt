package dev.goffy.os

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dev.goffy.os.agent.TaskEventKind
import dev.goffy.os.agent.TaskPhase
import dev.goffy.os.agent.TaskTimelineEntry
import dev.goffy.os.hub.HubOperatorAuditEvent
import dev.goffy.os.localmodel.LocalModelRuntimeState
import dev.goffy.os.ocr.ForegroundOcrScanner
import dev.goffy.os.qr.ForegroundQrScanner
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.GitStatus
import dev.goffy.os.protocol.MacAppOpened
import dev.goffy.os.protocol.MacAppsList
import dev.goffy.os.protocol.MacClipboardRead
import dev.goffy.os.protocol.MacFilesLargest
import dev.goffy.os.protocol.MacFilesList
import dev.goffy.os.protocol.MacProcessesList
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PhoneFlashlightState
import dev.goffy.os.protocol.PhoneMemoryDeleted
import dev.goffy.os.protocol.PhoneMemoryForgotten
import dev.goffy.os.protocol.PhoneMemoryList
import dev.goffy.os.protocol.PhoneMemoryRemembered
import dev.goffy.os.protocol.PhoneMemoryUpdated
import dev.goffy.os.protocol.PhoneNoteCreated
import dev.goffy.os.protocol.PhoneOcrRead
import dev.goffy.os.protocol.PhoneQrRead
import dev.goffy.os.protocol.PhoneTimerDispatched
import dev.goffy.os.protocol.ToolResultContent
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

private val Void = Color(0xFF05090C)
private val Panel = Color(0xFF0B1318)
private val Line = Color(0xFF23333B)
private val Bone = Color(0xFFF1F0E8)
private val Mist = Color(0xFF94A5AC)
private val Acid = Color(0xFFB6F23A)
private val Signal = Color(0xFF41D7C7)
private val Warning = Color(0xFFFF7A59)
private val Error = Color(0xFFFF4E64)
private val AuditTimestampFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

private val GoffyColors = darkColorScheme(
    primary = Acid,
    secondary = Signal,
    background = Void,
    surface = Panel,
    onPrimary = Void,
    onBackground = Bone,
    onSurface = Bone,
)

private data class PairingScannerNotice(
    val message: String,
    val warning: Boolean,
)

private enum class CameraScanMode {
    PAIRING,
    OCR_READ,
    QR_READ,
}

private val QrReadCommand = Regex(
    pattern = "^(?:read|scan)(?: this| the| a)? qr(?: code)?[.!?]?$",
    option = RegexOption.IGNORE_CASE,
)

internal fun isForegroundQrReadCommand(command: String): Boolean =
    command.trim().matches(QrReadCommand)

private val OcrReadCommand = Regex(
    pattern = "^(?:(?:read|scan|extract)(?: this| the| a)? (?:text|ocr)|ocr this)(?: code)?[.!?]?$",
    option = RegexOption.IGNORE_CASE,
)

internal fun isForegroundOcrReadCommand(command: String): Boolean =
    command.trim().matches(OcrReadCommand)

@Composable
fun GoffyApp(
    viewModel: GoffyViewModel,
    voiceInputState: GoffyVoiceInputState = GoffyVoiceInputState(),
    onStartVoiceInput: ((String) -> Unit) -> Unit = {},
    onVoicePermissionDenied: () -> Unit = {},
    onSpeakLatest: (String) -> Unit = {},
    onOpenSystemSettings: () -> Unit = {},
    onOpenHomeSettings: () -> Unit = {},
) {
    val context = LocalContext.current
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val latestSpeakableText = state.latestSpeakableText()
    val scannerPermissionDenied = stringResource(R.string.pairing_scanner_permission_denied)
    val scannerCaptured = stringResource(R.string.pairing_scanner_captured)
    val scannerStartFailed = stringResource(R.string.pairing_scanner_start_failed)
    val qrReadPermissionDenied = stringResource(R.string.qr_read_permission_denied)
    val qrReadStartFailed = stringResource(R.string.qr_read_start_failed)
    val ocrReadPermissionDenied = stringResource(R.string.ocr_read_permission_denied)
    val ocrReadStartFailed = stringResource(R.string.ocr_read_start_failed)
    val ocrRecognitionFailed = stringResource(R.string.ocr_read_recognition_failed)
    var command by remember { mutableStateOf("") }
    var endpoint by rememberSaveable(state.hubEndpoint) { mutableStateOf(state.hubEndpoint) }
    var pairingChallenge by remember { mutableStateOf("") }
    var bearerToken by remember { mutableStateOf("") }
    var showLinkSetup by remember(state.hubConfigured) { mutableStateOf(!state.hubConfigured) }
    var showForgetConfirmation by remember { mutableStateOf(false) }
    var showRotateConfirmation by remember { mutableStateOf(false) }
    var showPairingScanner by remember { mutableStateOf(false) }
    var showQrReadScanner by remember { mutableStateOf(false) }
    var showOcrReadScanner by remember { mutableStateOf(false) }
    var pendingCameraScanMode by remember { mutableStateOf<CameraScanMode?>(null) }
    var pairingScannerNotice by remember { mutableStateOf<PairingScannerNotice?>(null) }
    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        val scanMode = pendingCameraScanMode
        pendingCameraScanMode = null
        if (granted) {
            when (scanMode) {
                CameraScanMode.PAIRING -> {
                    pairingScannerNotice = null
                    showPairingScanner = true
                }
                CameraScanMode.OCR_READ -> showOcrReadScanner = true
                CameraScanMode.QR_READ -> showQrReadScanner = true
                null -> Unit
            }
        } else {
            when (scanMode) {
                CameraScanMode.PAIRING -> {
                    pairingScannerNotice = PairingScannerNotice(
                        message = scannerPermissionDenied,
                        warning = true,
                    )
                }
                CameraScanMode.OCR_READ -> viewModel.recordForegroundOcrReadUnavailable(
                    ocrReadPermissionDenied,
                )
                CameraScanMode.QR_READ -> viewModel.recordForegroundQrScanUnavailable(
                    qrReadPermissionDenied,
                )
                null -> Unit
            }
        }
    }
    val audioPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            onStartVoiceInput { spokenCommand ->
                command = spokenCommand.take(MAX_COMMAND_LENGTH)
            }
        } else {
            onVoicePermissionDenied()
        }
    }
    fun startForegroundQrRead() {
        if (context.checkSelfPermission(Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            showQrReadScanner = true
        } else {
            pendingCameraScanMode = CameraScanMode.QR_READ
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }
    fun startForegroundOcrRead() {
        if (context.checkSelfPermission(Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            showOcrReadScanner = true
        } else {
            pendingCameraScanMode = CameraScanMode.OCR_READ
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    MaterialTheme(colorScheme = GoffyColors) {
        Surface(modifier = Modifier.fillMaxSize(), color = Void) {
            if (showForgetConfirmation) {
                ForgetHubDialog(
                    paired = state.hubLinkState == HubLinkState.PAIRED,
                    onConfirm = {
                        showForgetConfirmation = false
                        pairingChallenge = ""
                        bearerToken = ""
                        viewModel.forgetHub()
                        showLinkSetup = true
                    },
                    onDismiss = { showForgetConfirmation = false },
                )
            }
            if (showRotateConfirmation) {
                RotateHubDialog(
                    onConfirm = {
                        showRotateConfirmation = false
                        viewModel.rotateHubCredential()
                        showLinkSetup = true
                    },
                    onDismiss = { showRotateConfirmation = false },
                )
            }
            if (showPairingScanner) {
                PairingQrScannerDialog(
                    onScanned = { payload ->
                        pairingChallenge = payload.take(MAX_PAIRING_CHALLENGE_LENGTH)
                        pairingScannerNotice = PairingScannerNotice(
                            message = scannerCaptured,
                            warning = false,
                        )
                        showPairingScanner = false
                    },
                    onCameraFailure = {
                        pairingScannerNotice = PairingScannerNotice(
                            message = scannerStartFailed,
                            warning = true,
                        )
                        showPairingScanner = false
                    },
                    onDismiss = { showPairingScanner = false },
                )
            }
            if (showQrReadScanner) {
                QrReadScannerDialog(
                    onScanned = { payload ->
                        viewModel.recordForegroundQrScan(payload)
                        showQrReadScanner = false
                    },
                    onCameraFailure = {
                        viewModel.recordForegroundQrScanUnavailable(qrReadStartFailed)
                        showQrReadScanner = false
                    },
                    onDismiss = { showQrReadScanner = false },
                )
            }
            if (showOcrReadScanner) {
                OcrReadScannerDialog(
                    onTextRecognized = { text ->
                        viewModel.recordForegroundOcrRead(text)
                        showOcrReadScanner = false
                    },
                    onRecognitionFailure = {
                        viewModel.recordForegroundOcrReadUnavailable(ocrRecognitionFailed)
                        showOcrReadScanner = false
                    },
                    onCameraFailure = {
                        viewModel.recordForegroundOcrReadUnavailable(ocrReadStartFailed)
                        showOcrReadScanner = false
                    },
                    onDismiss = { showOcrReadScanner = false },
                )
            }
            GoffyHomeScreen(
                state = state,
                command = command,
                endpoint = endpoint,
                pairingChallenge = pairingChallenge,
                bearerToken = bearerToken,
                showLinkSetup = showLinkSetup,
                pairingScannerNotice = pairingScannerNotice,
                voiceInputState = voiceInputState,
                latestSpeakableText = latestSpeakableText,
                onCommandChange = { command = it.take(MAX_COMMAND_LENGTH) },
                onEndpointChange = { endpoint = it.take(MAX_ENDPOINT_LENGTH) },
                onPairingChallengeChange = {
                    pairingChallenge = it.take(MAX_PAIRING_CHALLENGE_LENGTH)
                    pairingScannerNotice = null
                },
                onBearerTokenChange = { bearerToken = it.take(MAX_TOKEN_LENGTH) },
                onToggleLinkSetup = { showLinkSetup = !showLinkSetup },
                onConfigureHub = {
                    if (viewModel.configureHub(endpoint, bearerToken)) {
                        bearerToken = ""
                        showLinkSetup = false
                    }
                },
                onScanPairingQr = {
                    if (context.checkSelfPermission(Manifest.permission.CAMERA) ==
                        PackageManager.PERMISSION_GRANTED
                    ) {
                        pairingScannerNotice = null
                        showPairingScanner = true
                    } else {
                        pendingCameraScanMode = CameraScanMode.PAIRING
                        cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                    }
                },
                onReadQrCode = { startForegroundQrRead() },
                onReadText = { startForegroundOcrRead() },
                onPairHub = {
                    val challenge = pairingChallenge
                    pairingChallenge = ""
                    pairingScannerNotice = null
                    viewModel.pairHub(endpoint, challenge)
                },
                onRotateHub = { showRotateConfirmation = true },
                onForgetHub = { showForgetConfirmation = true },
                onRefreshHubAudit = viewModel::refreshHubOperatorAudit,
                onOpenSystemSettings = onOpenSystemSettings,
                onOpenHomeSettings = onOpenHomeSettings,
                onCheckHomeStatus = { viewModel.submitCommand(GOFFY_HOME_STATUS_COMMAND) },
                onVoiceInput = {
                    if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
                        PackageManager.PERMISSION_GRANTED
                    ) {
                        onStartVoiceInput { spokenCommand ->
                            command = spokenCommand.take(MAX_COMMAND_LENGTH)
                        }
                    } else {
                        audioPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                },
                onSpeakLatest = onSpeakLatest,
                onSubmit = {
                    when {
                        isForegroundQrReadCommand(command) -> startForegroundQrRead()
                        isForegroundOcrReadCommand(command) -> startForegroundOcrRead()
                        else -> viewModel.submitCommand(command)
                    }
                    command = ""
                },
                onSetLocalModelEnabled = { enabled ->
                    viewModel.setLocalModelEnabled(enabled)
                },
                onCancel = viewModel::cancelActiveTask,
                onApprove = { taskId -> viewModel.approvePendingTask(taskId) },
                onDeny = { taskId -> viewModel.denyPendingTask(taskId) },
            )
        }
    }
}

@Composable
private fun PairingQrScannerDialog(
    onScanned: (String) -> Unit,
    onCameraFailure: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.pairing_scanner_title)) },
        text = {
            Column {
                Text(
                    text = stringResource(R.string.pairing_scanner_explanation),
                    color = Mist,
                    fontSize = 12.sp,
                )
                Spacer(Modifier.height(12.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(360.dp)
                        .clip(RoundedCornerShape(18.dp))
                        .background(Void)
                        .border(1.dp, Line, RoundedCornerShape(18.dp)),
                ) {
                    ForegroundQrScanner(
                        onPayloadScanned = onScanned,
                        onCameraFailure = onCameraFailure,
                        modifier = Modifier.fillMaxSize(),
                    )
                    Text(
                        text = stringResource(R.string.pairing_scanner_frame_label),
                        color = Bone,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 10.sp,
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .padding(top = 12.dp)
                            .background(Void.copy(alpha = 0.72f), RoundedCornerShape(99.dp))
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.pairing_scanner_close), color = Signal)
            }
        },
        containerColor = Panel,
        titleContentColor = Bone,
        textContentColor = Mist,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    )
}

@Composable
private fun QrReadScannerDialog(
    onScanned: (String) -> Unit,
    onCameraFailure: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.qr_read_scanner_title)) },
        text = {
            Column {
                Text(
                    text = stringResource(R.string.qr_read_scanner_explanation),
                    color = Mist,
                    fontSize = 12.sp,
                )
                Spacer(Modifier.height(12.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(360.dp)
                        .clip(RoundedCornerShape(18.dp))
                        .background(Void)
                        .border(1.dp, Line, RoundedCornerShape(18.dp)),
                ) {
                    ForegroundQrScanner(
                        onPayloadScanned = onScanned,
                        onCameraFailure = onCameraFailure,
                        modifier = Modifier.fillMaxSize(),
                    )
                    Text(
                        text = stringResource(R.string.qr_read_scanner_frame_label),
                        color = Bone,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 10.sp,
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .padding(top = 12.dp)
                            .background(Void.copy(alpha = 0.72f), RoundedCornerShape(99.dp))
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.qr_read_scanner_close), color = Signal)
            }
        },
        containerColor = Panel,
        titleContentColor = Bone,
        textContentColor = Mist,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    )
}

@Composable
private fun OcrReadScannerDialog(
    onTextRecognized: (String) -> Unit,
    onRecognitionFailure: () -> Unit,
    onCameraFailure: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.ocr_read_scanner_title)) },
        text = {
            Column {
                Text(
                    text = stringResource(R.string.ocr_read_scanner_explanation),
                    color = Mist,
                    fontSize = 12.sp,
                )
                Spacer(Modifier.height(12.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(360.dp)
                        .clip(RoundedCornerShape(18.dp))
                        .background(Void)
                        .border(1.dp, Line, RoundedCornerShape(18.dp)),
                ) {
                    ForegroundOcrScanner(
                        onTextRecognized = onTextRecognized,
                        onRecognitionFailure = onRecognitionFailure,
                        onCameraFailure = onCameraFailure,
                        modifier = Modifier.fillMaxSize(),
                    )
                    Text(
                        text = stringResource(R.string.ocr_read_scanner_frame_label),
                        color = Bone,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 10.sp,
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .padding(top = 12.dp)
                            .background(Void.copy(alpha = 0.72f), RoundedCornerShape(99.dp))
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.ocr_read_scanner_close), color = Signal)
            }
        },
        containerColor = Panel,
        titleContentColor = Bone,
        textContentColor = Mist,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    )
}

@Composable
private fun ForgetHubDialog(
    paired: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.forget_hub_title)) },
        text = {
            Text(
                stringResource(
                    if (paired) {
                        R.string.forget_hub_paired_explanation
                    } else {
                        R.string.forget_hub_debug_explanation
                    },
                ),
            )
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors = ButtonDefaults.buttonColors(
                    containerColor = Warning,
                    contentColor = Void,
                ),
            ) {
                Text(stringResource(R.string.forget_hub_confirm), fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.forget_hub_cancel), color = Signal)
            }
        },
        containerColor = Panel,
        titleContentColor = Bone,
        textContentColor = Mist,
    )
}

@Composable
private fun RotateHubDialog(
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(dismissOnClickOutside = false),
        title = { Text(stringResource(R.string.rotate_hub_title)) },
        text = {
            Text(
                text = stringResource(R.string.rotate_hub_explanation),
                color = Mist,
                fontSize = 13.sp,
            )
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors = ButtonDefaults.buttonColors(
                    containerColor = Signal,
                    contentColor = Void,
                ),
            ) {
                Text(stringResource(R.string.rotate_hub_confirm), fontWeight = FontWeight.Bold)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.rotate_hub_cancel), color = Signal)
            }
        },
        containerColor = Panel,
        titleContentColor = Bone,
        textContentColor = Mist,
    )
}

@Composable
private fun GoffyHomeScreen(
    state: GoffyUiState,
    command: String,
    endpoint: String,
    pairingChallenge: String,
    bearerToken: String,
    showLinkSetup: Boolean,
    pairingScannerNotice: PairingScannerNotice?,
    voiceInputState: GoffyVoiceInputState,
    latestSpeakableText: String?,
    onCommandChange: (String) -> Unit,
    onEndpointChange: (String) -> Unit,
    onPairingChallengeChange: (String) -> Unit,
    onBearerTokenChange: (String) -> Unit,
    onToggleLinkSetup: () -> Unit,
    onConfigureHub: () -> Unit,
    onScanPairingQr: () -> Unit,
    onReadQrCode: () -> Unit,
    onReadText: () -> Unit,
    onPairHub: () -> Unit,
    onRotateHub: () -> Unit,
    onForgetHub: () -> Unit,
    onRefreshHubAudit: () -> Unit,
    onOpenSystemSettings: () -> Unit,
    onOpenHomeSettings: () -> Unit,
    onCheckHomeStatus: () -> Unit,
    onVoiceInput: () -> Unit,
    onSpeakLatest: (String) -> Unit,
    onSubmit: () -> Unit,
    onSetLocalModelEnabled: (Boolean) -> Unit,
    onCancel: () -> Unit,
    onApprove: (UUID) -> Unit,
    onDeny: (UUID) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    listOf(Color(0xFF081014), Void, Color(0xFF07100D)),
                ),
            )
            .verticalScroll(rememberScrollState())
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .padding(horizontal = 20.dp, vertical = 18.dp),
    ) {
        Header(onOpenSystemSettings)
        Spacer(Modifier.height(20.dp))
        GoffyOrb(state.toGoffyOrbUiModel(voiceInputState))
        Spacer(Modifier.height(20.dp))
        StatusRail(state)
        Spacer(Modifier.height(12.dp))
        HomeSetupSection(
            model = state.toGoffyHomeSetupUiModel(),
            onCheckHomeStatus = onCheckHomeStatus,
            onOpenHomeSettings = onOpenHomeSettings,
        )
        Spacer(Modifier.height(12.dp))
        DeviceMapSection(state.toGoffyDeviceMapUiModel())
        if (state.localModelControlsAvailable) {
            Spacer(Modifier.height(12.dp))
            LocalModelRuntimeSection(
                state = state,
                onSetEnabled = onSetLocalModelEnabled,
            )
        }
        Spacer(Modifier.height(12.dp))
        HubLinkSection(
            state = state,
            endpoint = endpoint,
            pairingChallenge = pairingChallenge,
            bearerToken = bearerToken,
            showSetup = showLinkSetup,
            pairingScannerNotice = pairingScannerNotice,
            onEndpointChange = onEndpointChange,
            onPairingChallengeChange = onPairingChallengeChange,
            onBearerTokenChange = onBearerTokenChange,
            onToggleSetup = onToggleLinkSetup,
            onConfigure = onConfigureHub,
            onScanPairingQr = onScanPairingQr,
            onPair = onPairHub,
            onRotate = onRotateHub,
            onForget = onForgetHub,
        )
        Spacer(Modifier.height(12.dp))
        HubOperatorAuditSection(
            state = state,
            onRefresh = onRefreshHubAudit,
        )
        Spacer(Modifier.height(16.dp))
        CommandSurface(
            command = command,
            busy = state.isBusy,
            voiceInputState = voiceInputState,
            latestSpeakableText = latestSpeakableText,
            onCommandChange = onCommandChange,
            onSubmit = onSubmit,
            onCancel = onCancel,
            onVoiceInput = onVoiceInput,
            onReadQrCode = onReadQrCode,
            onReadText = onReadText,
            onSpeakLatest = onSpeakLatest,
        )
        Spacer(Modifier.height(18.dp))
        Timeline(
            entries = state.timeline.entries,
            pendingApproval = state.pendingApproval,
            auditPersistence = state.auditPersistence,
            discardedAuditRecords = state.discardedAuditRecords,
            onApprove = onApprove,
            onDeny = onDeny,
        )
    }
}

@Composable
private fun HomeSetupSection(
    model: GoffyHomeSetupUiModel,
    onCheckHomeStatus: () -> Unit,
    onOpenHomeSettings: () -> Unit,
) {
    val statusLabel = when (model.status) {
        GoffyHomeSetupStatus.UNKNOWN -> stringResource(R.string.home_setup_status_unknown)
        GoffyHomeSetupStatus.DEFAULT_HOME -> stringResource(R.string.home_setup_status_default)
        GoffyHomeSetupStatus.AVAILABLE -> stringResource(R.string.home_setup_status_available)
        GoffyHomeSetupStatus.UNAVAILABLE -> stringResource(R.string.home_setup_status_unavailable)
    }
    val body = when (model.status) {
        GoffyHomeSetupStatus.UNKNOWN -> stringResource(R.string.home_setup_body_unknown)
        GoffyHomeSetupStatus.DEFAULT_HOME -> stringResource(R.string.home_setup_body_default)
        GoffyHomeSetupStatus.AVAILABLE -> stringResource(R.string.home_setup_body_available)
        GoffyHomeSetupStatus.UNAVAILABLE -> stringResource(R.string.home_setup_body_unavailable)
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(Color(0xFF08131A))
            .border(1.dp, Line, RoundedCornerShape(18.dp))
            .padding(14.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Label(stringResource(R.string.home_setup_title))
                Text(
                    text = statusLabel,
                    color = Signal,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                )
            }
            Spacer(Modifier.width(10.dp))
            OutlinedButton(
                onClick = onCheckHomeStatus,
                enabled = model.canCheckHomeStatus,
            ) {
                Text(
                    text = stringResource(R.string.home_setup_check),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 10.sp,
                )
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            text = body,
            color = Mist,
            fontSize = 12.sp,
        )
        if (model.status != GoffyHomeSetupStatus.DEFAULT_HOME) {
            Spacer(Modifier.height(10.dp))
            Button(
                onClick = onOpenHomeSettings,
                enabled = model.canOpenHomeSettings,
                colors = ButtonDefaults.buttonColors(
                    containerColor = Signal,
                    contentColor = Void,
                    disabledContainerColor = Line,
                    disabledContentColor = Mist,
                ),
            ) {
                Text(
                    text = stringResource(R.string.home_setup_choose_home),
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Bold,
                    fontSize = 11.sp,
                )
            }
            Spacer(Modifier.height(6.dp))
            Text(
                text = stringResource(R.string.home_setup_no_silent_default),
                color = Mist,
                fontSize = 10.sp,
            )
        }
    }
}

@Composable
private fun LocalModelRuntimeSection(
    state: GoffyUiState,
    onSetEnabled: (Boolean) -> Unit,
) {
    val userEnabled = state.localModelStatus.enabledByUser
    val actionLabel = when {
        !state.localModelSettingsLoaded -> stringResource(R.string.local_model_loading)
        state.localModelOperationInProgress -> stringResource(R.string.local_model_saving)
        userEnabled -> stringResource(R.string.local_model_disable_runtime)
        else -> stringResource(R.string.local_model_enable_runtime)
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(Color(0xFF091217))
            .border(1.dp, Line, RoundedCornerShape(18.dp))
            .padding(14.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Label(stringResource(R.string.local_model_runtime_title))
                Text(
                    text = state.localModelStatus.summary,
                    color = Mist,
                    fontSize = 12.sp,
                )
            }
            Spacer(Modifier.width(12.dp))
            Button(
                onClick = { onSetEnabled(!userEnabled) },
                enabled = state.localModelSettingsLoaded &&
                    !state.isBusy &&
                    !state.localModelOperationInProgress,
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (userEnabled) Line else Signal,
                    contentColor = if (userEnabled) Bone else Void,
                ),
            ) {
                Text(actionLabel, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            text = stringResource(R.string.local_model_runtime_note),
            color = Mist,
            fontSize = 11.sp,
        )
        state.localModelNotice?.let { notice ->
            Spacer(Modifier.height(8.dp))
            Text(
                text = notice.message,
                color = if (notice.warning) Warning else Signal,
                fontSize = 12.sp,
            )
        }
    }
}

@Composable
private fun Header(onOpenSystemSettings: () -> Unit) {
    val systemSettingsDescription = stringResource(R.string.system_settings_description)
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Top,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = stringResource(R.string.home_kicker),
                color = Signal,
                fontFamily = FontFamily.Monospace,
                fontSize = 10.sp,
                letterSpacing = 1.2.sp,
            )
            Text(
                text = stringResource(R.string.home_title),
                color = Bone,
                fontFamily = FontFamily.Serif,
                fontWeight = FontWeight.Black,
                fontSize = 42.sp,
                letterSpacing = (-1).sp,
            )
            Text(
                text = stringResource(R.string.home_subtitle),
                color = Mist,
                fontSize = 14.sp,
            )
        }
        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = stringResource(R.string.performance_lite),
                color = Acid,
                fontFamily = FontFamily.Monospace,
                fontSize = 10.sp,
                modifier = Modifier
                    .border(1.dp, Acid.copy(alpha = 0.55f), RoundedCornerShape(99.dp))
                    .padding(horizontal = 10.dp, vertical = 7.dp),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedButton(
                onClick = onOpenSystemSettings,
                modifier = Modifier.semantics {
                    contentDescription = systemSettingsDescription
                },
            ) {
                Text(
                    text = stringResource(R.string.system_settings_short),
                    fontFamily = FontFamily.Monospace,
                    fontSize = 10.sp,
                )
            }
        }
    }
}

@Composable
private fun GoffyOrb(model: GoffyOrbUiModel) {
    val modeLabel = model.mode.label()
    val targetLabel = model.target.label()
    val phaseLabel = model.phase?.displayLabel() ?: stringResource(R.string.orb_phase_none)
    val description = stringResource(R.string.orb_description, modeLabel, targetLabel, phaseLabel)
    val accent = model.mode.accentColor()
    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Canvas(
                modifier = Modifier
                    .size(166.dp)
                    .semantics { contentDescription = description },
            ) {
                val center = Offset(size.width / 2f, size.height / 2f)
                val radius = size.minDimension / 2f
                val strokeWidth = 2.dp.toPx()
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(
                            Bone.copy(alpha = 0.98f),
                            accent.copy(alpha = 0.48f),
                            Color(0xFF10272B),
                            Color.Transparent,
                        ),
                        center = center,
                        radius = radius,
                    ),
                    radius = radius,
                )
                drawCircle(
                    color = Line.copy(alpha = 0.7f),
                    radius = radius * 0.78f,
                    style = Stroke(width = 1.dp.toPx(), cap = StrokeCap.Round),
                )
                drawCircle(
                    color = accent.copy(alpha = 0.86f),
                    radius = radius * 0.48f,
                    style = Stroke(width = strokeWidth, cap = StrokeCap.Round),
                )
                drawOrbStateMark(
                    mode = model.mode,
                    accent = accent,
                    center = center,
                    radius = radius,
                    strokeWidth = strokeWidth,
                )
            }
            Spacer(Modifier.height(10.dp))
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OrbStatusPill(stringResource(R.string.orb_loop_label, modeLabel), accent)
                OrbStatusPill(targetLabel, Signal)
            }
            if (model.phase != null) {
                Spacer(Modifier.height(6.dp))
                OrbStatusPill(stringResource(R.string.orb_phase_label, phaseLabel), Mist)
            }
        }
    }
}

private fun androidx.compose.ui.graphics.drawscope.DrawScope.drawOrbStateMark(
    mode: GoffyOrbMode,
    accent: Color,
    center: Offset,
    radius: Float,
    strokeWidth: Float,
) {
    when (mode) {
        GoffyOrbMode.IDLE -> drawCircle(
            color = accent.copy(alpha = 0.28f),
            radius = radius * 0.22f,
        )
        GoffyOrbMode.LISTENING -> drawCircle(
            color = accent.copy(alpha = 0.92f),
            radius = radius * 0.68f,
            style = Stroke(width = strokeWidth, cap = StrokeCap.Round),
        )
        GoffyOrbMode.PHONE_ROUTE -> {
            drawCircle(
                color = accent.copy(alpha = 0.9f),
                radius = radius * 0.3f,
                style = Stroke(width = strokeWidth * 1.35f, cap = StrokeCap.Round),
            )
            drawCircle(
                color = accent.copy(alpha = 0.42f),
                radius = radius * 0.18f,
            )
        }
        GoffyOrbMode.MAC_ROUTE -> {
            val y = center.y
            drawLine(
                color = accent.copy(alpha = 0.9f),
                start = Offset(center.x - radius * 0.52f, y),
                end = Offset(center.x + radius * 0.52f, y),
                strokeWidth = strokeWidth * 1.55f,
                cap = StrokeCap.Round,
            )
            drawCircle(color = accent, radius = radius * 0.08f, center = center)
        }
        GoffyOrbMode.CLOUD_ROUTE -> drawArc(
            color = accent.copy(alpha = 0.9f),
            startAngle = 210f,
            sweepAngle = 120f,
            useCenter = false,
            topLeft = Offset(center.x - radius * 0.5f, center.y - radius * 0.62f),
            size = Size(radius, radius * 0.72f),
            style = Stroke(width = strokeWidth * 1.4f, cap = StrokeCap.Round),
        )
        GoffyOrbMode.APPROVAL -> {
            drawCircle(
                color = Warning.copy(alpha = 0.95f),
                radius = radius * 0.62f,
                style = Stroke(width = strokeWidth * 1.35f, cap = StrokeCap.Round),
            )
            drawLine(
                color = Warning,
                start = Offset(center.x - radius * 0.16f, center.y + radius * 0.04f),
                end = Offset(center.x + radius * 0.16f, center.y + radius * 0.04f),
                strokeWidth = strokeWidth,
                cap = StrokeCap.Round,
            )
            drawLine(
                color = Warning,
                start = Offset(center.x, center.y - radius * 0.17f),
                end = Offset(center.x, center.y + radius * 0.22f),
                strokeWidth = strokeWidth,
                cap = StrokeCap.Round,
            )
        }
        GoffyOrbMode.VERIFIED -> {
            drawLine(
                color = accent,
                start = Offset(center.x - radius * 0.28f, center.y + radius * 0.02f),
                end = Offset(center.x - radius * 0.08f, center.y + radius * 0.22f),
                strokeWidth = strokeWidth * 1.8f,
                cap = StrokeCap.Round,
            )
            drawLine(
                color = accent,
                start = Offset(center.x - radius * 0.08f, center.y + radius * 0.22f),
                end = Offset(center.x + radius * 0.34f, center.y - radius * 0.26f),
                strokeWidth = strokeWidth * 1.8f,
                cap = StrokeCap.Round,
            )
        }
        GoffyOrbMode.ATTENTION -> drawCircle(
            color = accent.copy(alpha = 0.96f),
            radius = radius * 0.64f,
            style = Stroke(width = strokeWidth * 1.5f, cap = StrokeCap.Round),
        )
    }
}

@Composable
private fun OrbStatusPill(label: String, accent: Color) {
    Text(
        text = label,
        color = accent,
        fontFamily = FontFamily.Monospace,
        fontSize = 10.sp,
        maxLines = 1,
        modifier = Modifier
            .border(1.dp, accent.copy(alpha = 0.42f), RoundedCornerShape(99.dp))
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}

@Composable
private fun GoffyOrbMode.label(): String = stringResource(
    when (this) {
        GoffyOrbMode.IDLE -> R.string.orb_state_idle
        GoffyOrbMode.LISTENING -> R.string.orb_state_listening
        GoffyOrbMode.PHONE_ROUTE -> R.string.orb_state_phone_route
        GoffyOrbMode.MAC_ROUTE -> R.string.orb_state_mac_route
        GoffyOrbMode.CLOUD_ROUTE -> R.string.orb_state_cloud_route
        GoffyOrbMode.APPROVAL -> R.string.orb_state_approval
        GoffyOrbMode.VERIFIED -> R.string.orb_state_verified
        GoffyOrbMode.ATTENTION -> R.string.orb_state_attention
    },
)

@Composable
private fun ExecutionTarget.label(): String = stringResource(
    when (this) {
        ExecutionTarget.PHONE -> R.string.target_phone
        ExecutionTarget.MAC -> R.string.target_mac
        ExecutionTarget.CLOUD -> R.string.target_cloud
    },
)

private fun GoffyOrbMode.accentColor(): Color = when (this) {
    GoffyOrbMode.APPROVAL -> Warning
    GoffyOrbMode.ATTENTION -> Error
    GoffyOrbMode.VERIFIED,
    GoffyOrbMode.MAC_ROUTE,
    -> Signal
    GoffyOrbMode.PHONE_ROUTE,
    GoffyOrbMode.LISTENING,
    GoffyOrbMode.CLOUD_ROUTE,
    GoffyOrbMode.IDLE,
    -> Acid
}

private fun TaskPhase.displayLabel(): String = name.replace('_', ' ')

@Composable
private fun StatusRail(state: GoffyUiState) {
    val connectionValue = when (state.macConnection) {
        MacConnectionState.DISCONNECTED -> stringResource(R.string.connection_disconnected)
        MacConnectionState.CONNECTING -> stringResource(R.string.connection_connecting)
        MacConnectionState.CONNECTED -> stringResource(R.string.connection_connected)
    }
    val connectionAccent = if (state.macConnection == MacConnectionState.CONNECTED) Signal else Warning
    val targetValue = when (state.executionTarget) {
        ExecutionTarget.PHONE -> stringResource(R.string.target_phone)
        ExecutionTarget.MAC -> stringResource(R.string.target_mac)
        ExecutionTarget.CLOUD -> stringResource(R.string.target_cloud)
    }
    val localModelValue = when (state.localModelStatus.state) {
        LocalModelRuntimeState.DISABLED -> stringResource(R.string.local_model_disabled)
        LocalModelRuntimeState.UNAVAILABLE -> stringResource(R.string.local_model_unavailable)
        LocalModelRuntimeState.BLOCKED -> stringResource(R.string.local_model_blocked)
        LocalModelRuntimeState.READY -> stringResource(R.string.local_model_ready)
    }
    val localModelAccent = when (state.localModelStatus.state) {
        LocalModelRuntimeState.READY -> Signal
        LocalModelRuntimeState.BLOCKED -> Error
        LocalModelRuntimeState.DISABLED,
        LocalModelRuntimeState.UNAVAILABLE,
        -> Mist
    }
    val dockValue = when (state.dockAwakeStatus) {
        DockAwakeStatus.AWAKE -> stringResource(R.string.dock_awake)
        DockAwakeStatus.WAITING_FOR_POWER -> stringResource(R.string.dock_waiting)
        DockAwakeStatus.DISABLED -> stringResource(R.string.dock_disabled)
    }
    val dockAccent = when (state.dockAwakeStatus) {
        DockAwakeStatus.AWAKE -> Signal
        DockAwakeStatus.WAITING_FOR_POWER -> Mist
        DockAwakeStatus.DISABLED -> Warning
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        StatusCard(
            label = stringResource(R.string.connection_label),
            value = connectionValue,
            accent = connectionAccent,
            modifier = Modifier.weight(1f),
        )
        StatusCard(
            label = stringResource(R.string.target_label),
            value = targetValue,
            accent = Signal,
            modifier = Modifier.weight(1f),
        )
        StatusCard(
            label = stringResource(R.string.local_model_label),
            value = localModelValue,
            accent = localModelAccent,
            modifier = Modifier.weight(1f),
        )
        StatusCard(
            label = stringResource(R.string.dock_label),
            value = dockValue,
            accent = dockAccent,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun StatusCard(label: String, value: String, accent: Color, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(18.dp))
            .background(Panel.copy(alpha = 0.92f))
            .border(1.dp, Line, RoundedCornerShape(18.dp))
            .padding(14.dp),
    ) {
        Label(label)
        Spacer(Modifier.height(7.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(7.dp).background(accent, CircleShape))
            Spacer(Modifier.width(8.dp))
            Text(
                text = value,
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 12.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun DeviceMapSection(model: GoffyDeviceMapUiModel) {
    val targetLabel = model.activeTarget.label()
    val routeLabel = when (model.routeMode) {
        GoffyDeviceMapRouteMode.STANDBY ->
            stringResource(R.string.device_map_route_standby, targetLabel)
        GoffyDeviceMapRouteMode.ACTIVE_TARGET ->
            stringResource(R.string.device_map_route_active, targetLabel)
        GoffyDeviceMapRouteMode.LOCAL_MODEL_OBSERVATION ->
            stringResource(R.string.device_map_route_local_model)
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(Color(0xFF071115))
            .border(1.dp, Line, RoundedCornerShape(18.dp))
            .padding(14.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Label(stringResource(R.string.device_map_title))
                Text(
                    text = stringResource(R.string.device_map_description),
                    color = Mist,
                    fontSize = 11.sp,
                )
            }
            Spacer(Modifier.width(10.dp))
            Text(
                text = routeLabel,
                color = if (model.routeMode == GoffyDeviceMapRouteMode.STANDBY) Mist else Signal,
                fontFamily = FontFamily.Monospace,
                fontSize = 9.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.height(10.dp))
        model.nodes.forEachIndexed { index, node ->
            DeviceMapNodeRow(node)
            if (index < model.nodes.lastIndex) {
                Spacer(Modifier.height(7.dp))
            }
        }
    }
}

@Composable
private fun DeviceMapNodeRow(node: GoffyDeviceMapNode) {
    val label = node.kind.label()
    val status = node.status.label()
    val accent = node.status.accentColor()
    val routeState = stringResource(
        if (node.active) {
            R.string.device_map_node_routing
        } else {
            R.string.device_map_node_standby
        },
    )
    val description = stringResource(
        R.string.device_map_node_description,
        label,
        status,
        routeState,
    )
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(if (node.active) Signal.copy(alpha = 0.09f) else Panel.copy(alpha = 0.58f))
            .border(1.dp, accent.copy(alpha = 0.34f), RoundedCornerShape(14.dp))
            .semantics { contentDescription = description }
            .padding(horizontal = 11.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).background(accent, CircleShape))
        Spacer(Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = label,
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = status,
                color = Mist,
                fontFamily = FontFamily.Monospace,
                fontSize = 9.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        if (node.active) {
            Text(
                text = routeState,
                color = Signal,
                fontFamily = FontFamily.Monospace,
                fontSize = 9.sp,
            )
        }
    }
}

@Composable
private fun GoffyDeviceMapNodeKind.label(): String = stringResource(
    when (this) {
        GoffyDeviceMapNodeKind.PHONE -> R.string.device_map_phone
        GoffyDeviceMapNodeKind.MAC_HUB -> R.string.device_map_mac_hub
        GoffyDeviceMapNodeKind.MCP -> R.string.device_map_mcp
        GoffyDeviceMapNodeKind.LOCAL_MODEL -> R.string.device_map_local_model
        GoffyDeviceMapNodeKind.CLOUD -> R.string.device_map_cloud
    },
)

@Composable
private fun GoffyDeviceMapNodeStatus.label(): String = stringResource(
    when (this) {
        GoffyDeviceMapNodeStatus.READY -> R.string.device_map_status_ready
        GoffyDeviceMapNodeStatus.CONNECTING -> R.string.device_map_status_connecting
        GoffyDeviceMapNodeStatus.WAITING -> R.string.device_map_status_waiting
        GoffyDeviceMapNodeStatus.OFFLINE -> R.string.device_map_status_offline
        GoffyDeviceMapNodeStatus.DISABLED -> R.string.device_map_status_disabled
        GoffyDeviceMapNodeStatus.UNAVAILABLE -> R.string.device_map_status_unavailable
        GoffyDeviceMapNodeStatus.BLOCKED -> R.string.device_map_status_blocked
        GoffyDeviceMapNodeStatus.OBSERVE_ONLY -> R.string.device_map_status_observe_only
    },
)

private fun GoffyDeviceMapNodeStatus.accentColor(): Color = when (this) {
    GoffyDeviceMapNodeStatus.READY,
    GoffyDeviceMapNodeStatus.OBSERVE_ONLY,
    -> Signal
    GoffyDeviceMapNodeStatus.CONNECTING -> Acid
    GoffyDeviceMapNodeStatus.BLOCKED -> Error
    GoffyDeviceMapNodeStatus.UNAVAILABLE,
    GoffyDeviceMapNodeStatus.OFFLINE,
    -> Warning
    GoffyDeviceMapNodeStatus.WAITING,
    GoffyDeviceMapNodeStatus.DISABLED,
    -> Mist
}

@Composable
private fun HubLinkSection(
    state: GoffyUiState,
    endpoint: String,
    pairingChallenge: String,
    bearerToken: String,
    showSetup: Boolean,
    pairingScannerNotice: PairingScannerNotice?,
    onEndpointChange: (String) -> Unit,
    onPairingChallengeChange: (String) -> Unit,
    onBearerTokenChange: (String) -> Unit,
    onToggleSetup: () -> Unit,
    onConfigure: () -> Unit,
    onScanPairingQr: () -> Unit,
    onPair: () -> Unit,
    onRotate: () -> Unit,
    onForget: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(Color(0xFF091217))
            .border(1.dp, Line, RoundedCornerShape(18.dp))
            .padding(14.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Label(stringResource(R.string.hub_link_title))
                Text(
                    text = when (state.hubLinkState) {
                        HubLinkState.LOADING -> stringResource(R.string.hub_loading)
                        HubLinkState.PAIRING -> stringResource(R.string.hub_pairing)
                        HubLinkState.FORGETTING -> stringResource(R.string.hub_forgetting)
                        HubLinkState.ROTATING -> stringResource(R.string.hub_rotating)
                        HubLinkState.DEGRADED -> stringResource(R.string.hub_degraded)
                        HubLinkState.UNPAIRED -> stringResource(R.string.hub_not_configured)
                        HubLinkState.PAIRED,
                        HubLinkState.DEVELOPMENT,
                        -> state.hubEndpoint
                    },
                    color = if (state.hubConfigured) Signal else Mist,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (state.hubLinkState == HubLinkState.PAIRED &&
                    state.hubIdentityFingerprint != null
                ) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = stringResource(
                            R.string.hub_identity_fingerprint,
                            state.hubIdentityFingerprint,
                        ),
                        color = Mist,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 10.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                state.hubTokenRotationReminder?.let { reminder ->
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = stringResource(
                            R.string.hub_token_rotation_reminder,
                            reminder.tokenAgeDays,
                        ),
                        color = Warning,
                        fontSize = 11.sp,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            TextButton(onClick = onToggleSetup) {
                Text(stringResource(if (showSetup) R.string.hide_link_setup else R.string.edit_link_setup))
            }
        }

        if (showSetup) {
            Spacer(Modifier.height(10.dp))
            Text(
                text = stringResource(R.string.hub_link_security_note),
                color = Mist,
                fontSize = 12.sp,
            )
            if (!state.hubConfigured) {
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = endpoint,
                    onValueChange = onEndpointChange,
                    label = { Text(stringResource(R.string.hub_endpoint_label)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = goffyTextFieldColors(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = pairingChallenge,
                    onValueChange = onPairingChallengeChange,
                    label = { Text(stringResource(R.string.hub_pairing_challenge_label)) },
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth(),
                    colors = goffyTextFieldColors(),
                    minLines = 2,
                    maxLines = 3,
                )
                Spacer(Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = stringResource(R.string.hub_pairing_qr_note),
                        color = Mist,
                        fontSize = 12.sp,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(10.dp))
                    OutlinedButton(
                        onClick = onScanPairingQr,
                        enabled = !state.isBusy && !state.linkOperationInProgress,
                    ) {
                        Text(stringResource(R.string.scan_pairing_qr), color = Signal)
                    }
                }
                pairingScannerNotice?.let { notice ->
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = notice.message,
                        color = if (notice.warning) Warning else Signal,
                        fontSize = 12.sp,
                    )
                }
                if (state.developmentTokenAllowed) {
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = bearerToken,
                        onValueChange = onBearerTokenChange,
                        label = { Text(stringResource(R.string.hub_token_label)) },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        modifier = Modifier.fillMaxWidth(),
                        colors = goffyTextFieldColors(),
                    )
                }
            }
            state.linkError?.let { error ->
                Spacer(Modifier.height(8.dp))
                Text(error, color = Warning, fontSize = 12.sp)
            }
            state.linkNotice?.let { notice ->
                Spacer(Modifier.height(8.dp))
                Text(
                    notice.message,
                    color = if (notice.warning) Warning else Signal,
                    fontSize = 12.sp,
                )
            }
            Spacer(Modifier.height(10.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (state.hubConfigured) {
                    if (state.hubLinkState == HubLinkState.PAIRED) {
                        OutlinedButton(
                            onClick = onRotate,
                            enabled = !state.isBusy && !state.linkOperationInProgress,
                        ) {
                            Text(stringResource(R.string.rotate_hub), color = Signal)
                        }
                        Spacer(Modifier.width(8.dp))
                    }
                    TextButton(onClick = onForget) {
                        Text(stringResource(R.string.forget_hub), color = Warning)
                    }
                    Spacer(Modifier.width(8.dp))
                }
                if (!state.hubConfigured) {
                    Button(
                        onClick = onPair,
                        enabled = endpoint.isNotBlank() &&
                            pairingChallenge.isNotBlank() &&
                            !state.isBusy &&
                            !state.linkOperationInProgress,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Signal,
                            contentColor = Void,
                        ),
                    ) {
                        Text(stringResource(R.string.pair_hub), fontWeight = FontWeight.Bold)
                    }
                }
                if (state.developmentTokenAllowed && !state.hubConfigured) {
                    Spacer(Modifier.width(8.dp))
                    Button(
                        onClick = onConfigure,
                        enabled = endpoint.isNotBlank() &&
                            bearerToken.isNotBlank() &&
                            !state.isBusy &&
                            !state.linkOperationInProgress,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Line,
                            contentColor = Bone,
                        ),
                    ) {
                        Text(stringResource(R.string.configure_hub), fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}

@Composable
private fun HubOperatorAuditSection(
    state: GoffyUiState,
    onRefresh: () -> Unit,
) {
    val audit = state.hubOperatorAudit
    val paired = state.hubLinkState == HubLinkState.PAIRED
    val loading = audit.state == HubOperatorAuditState.LOADING
    val status = when (audit.state) {
        HubOperatorAuditState.IDLE -> stringResource(
            if (paired) R.string.hub_audit_idle else R.string.hub_audit_requires_pairing,
        )
        HubOperatorAuditState.LOADING -> stringResource(R.string.hub_audit_loading)
        HubOperatorAuditState.READY -> stringResource(
            R.string.hub_audit_ready,
            audit.events.size,
            audit.storageKind ?: "unknown",
            audit.integrity ?: "unknown",
        )
        HubOperatorAuditState.DEGRADED -> stringResource(R.string.hub_audit_degraded)
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(Color(0xFF071115))
            .border(1.dp, Line, RoundedCornerShape(18.dp))
            .padding(14.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Label(stringResource(R.string.hub_audit_title))
                Text(
                    text = status,
                    color = if (audit.state == HubOperatorAuditState.DEGRADED) Warning else Mist,
                    fontSize = 12.sp,
                )
            }
            Spacer(Modifier.width(10.dp))
            OutlinedButton(
                onClick = onRefresh,
                enabled = paired && !state.linkOperationInProgress && !loading,
            ) {
                Text(stringResource(R.string.refresh_hub_audit), color = Signal)
            }
        }
        Spacer(Modifier.height(8.dp))
        Text(
            text = stringResource(R.string.hub_audit_description),
            color = Mist,
            fontSize = 11.sp,
        )
        audit.message?.let { message ->
            Spacer(Modifier.height(8.dp))
            Text(message, color = Warning, fontSize = 12.sp)
        }
        if (audit.state == HubOperatorAuditState.READY) {
            Spacer(Modifier.height(10.dp))
            if (audit.events.isEmpty()) {
                Text(stringResource(R.string.hub_audit_empty), color = Mist, fontSize = 12.sp)
            } else {
                audit.events.take(MAX_HUB_AUDIT_UI_EVENTS).forEach { event ->
                    HubOperatorAuditRow(event)
                    Spacer(Modifier.height(7.dp))
                }
            }
        }
    }
}

@Composable
private fun HubOperatorAuditRow(event: HubOperatorAuditEvent) {
    val recordedAt = AuditTimestampFormatter.format(
        event.recordedAt.atZone(ZoneId.systemDefault()),
    )
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Panel.copy(alpha = 0.66f))
            .border(1.dp, Line.copy(alpha = 0.75f), RoundedCornerShape(12.dp))
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        Text(
            text = "#${event.sequence}  ${event.source}/${event.action}",
            color = Bone,
            fontFamily = FontFamily.Monospace,
            fontSize = 10.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = "${event.outcome.uppercase()} / ${event.principalKind} / $recordedAt",
            color = if (event.outcome == "failed") Warning else Signal,
            fontFamily = FontFamily.Monospace,
            fontSize = 9.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        event.detailCode?.let { detail ->
            Text(
                text = detail,
                color = Mist,
                fontFamily = FontFamily.Monospace,
                fontSize = 9.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun CommandSurface(
    command: String,
    busy: Boolean,
    voiceInputState: GoffyVoiceInputState,
    latestSpeakableText: String?,
    onCommandChange: (String) -> Unit,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
    onVoiceInput: () -> Unit,
    onReadQrCode: () -> Unit,
    onReadText: () -> Unit,
    onSpeakLatest: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(22.dp))
            .background(Panel)
            .border(1.dp, Line, RoundedCornerShape(22.dp))
            .padding(14.dp),
    ) {
        OutlinedTextField(
            value = command,
            onValueChange = onCommandChange,
            enabled = !busy,
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text(stringResource(R.string.command_hint), color = Mist) },
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(
                onSend = {
                    if (!busy && command.isNotBlank()) {
                        onSubmit()
                    }
                },
            ),
            minLines = 2,
            maxLines = 4,
            colors = goffyTextFieldColors(),
            shape = RoundedCornerShape(16.dp),
        )
        Spacer(Modifier.height(12.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                VoiceInputAction(
                    voiceInputState = voiceInputState,
                    busy = busy,
                    onVoiceInput = onVoiceInput,
                )
                CameraQrAction(
                    shortLabel = stringResource(R.string.camera_short),
                    description = stringResource(R.string.camera_placeholder),
                    busy = busy,
                    onReadQrCode = onReadQrCode,
                )
                CameraOcrAction(
                    shortLabel = stringResource(R.string.ocr_short),
                    description = stringResource(R.string.ocr_placeholder),
                    busy = busy,
                    onReadText = onReadText,
                )
                SpeakLatestAction(
                    speakableText = latestSpeakableText,
                    busy = busy,
                    onSpeakLatest = onSpeakLatest,
                )
            }
            if (busy) {
                OutlinedButton(onClick = onCancel) {
                    Text(stringResource(R.string.cancel_task), color = Warning)
                }
            } else {
                Button(
                    onClick = onSubmit,
                    enabled = command.isNotBlank(),
                    modifier = Modifier.semantics {
                        contentDescription = "Submit GOFFY command"
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Acid, contentColor = Void),
                ) {
                    Text(stringResource(R.string.send_command), fontWeight = FontWeight.Bold)
                }
            }
        }
        voiceInputState.notice?.let { notice ->
            Spacer(Modifier.height(8.dp))
            Text(
                text = notice,
                color = if (voiceInputState.warning) Warning else Signal,
                fontSize = 12.sp,
            )
        }
    }
}

@Composable
private fun VoiceInputAction(
    voiceInputState: GoffyVoiceInputState,
    busy: Boolean,
    onVoiceInput: () -> Unit,
) {
    val description = stringResource(R.string.microphone_placeholder)
    OutlinedButton(
        onClick = onVoiceInput,
        enabled = !busy && !voiceInputState.listening,
        modifier = Modifier.semantics { contentDescription = description },
        colors = ButtonDefaults.outlinedButtonColors(disabledContentColor = Mist),
    ) {
        Text(
            text = stringResource(
                if (voiceInputState.listening) {
                    R.string.microphone_listening_short
                } else {
                    R.string.microphone_short
                },
            ),
            fontFamily = FontFamily.Monospace,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun SpeakLatestAction(
    speakableText: String?,
    busy: Boolean,
    onSpeakLatest: (String) -> Unit,
) {
    val description = stringResource(R.string.speak_latest_result)
    OutlinedButton(
        onClick = { speakableText?.let(onSpeakLatest) },
        enabled = speakableText != null && !busy,
        modifier = Modifier.semantics { contentDescription = description },
        colors = ButtonDefaults.outlinedButtonColors(disabledContentColor = Mist),
    ) {
        Text(
            text = stringResource(R.string.speak_latest_short),
            fontFamily = FontFamily.Monospace,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun CameraQrAction(
    shortLabel: String,
    description: String,
    busy: Boolean,
    onReadQrCode: () -> Unit,
) {
    OutlinedButton(
        onClick = onReadQrCode,
        enabled = !busy,
        modifier = Modifier.semantics { contentDescription = description },
        colors = ButtonDefaults.outlinedButtonColors(disabledContentColor = Mist),
    ) {
        Text(shortLabel, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
    }
}

@Composable
private fun CameraOcrAction(
    shortLabel: String,
    description: String,
    busy: Boolean,
    onReadText: () -> Unit,
) {
    OutlinedButton(
        onClick = onReadText,
        enabled = !busy,
        modifier = Modifier.semantics { contentDescription = description },
        colors = ButtonDefaults.outlinedButtonColors(disabledContentColor = Mist),
    ) {
        Text(shortLabel, fontFamily = FontFamily.Monospace, fontSize = 11.sp)
    }
}

@Composable
private fun Timeline(
    entries: List<TaskTimelineEntry>,
    pendingApproval: PendingApproval?,
    auditPersistence: AuditPersistenceState,
    discardedAuditRecords: Int,
    onApprove: (UUID) -> Unit,
    onDeny: (UUID) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(22.dp))
            .background(Color(0xFF080E11))
            .border(1.dp, Line, RoundedCornerShape(22.dp))
            .padding(16.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Label(stringResource(R.string.timeline_title))
            val auditLabel = when (auditPersistence) {
                AuditPersistenceState.LOADING -> stringResource(R.string.audit_loading)
                AuditPersistenceState.READY -> stringResource(R.string.audit_ready)
                AuditPersistenceState.DEGRADED -> if (discardedAuditRecords > 0) {
                    stringResource(R.string.audit_degraded_records, discardedAuditRecords)
                } else {
                    stringResource(R.string.audit_degraded)
                }
            }
            Text(
                text = auditLabel,
                color = if (auditPersistence == AuditPersistenceState.DEGRADED) Warning else Signal,
                fontFamily = FontFamily.Monospace,
                fontSize = 9.sp,
            )
        }
        Spacer(Modifier.height(12.dp))
        if (entries.isEmpty()) {
            Text(stringResource(R.string.timeline_empty), color = Mist, fontSize = 14.sp)
        } else {
            entries.asReversed().forEach { entry ->
                TaskCard(
                    entry = entry,
                    approval = pendingApproval?.takeIf { it.taskId == entry.id },
                    onApprove = onApprove,
                    onDeny = onDeny,
                )
                Spacer(Modifier.height(10.dp))
            }
        }
    }
}

@Composable
private fun TaskCard(
    entry: TaskTimelineEntry,
    approval: PendingApproval?,
    onApprove: (UUID) -> Unit,
    onDeny: (UUID) -> Unit,
) {
    val phaseColor = when (entry.phase) {
        TaskPhase.VERIFIED -> Signal
        TaskPhase.UNVERIFIED,
        TaskPhase.FAILED,
        -> Error
        TaskPhase.AWAITING_APPROVAL,
        TaskPhase.CANCELLED,
        -> Warning
        else -> Acid
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Panel)
            .border(1.dp, phaseColor.copy(alpha = 0.45f), RoundedCornerShape(16.dp))
            .padding(13.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = entry.command,
                color = Bone,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.width(8.dp))
            Text(
                text = entry.phase.name.replace('_', ' '),
                color = phaseColor,
                fontFamily = FontFamily.Monospace,
                fontSize = 9.sp,
            )
        }
        Spacer(Modifier.height(5.dp))
        entry.result?.let { result ->
            TaskResult(result)
            Spacer(Modifier.height(7.dp))
        }
        Text(entry.summary, color = Mist, fontSize = 12.sp)
        entry.toolName?.let { tool ->
            Spacer(Modifier.height(7.dp))
            Text(
                text = listOfNotNull(
                    entry.executionTarget.name,
                    tool,
                    entry.permission?.name,
                ).joinToString("  /  "),
                color = Signal,
                fontFamily = FontFamily.Monospace,
                fontSize = 10.sp,
            )
        }
        entry.auditRecordedAtEpochMillis?.let { recordedAt ->
            Spacer(Modifier.height(5.dp))
            Text(
                text = stringResource(
                    R.string.audit_recorded_at,
                    AuditTimestampFormatter.format(
                        Instant.ofEpochMilli(recordedAt).atZone(ZoneId.systemDefault()),
                    ),
                ),
                color = Mist,
                fontFamily = FontFamily.Monospace,
                fontSize = 9.sp,
            )
        }
        approval?.let {
            ApprovalActions(it, onApprove, onDeny)
        }
        if (entry.events.isNotEmpty()) {
            Spacer(Modifier.height(9.dp))
            entry.events.takeLast(5).forEach { event ->
                val eventColor = if (event.kind in setOf(TaskEventKind.ERROR)) Warning else Mist
                Text(
                    text = "${event.kind.name.padEnd(7)} ${event.message}",
                    color = eventColor,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 9.sp,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun ApprovalActions(
    approval: PendingApproval,
    onApprove: (UUID) -> Unit,
    onDeny: (UUID) -> Unit,
) {
    Spacer(Modifier.height(12.dp))
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Warning.copy(alpha = 0.08f))
            .border(1.dp, Warning.copy(alpha = 0.45f), RoundedCornerShape(12.dp))
            .padding(12.dp),
    ) {
        Label(stringResource(R.string.approval_required))
        Spacer(Modifier.height(5.dp))
        Text(approval.description, color = Bone, fontSize = 12.sp)
        Text(
            stringResource(R.string.approval_expiry, approval.durationSeconds),
            color = Warning,
            fontFamily = FontFamily.Monospace,
            fontSize = 10.sp,
        )
        Spacer(Modifier.height(10.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
        ) {
            TextButton(onClick = { onDeny(approval.taskId) }) {
                Text(stringResource(R.string.deny_action), color = Warning)
            }
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = { onApprove(approval.taskId) },
                colors = ButtonDefaults.buttonColors(containerColor = Acid, contentColor = Void),
            ) {
                Text(stringResource(R.string.approve_once), fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
private fun TaskResult(result: ToolResultContent) {
    Spacer(Modifier.height(9.dp))
    when (result) {
        is GitStatus -> {
            Text(
                text = "REPO ${result.repoIndex} / ${result.repoName}",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = if (result.clean) {
                    "clean${result.branch?.let { " / $it" } ?: ""}"
                } else {
                    val shown = minOf(result.changes.size, 5)
                    "$shown of ${result.changes.size} shown" +
                        if (result.truncated) " / truncated" else ""
                },
                color = Signal,
                fontSize = 11.sp,
            )
            result.changes.take(5).forEach { change ->
                Text(
                    text = "${change.kind.uppercase()} / ${change.path}",
                    color = Mist,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        is MacFilesList -> {
            Text(
                text = "ROOT ${result.rootIndex} / ${result.rootName}",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = "${result.entries.size} entries${if (result.truncated) " / truncated" else ""}",
                color = Signal,
                fontSize = 11.sp,
            )
            result.entries.take(5).forEach { entry ->
                Text(
                    text = "${entry.kind.uppercase()} / ${entry.name}",
                    color = Mist,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        is MacFilesLargest -> {
            Text(
                text = "LARGEST / ${result.rootIndex} / ${result.rootName}",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = "${result.entries.size} files / scanned ${result.scannedEntries}" +
                    if (result.truncated) " / truncated" else "",
                color = Signal,
                fontSize = 11.sp,
            )
            result.entries.take(5).forEach { entry ->
                Text(
                    text = "${entry.sizeBytes.toReadableFileSize()} / ${entry.relativePath}",
                    color = Mist,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        is MacAppsList -> {
            Text(
                text = "MAC APPS / ${result.appCount}",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = "${result.entries.size} approved" +
                    if (result.truncated) " / truncated" else "",
                color = Signal,
                fontSize = 11.sp,
            )
            result.entries.take(5).forEach { entry ->
                Text(
                    text = "${entry.appIndex} / ${entry.displayName} / ${entry.bundleId}",
                    color = Mist,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        is MacAppOpened -> {
            Text(
                text = "MAC APP OPEN / ${result.status.uppercase()}",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = "${result.displayName} / ${result.bundleId} / verified ${result.verified}",
                color = Signal,
                fontSize = 11.sp,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        is MacProcessesList -> {
            Text(
                text = "MAC PROCESSES / ${result.processCount}",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = "${result.entries.size} shown / skipped ${result.skippedCount}" +
                    if (result.truncated) " / truncated" else "",
                color = Signal,
                fontSize = 11.sp,
            )
            result.entries.take(5).forEach { entry ->
                Text(
                    text = "#${entry.pid} / ${entry.name} / ${entry.rssBytes.toReadableFileSize()} / ${entry.status}",
                    color = Mist,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        is MacClipboardRead -> {
            Text(
                text = "MAC CLIPBOARD / ${result.status.uppercase()}",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = when (result.status) {
                    "available" ->
                        "${result.characterCount} text chars" +
                            if (result.textTruncated || result.characterCountTruncated) {
                                " / truncated"
                            } else {
                                ""
                            }
                    "empty" -> "no readable text"
                    "unsupported" -> "unsupported content hidden"
                    else -> "unknown clipboard state"
                },
                color = Signal,
                fontSize = 11.sp,
            )
            result.text?.let { text ->
                Text(
                    text = text,
                    color = Mist,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        is MacSystemInfo -> {
            Text(
                text = "${result.operatingSystem} / ${result.architecture}",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(result.status.uppercase(), color = Signal, fontSize = 11.sp)
        }
        is PhoneBatteryStatus -> {
            Text(
                text = "${result.levelPercent}%",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = stringResource(
                    if (result.charging) R.string.battery_charging else R.string.battery_on_battery,
                ),
                color = Signal,
                fontSize = 11.sp,
            )
        }
        is PhoneDeviceInfo -> {
            val homeStatus = when {
                result.goffyDefaultHome -> "default"
                result.goffyHomeCandidate -> "available"
                else -> "not available"
            }
            val systemStatus = if (result.goffySystemApp) "yes" else "no"
            Text(
                text = result.model,
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = stringResource(
                    R.string.device_info_details,
                    result.manufacturer,
                    result.androidRelease,
                    result.sdkInt,
                ),
                color = Signal,
                fontSize = 11.sp,
            )
            Text(
                text = "GOFFY home=$homeStatus / system=$systemStatus",
                color = Mist,
                fontSize = 11.sp,
            )
        }
        is PhoneFlashlightState -> {
            Text(
                text = stringResource(
                    if (result.enabled) R.string.flashlight_on else R.string.flashlight_off,
                ),
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = stringResource(
                    if (result.stateChanged) {
                        R.string.flashlight_changed_observed
                    } else {
                        R.string.flashlight_already_observed
                    },
                ),
                color = Signal,
                fontSize = 11.sp,
            )
        }
        is PhoneNoteCreated -> {
            Text(
                text = stringResource(R.string.note_created, result.noteId),
                color = Signal,
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
            )
            Text(
                text = result.text.take(MAX_NOTE_PREVIEW_LENGTH),
                color = Bone,
                fontSize = 14.sp,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
        }
        is PhoneMemoryRemembered -> {
            Text(
                text = "MEMORY SAVED / #${result.memoryId}",
                color = Signal,
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
            )
            Text(
                text = result.text.take(MAX_MEMORY_PREVIEW_LENGTH),
                color = Bone,
                fontSize = 14.sp,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = result.provenance,
                color = Mist,
                fontFamily = FontFamily.Monospace,
                fontSize = 10.sp,
            )
        }
        is PhoneMemoryUpdated -> {
            Text(
                text = "MEMORY UPDATED / #${result.memoryId}",
                color = Signal,
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
            )
            Text(
                text = result.text.take(MAX_MEMORY_PREVIEW_LENGTH),
                color = Bone,
                fontSize = 14.sp,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = result.provenance,
                color = Mist,
                fontFamily = FontFamily.Monospace,
                fontSize = 10.sp,
            )
        }
        is PhoneMemoryList -> {
            Text(
                text = "MEMORIES / ${result.count}" + if (result.truncated) " / truncated" else "",
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            if (result.entries.isEmpty()) {
                Text("No local memories stored.", color = Mist, fontSize = 11.sp)
            } else {
                result.entries.take(5).forEach { entry ->
                    Text(
                        text = "#${entry.memoryId} / ${entry.text}",
                        color = Mist,
                        fontFamily = FontFamily.Monospace,
                        fontSize = 11.sp,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
        is PhoneMemoryDeleted -> {
            Text(
                text = "MEMORY DELETED / #${result.memoryId}",
                color = Warning,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = "remaining=${result.remainingCount}",
                color = Signal,
                fontSize = 11.sp,
            )
        }
        is PhoneMemoryForgotten -> {
            Text(
                text = "MEMORIES DELETED / ${result.deletedCount}",
                color = Warning,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = "remaining=${result.remainingCount}",
                color = Signal,
                fontSize = 11.sp,
            )
        }
        is PhoneOcrRead -> {
            Text(
                text = stringResource(R.string.ocr_read_result, result.lineCount),
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = if (result.redacted) {
                    stringResource(R.string.ocr_read_redacted_result, result.characterCount)
                } else {
                    stringResource(
                        R.string.ocr_read_preview_result,
                        result.characterCount,
                        result.preview ?: "",
                    )
                },
                color = if (result.redacted) Warning else Mist,
                fontSize = 11.sp,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
        }
        is PhoneQrRead -> {
            Text(
                text = stringResource(R.string.qr_read_result, result.contentType.uppercase()),
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 13.sp,
            )
            Text(
                text = if (result.redacted) {
                    stringResource(R.string.qr_read_redacted_result, result.characterCount)
                } else {
                    stringResource(
                        R.string.qr_read_preview_result,
                        result.characterCount,
                        result.preview ?: "",
                    )
                },
                color = if (result.redacted) Warning else Mist,
                fontSize = 11.sp,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        is PhoneTimerDispatched -> {
            Text(
                text = stringResource(R.string.timer_dispatched, result.durationSeconds),
                color = Bone,
                fontFamily = FontFamily.Monospace,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = stringResource(R.string.timer_clock_package, result.clockPackage),
                color = Signal,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun Label(text: String) {
    Text(
        text = text,
        color = Signal,
        fontFamily = FontFamily.Monospace,
        fontSize = 9.sp,
        letterSpacing = 0.9.sp,
    )
}

@Composable
private fun goffyTextFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = Signal,
    unfocusedBorderColor = Line,
    cursorColor = Acid,
    disabledBorderColor = Line.copy(alpha = 0.5f),
    disabledTextColor = Mist,
)

private fun Long.toReadableFileSize(): String {
    val units = listOf("B", "KB", "MB", "GB", "TB")
    var value = toDouble()
    var unitIndex = 0
    while (value >= 1024.0 && unitIndex < units.lastIndex) {
        value /= 1024.0
        unitIndex += 1
    }
    return if (unitIndex == 0) {
        "${this}B"
    } else {
        String.format(java.util.Locale.US, "%.1f%s", value, units[unitIndex])
    }
}

private const val MAX_COMMAND_LENGTH = 2_000
private const val MAX_ENDPOINT_LENGTH = 2_048
private const val MAX_TOKEN_LENGTH = 4_096
private const val MAX_PAIRING_CHALLENGE_LENGTH = 2_048
private const val MAX_NOTE_PREVIEW_LENGTH = 256
private const val MAX_MEMORY_PREVIEW_LENGTH = 256
private const val MAX_HUB_AUDIT_UI_EVENTS = 5
private const val GOFFY_HOME_STATUS_COMMAND = "Show my phone info"
