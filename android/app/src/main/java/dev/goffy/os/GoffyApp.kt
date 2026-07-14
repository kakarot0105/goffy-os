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
import dev.goffy.os.qr.PairingQrScanner
import dev.goffy.os.protocol.ExecutionTarget
import dev.goffy.os.protocol.MacSystemInfo
import dev.goffy.os.protocol.PhoneBatteryStatus
import dev.goffy.os.protocol.PhoneDeviceInfo
import dev.goffy.os.protocol.PhoneFlashlightState
import dev.goffy.os.protocol.PhoneNoteCreated
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

@Composable
fun GoffyApp(viewModel: GoffyViewModel) {
    val context = LocalContext.current
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var command by remember { mutableStateOf("") }
    var endpoint by rememberSaveable(state.hubEndpoint) { mutableStateOf(state.hubEndpoint) }
    var pairingChallenge by remember { mutableStateOf("") }
    var bearerToken by remember { mutableStateOf("") }
    var showLinkSetup by remember(state.hubConfigured) { mutableStateOf(!state.hubConfigured) }
    var showForgetConfirmation by remember { mutableStateOf(false) }
    var showPairingScanner by remember { mutableStateOf(false) }
    var pairingScannerNotice by remember { mutableStateOf<PairingScannerNotice?>(null) }
    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            pairingScannerNotice = null
            showPairingScanner = true
        } else {
            pairingScannerNotice = PairingScannerNotice(
                message = context.getString(R.string.pairing_scanner_permission_denied),
                warning = true,
            )
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
            if (showPairingScanner) {
                PairingQrScannerDialog(
                    onScanned = { payload ->
                        pairingChallenge = payload.take(MAX_PAIRING_CHALLENGE_LENGTH)
                        pairingScannerNotice = PairingScannerNotice(
                            message = context.getString(R.string.pairing_scanner_captured),
                            warning = false,
                        )
                        showPairingScanner = false
                    },
                    onCameraFailure = {
                        pairingScannerNotice = PairingScannerNotice(
                            message = context.getString(R.string.pairing_scanner_start_failed),
                            warning = true,
                        )
                        showPairingScanner = false
                    },
                    onDismiss = { showPairingScanner = false },
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
                        cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                    }
                },
                onPairHub = {
                    val challenge = pairingChallenge
                    pairingChallenge = ""
                    pairingScannerNotice = null
                    viewModel.pairHub(endpoint, challenge)
                },
                onForgetHub = { showForgetConfirmation = true },
                onSubmit = {
                    viewModel.submitCommand(command)
                    command = ""
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
                    PairingQrScanner(
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
private fun GoffyHomeScreen(
    state: GoffyUiState,
    command: String,
    endpoint: String,
    pairingChallenge: String,
    bearerToken: String,
    showLinkSetup: Boolean,
    pairingScannerNotice: PairingScannerNotice?,
    onCommandChange: (String) -> Unit,
    onEndpointChange: (String) -> Unit,
    onPairingChallengeChange: (String) -> Unit,
    onBearerTokenChange: (String) -> Unit,
    onToggleLinkSetup: () -> Unit,
    onConfigureHub: () -> Unit,
    onScanPairingQr: () -> Unit,
    onPairHub: () -> Unit,
    onForgetHub: () -> Unit,
    onSubmit: () -> Unit,
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
        Header()
        Spacer(Modifier.height(20.dp))
        GoffyOrb()
        Spacer(Modifier.height(20.dp))
        StatusRail(state)
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
            onForget = onForgetHub,
        )
        Spacer(Modifier.height(16.dp))
        CommandSurface(
            command = command,
            busy = state.isBusy,
            onCommandChange = onCommandChange,
            onSubmit = onSubmit,
            onCancel = onCancel,
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
private fun Header() {
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
        Text(
            text = stringResource(R.string.performance_lite),
            color = Acid,
            fontFamily = FontFamily.Monospace,
            fontSize = 10.sp,
            modifier = Modifier
                .border(1.dp, Acid.copy(alpha = 0.55f), RoundedCornerShape(99.dp))
                .padding(horizontal = 10.dp, vertical = 7.dp),
        )
    }
}

@Composable
private fun GoffyOrb() {
    val description = stringResource(R.string.orb_description)
    Box(
        modifier = Modifier.fillMaxWidth(),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(
            modifier = Modifier
                .size(142.dp)
                .semantics { contentDescription = description },
        ) {
            val center = Offset(size.width / 2f, size.height / 2f)
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(Bone, Signal, Color(0xFF12383A), Color.Transparent),
                    center = center,
                    radius = size.minDimension / 2f,
                ),
                radius = size.minDimension / 2f,
            )
            drawCircle(
                color = Acid.copy(alpha = 0.72f),
                radius = size.minDimension * 0.42f,
                style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round),
            )
        }
    }
}

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
private fun CommandSurface(
    command: String,
    busy: Boolean,
    onCommandChange: (String) -> Unit,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
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
                PlaceholderAction(
                    shortLabel = stringResource(R.string.microphone_short),
                    description = stringResource(R.string.microphone_placeholder),
                )
                PlaceholderAction(
                    shortLabel = stringResource(R.string.camera_short),
                    description = stringResource(R.string.camera_placeholder),
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
                    colors = ButtonDefaults.buttonColors(containerColor = Acid, contentColor = Void),
                ) {
                    Text(stringResource(R.string.send_command), fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@Composable
private fun PlaceholderAction(shortLabel: String, description: String) {
    OutlinedButton(
        onClick = {},
        enabled = false,
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
        TaskPhase.AWAITING_APPROVAL,
        TaskPhase.FAILED,
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
        entry.result?.let { result ->
            TaskResult(result)
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

private const val MAX_COMMAND_LENGTH = 2_000
private const val MAX_ENDPOINT_LENGTH = 2_048
private const val MAX_TOKEN_LENGTH = 4_096
private const val MAX_PAIRING_CHALLENGE_LENGTH = 2_048
private const val MAX_NOTE_PREVIEW_LENGTH = 256
