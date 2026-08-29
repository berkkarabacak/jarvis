package com.berkkarabacak.jarvis

import android.app.Application
import com.berkkarabacak.jarvis.billing.JarvisSettingsBudgetWriter
import com.berkkarabacak.jarvis.billing.PlayBillingClientPort
import com.berkkarabacak.jarvis.billing.PlayBillingCoordinator
import com.berkkarabacak.jarvis.data.JarvisClient
import com.berkkarabacak.jarvis.data.PrefsConnectionStore

class JarvisApplication : Application() {
    lateinit var connectionStore: PrefsConnectionStore
        private set
    lateinit var jarvisClient: JarvisClient
        private set
    lateinit var billing: PlayBillingCoordinator
        private set

    override fun onCreate() {
        super.onCreate()
        connectionStore = PrefsConnectionStore(this)
        jarvisClient = JarvisClient(connectionStore)
        billing = PlayBillingCoordinator(
            billing = PlayBillingClientPort(this),
            budgetWriter = JarvisSettingsBudgetWriter(jarvisClient),
            connectionStore = connectionStore,
        )
    }
}
