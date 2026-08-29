package com.berkkarabacak.jarvis.ui

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.berkkarabacak.jarvis.billing.PlayBillingCoordinator
import com.berkkarabacak.jarvis.data.ConnectionStore
import com.berkkarabacak.jarvis.data.JarvisClient
import com.berkkarabacak.jarvis.ui.settings.SettingsScreen
import com.berkkarabacak.jarvis.ui.settings.SettingsViewModel
import com.berkkarabacak.jarvis.ui.talk.TalkScreen
import com.berkkarabacak.jarvis.ui.talk.TalkViewModel

@Composable
fun JarvisRoot(
    client: JarvisClient,
    connectionStore: ConnectionStore,
    billing: PlayBillingCoordinator,
) {
    val nav = rememberNavController()
    val talkFactory = remember(client, connectionStore) {
        TalkViewModel.factory(client, connectionStore)
    }
    val settingsFactory = remember(client, connectionStore, billing) {
        SettingsViewModel.factory(client, connectionStore, billing)
    }

    NavHost(navController = nav, startDestination = "talk") {
        composable("talk") {
            val vm: TalkViewModel = viewModel(factory = talkFactory)
            TalkScreen(
                viewModel = vm,
                onOpenSettings = { nav.navigate("settings") },
            )
        }
        composable("settings") {
            val vm: SettingsViewModel = viewModel(factory = settingsFactory)
            SettingsScreen(
                viewModel = vm,
                onBack = { nav.popBackStack() },
            )
        }
    }
}
