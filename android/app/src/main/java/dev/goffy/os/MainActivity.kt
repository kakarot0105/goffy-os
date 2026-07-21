package dev.goffy.os

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.os.Build
import android.speech.tts.TextToSpeech
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle

class MainActivity : ComponentActivity() {
    private lateinit var goffyViewModel: GoffyViewModel
    private var textToSpeech: TextToSpeech? = null
    private var textToSpeechReady = false
    private var pendingSpeechText: String? = null
    private var chargingReceiverRegistered = false
    private val chargingReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            goffyViewModel.updateChargingState(intent.isGoffyCharging())
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        goffyViewModel = ViewModelProvider(
            this,
            GoffyViewModel.Factory(applicationContext),
        )[GoffyViewModel::class.java]
        setContent {
            val state by goffyViewModel.uiState.collectAsStateWithLifecycle()
            DisposableEffect(state.keepScreenAwake) {
                applyKeepScreenAwake(state.keepScreenAwake)
                onDispose { applyKeepScreenAwake(false) }
            }
            GoffyApp(
                viewModel = goffyViewModel,
                onSpeakLatest = ::speakLatestResult,
            )
        }
    }

    override fun onStart() {
        super.onStart()
        observeChargingState()
    }

    override fun onStop() {
        stopObservingChargingState()
        applyKeepScreenAwake(false)
        stopSpeechOutput()
        goffyViewModel.updateChargingState(false)
        goffyViewModel.cancelForegroundPairing()
        super.onStop()
    }

    override fun onDestroy() {
        shutdownSpeechOutput()
        super.onDestroy()
    }

    private fun observeChargingState() {
        if (chargingReceiverRegistered) return
        val filter = IntentFilter(Intent.ACTION_BATTERY_CHANGED)
        val sticky = if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(chargingReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            registerReceiver(chargingReceiver, filter)
        }
        chargingReceiverRegistered = true
        goffyViewModel.updateChargingState(sticky.isGoffyCharging())
    }

    private fun stopObservingChargingState() {
        if (!chargingReceiverRegistered) return
        runCatching { unregisterReceiver(chargingReceiver) }
        chargingReceiverRegistered = false
    }

    private fun applyKeepScreenAwake(enabled: Boolean) {
        if (enabled) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    private fun speakLatestResult(text: String) {
        val safeText = text.toSafeSpeechText() ?: return
        val currentEngine = textToSpeech
        if (currentEngine != null && textToSpeechReady) {
            speakNow(currentEngine, safeText)
            return
        }

        pendingSpeechText = safeText
        if (currentEngine != null) return
        textToSpeech = TextToSpeech(applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) {
                textToSpeechReady = true
                val pending = pendingSpeechText
                pendingSpeechText = null
                val initializedEngine = textToSpeech
                if (pending != null && initializedEngine != null) {
                    speakNow(initializedEngine, pending)
                }
            } else {
                pendingSpeechText = null
                textToSpeechReady = false
            }
        }
    }

    private fun speakNow(engine: TextToSpeech, text: String) {
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, GOFFY_SPEECH_UTTERANCE_ID)
    }

    private fun stopSpeechOutput() {
        pendingSpeechText = null
        textToSpeech?.stop()
    }

    private fun shutdownSpeechOutput() {
        stopSpeechOutput()
        textToSpeech?.shutdown()
        textToSpeech = null
        textToSpeechReady = false
    }

    private fun String.toSafeSpeechText(): String? =
        replace(Regex("\\p{Cntrl}+"), " ")
            .trim()
            .take(MAX_SPEECH_UTTERANCE_LENGTH)
            .ifEmpty { null }

    private companion object {
        const val GOFFY_SPEECH_UTTERANCE_ID = "goffy-latest-result"
        const val MAX_SPEECH_UTTERANCE_LENGTH = 480
    }
}
