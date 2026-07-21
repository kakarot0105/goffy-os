package dev.goffy.os

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.os.Build
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle

class MainActivity : ComponentActivity() {
    private lateinit var goffyViewModel: GoffyViewModel
    private var textToSpeech: TextToSpeech? = null
    private var textToSpeechReady = false
    private var pendingSpeechText: String? = null
    private var speechRecognizer: SpeechRecognizer? = null
    private var pendingVoiceCommand: ((String) -> Unit)? = null
    private var voiceInputSessionActive = false
    private var voiceInputState by mutableStateOf(GoffyVoiceInputState())
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
                voiceInputState = voiceInputState,
                onStartVoiceInput = ::startVoiceInput,
                onVoicePermissionDenied = ::voicePermissionDenied,
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
        stopVoiceInput()
        stopSpeechOutput()
        goffyViewModel.updateChargingState(false)
        goffyViewModel.cancelForegroundPairing()
        super.onStop()
    }

    override fun onDestroy() {
        shutdownSpeechOutput()
        shutdownVoiceInput()
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

    private fun startVoiceInput(onCommand: (String) -> Unit) {
        if (voiceInputState.listening) return
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            voiceInputState = GoffyVoiceInputState(
                notice = getString(R.string.voice_unavailable),
                warning = true,
            )
            return
        }

        stopSpeechOutput()
        pendingVoiceCommand = onCommand
        voiceInputSessionActive = true
        val recognizer = speechRecognizer ?: SpeechRecognizer.createSpeechRecognizer(this).also {
            speechRecognizer = it
        }
        recognizer.setRecognitionListener(createRecognitionListener())
        voiceInputState = GoffyVoiceInputState(
            listening = true,
            notice = getString(R.string.voice_listening),
            warning = false,
        )
        try {
            recognizer.startListening(
                Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(
                        RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                        RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
                    )
                    .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
                    .putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
                    .putExtra(RecognizerIntent.EXTRA_PROMPT, getString(R.string.voice_prompt)),
            )
        } catch (_: RuntimeException) {
            voiceInputSessionActive = false
            pendingVoiceCommand = null
            voiceInputState = GoffyVoiceInputState(
                notice = getString(R.string.voice_error),
                warning = true,
            )
        }
    }

    private fun createRecognitionListener(): RecognitionListener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) = Unit

        override fun onBeginningOfSpeech() = Unit

        override fun onRmsChanged(rmsdB: Float) = Unit

        override fun onBufferReceived(buffer: ByteArray?) = Unit

        override fun onEndOfSpeech() {
            if (!voiceInputSessionActive) return
            voiceInputState = voiceInputState.copy(
                listening = false,
                notice = getString(R.string.voice_processing),
                warning = false,
            )
        }

        override fun onError(error: Int) {
            if (!voiceInputSessionActive) return
            voiceInputSessionActive = false
            pendingVoiceCommand = null
            voiceInputState = GoffyVoiceInputState(
                notice = voiceErrorMessage(error),
                warning = true,
            )
        }

        override fun onResults(results: Bundle?) {
            if (!voiceInputSessionActive) return
            voiceInputSessionActive = false
            val command = results
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                ?.toSafeRecognizedCommand()
            val commandHandler = pendingVoiceCommand
            pendingVoiceCommand = null
            if (command == null || commandHandler == null) {
                voiceInputState = GoffyVoiceInputState(
                    notice = getString(R.string.voice_no_match),
                    warning = true,
                )
                return
            }
            commandHandler(command)
            voiceInputState = GoffyVoiceInputState(
                notice = getString(R.string.voice_captured),
                warning = false,
            )
        }

        override fun onPartialResults(partialResults: Bundle?) = Unit

        override fun onEvent(eventType: Int, params: Bundle?) = Unit
    }

    private fun voiceErrorMessage(error: Int): String = when (error) {
        SpeechRecognizer.ERROR_NO_MATCH,
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
        -> getString(R.string.voice_no_match)
        SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> getString(R.string.voice_busy)
        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> getString(R.string.voice_permission_denied)
        else -> getString(R.string.voice_error)
    }

    private fun voicePermissionDenied() {
        voiceInputState = GoffyVoiceInputState(
            notice = getString(R.string.voice_permission_denied),
            warning = true,
        )
    }

    private fun stopVoiceInput() {
        voiceInputSessionActive = false
        pendingVoiceCommand = null
        speechRecognizer?.cancel()
        voiceInputState = GoffyVoiceInputState()
    }

    private fun shutdownVoiceInput() {
        stopVoiceInput()
        speechRecognizer?.destroy()
        speechRecognizer = null
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
