package dev.goffy.os

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.os.Build
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle

class MainActivity : ComponentActivity() {
    private lateinit var goffyViewModel: GoffyViewModel
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
            GoffyApp(goffyViewModel)
        }
    }

    override fun onStart() {
        super.onStart()
        observeChargingState()
    }

    override fun onStop() {
        stopObservingChargingState()
        applyKeepScreenAwake(false)
        goffyViewModel.updateChargingState(false)
        goffyViewModel.cancelForegroundPairing()
        super.onStop()
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
}
