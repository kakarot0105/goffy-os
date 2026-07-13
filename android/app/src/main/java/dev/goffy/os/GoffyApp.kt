package dev.goffy.os

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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Void = Color(0xFF05090C)
private val Panel = Color(0xFF0B1318)
private val Line = Color(0xFF23333B)
private val Bone = Color(0xFFF1F0E8)
private val Mist = Color(0xFF94A5AC)
private val Acid = Color(0xFFB6F23A)
private val Signal = Color(0xFF41D7C7)
private val Warning = Color(0xFFFF7A59)

private val GoffyColors = darkColorScheme(
    primary = Acid,
    secondary = Signal,
    background = Void,
    surface = Panel,
    onPrimary = Void,
    onBackground = Bone,
    onSurface = Bone,
)

@Composable
fun GoffyApp() {
    MaterialTheme(colorScheme = GoffyColors) {
        Surface(modifier = Modifier.fillMaxSize(), color = Void) {
            var state by remember { mutableStateOf(GoffyUiState()) }
            var command by rememberSaveable { mutableStateOf("") }
            val waitingStatus = stringResource(R.string.waiting_for_hub)

            GoffyHomeScreen(
                state = state,
                command = command,
                onCommandChange = { command = it.take(MAX_COMMAND_LENGTH) },
                onSubmit = {
                    state = state.queueCommand(command, waitingStatus)
                    command = ""
                },
            )
        }
    }
}

@Composable
private fun GoffyHomeScreen(
    state: GoffyUiState,
    command: String,
    onCommandChange: (String) -> Unit,
    onSubmit: () -> Unit,
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
        Spacer(Modifier.height(22.dp))
        GoffyOrb()
        Spacer(Modifier.height(22.dp))
        StatusRail(state)
        Spacer(Modifier.height(18.dp))
        CommandSurface(command, onCommandChange, onSubmit)
        Spacer(Modifier.height(20.dp))
        Timeline(state.timeline)
    }
}

@Composable
private fun Header() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.Top,
    ) {
        Column {
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
                .size(156.dp)
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
        Text(
            text = label,
            color = Mist,
            fontFamily = FontFamily.Monospace,
            fontSize = 9.sp,
            letterSpacing = 0.8.sp,
        )
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
private fun CommandSurface(
    command: String,
    onCommandChange: (String) -> Unit,
    onSubmit: () -> Unit,
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
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text(stringResource(R.string.command_hint), color = Mist) },
            minLines = 2,
            maxLines = 4,
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Signal,
                unfocusedBorderColor = Line,
                cursorColor = Acid,
            ),
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
            Button(
                onClick = onSubmit,
                enabled = command.isNotBlank(),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Acid,
                    contentColor = Void,
                ),
            ) {
                Text(stringResource(R.string.send_command), fontWeight = FontWeight.Bold)
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
private fun Timeline(entries: List<TimelineEntry>) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(22.dp))
            .background(Color(0xFF080E11))
            .border(1.dp, Line, RoundedCornerShape(22.dp))
            .padding(16.dp),
    ) {
        Text(
            text = stringResource(R.string.timeline_title),
            color = Signal,
            fontFamily = FontFamily.Monospace,
            fontSize = 10.sp,
            letterSpacing = 1.sp,
        )
        Spacer(Modifier.height(12.dp))
        if (entries.isEmpty()) {
            Text(
                text = stringResource(R.string.timeline_empty),
                color = Mist,
                fontSize = 14.sp,
            )
        } else {
            entries.asReversed().forEach { entry ->
                Column(Modifier.padding(vertical = 7.dp)) {
                    Text(entry.command, color = Bone, fontWeight = FontWeight.SemiBold)
                    Text(entry.status, color = Warning, fontSize = 12.sp)
                }
            }
        }
    }
}

private const val MAX_COMMAND_LENGTH = 2_000
