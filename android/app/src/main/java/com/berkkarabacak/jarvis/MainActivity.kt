package com.berkkarabacak.jarvis

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.lifecycleScope
import com.berkkarabacak.jarvis.ui.JarvisRoot
import com.berkkarabacak.jarvis.ui.theme.JarvisTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as JarvisApplication
        app.billing.start()
        setContent {
            JarvisTheme {
                JarvisRoot(
                    client = app.jarvisClient,
                    connectionStore = app.connectionStore,
                    billing = app.billing,
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        val app = application as JarvisApplication
        lifecycleScope.launch {
            app.billing.refresh(applyBudget = true)
        }
    }
}
