package dev.goffy.os

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.remember
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val factory = remember { GoffyViewModel.Factory(applicationContext) }
            val goffyViewModel: GoffyViewModel = viewModel(
                factory = factory,
            )
            GoffyApp(goffyViewModel)
        }
    }
}
