package com.berkkarabacak.jarvis.billing

import com.berkkarabacak.jarvis.data.JarvisClient
import com.berkkarabacak.jarvis.data.JarvisSettings
import com.berkkarabacak.jarvis.data.JarvisSettingsUpdate

/**
 * Writes the plan's monthly cap through the live Settings persist API.
 * Never invents spend numbers or extra keys.
 */
fun interface SettingsBudgetWriter {
    suspend fun writeMonthlyBudgetUsd(amount: Double): JarvisSettings
}

class JarvisSettingsBudgetWriter(
    private val client: JarvisClient,
) : SettingsBudgetWriter {
    override suspend fun writeMonthlyBudgetUsd(amount: Double): JarvisSettings {
        return client.putSettings(
            JarvisSettingsUpdate(
                monthlyBudgetUsd = amount,
                writeMonthlyBudget = true,
            ),
        )
    }
}
