package dev.goffy.os

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.lifecycle.ViewModelProvider

class MainActivity : ComponentActivity() {
    private lateinit var goffyViewModel: GoffyViewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        goffyViewModel = ViewModelProvider(
            this,
            GoffyViewModel.Factory(applicationContext),
        )[GoffyViewModel::class.java]
        setContent {
            GoffyApp(goffyViewModel)
        }
    }

    override fun onStop() {
        goffyViewModel.cancelForegroundPairing()
        super.onStop()
    }
}
