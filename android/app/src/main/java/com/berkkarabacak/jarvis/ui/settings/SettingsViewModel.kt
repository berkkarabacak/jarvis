package com.berkkarabacak.jarvis.ui.settings

import android.app.Activity
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.berkkarabacak.jarvis.billing.PlayBillingCoordinator
import com.berkkarabacak.jarvis.billing.SubscribeUiState
import com.berkkarabacak.jarvis.data.BudgetStatus
import com.berkkarabacak.jarvis.data.Connection
import com.berkkarabacak.jarvis.data.ConnectionStore
import com.berkkarabacak.jarvis.data.JarvisApiException
import com.berkkarabacak.jarvis.data.JarvisClient
import com.berkkarabacak.jarvis.data.JarvisJson
import com.berkkarabacak.jarvis.data.JarvisSettings
import com.berkkarabacak.jarvis.data.JarvisSettingsUpdate
import com.berkkarabacak.jarvis.data.LookSpeedOption
import com.berkkarabacak.jarvis.data.PermissionProfileOption
import com.berkkarabacak.jarvis.data.QualityOption
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SettingsUiState(
    val baseUrl: String = "",
    val apiKey: String = "",
    val lookSpeed: String = "off",
    val lookSpeeds: List<LookSpeedOption> = emptyList(),
    val qualityVsPrice: String = "balanced",
    val qualityChoices: List<QualityOption> = emptyList(),
    val monthlyBudgetText: String = "",
    val dailyBudgetText: String = "",
    val budget: BudgetStatus? = null,
    val permissionProfile: String = "personal",
    val permissionProfiles: List<PermissionProfileOption> = emptyList(),
    val loadedFromServer: Boolean = false,
    val busy: Boolean = false,
    val status: String = "",
    val statusIsError: Boolean = false,
    val subscribe: SubscribeUiState = SubscribeUiState(),
)

class SettingsViewModel(
    private val client: JarvisClient,
    private val connectionStore: ConnectionStore,
    private val billing: PlayBillingCoordinator,
) : ViewModel() {
    private val _state = MutableStateFlow(SettingsUiState())
    val state: StateFlow<SettingsUiState> = _state

    init {
        val connection = connectionStore.load()
        _state.update {
            it.copy(
                baseUrl = connection.baseUrl,
                apiKey = connection.apiKey,
                subscribe = billing.state.value,
            )
        }
        viewModelScope.launch {
            billing.state.collect { subscribe ->
                _state.update { it.copy(subscribe = subscribe) }
            }
        }
        billing.start()
        if (connection.isConfigured()) {
            refreshFromServer()
        }
    }

    fun pickPlan(productId: String, activity: Activity?) {
        persistConnection()
        viewModelScope.launch {
            billing.subscribeNow(productId, activity)
            reloadSettingsIfConfigured()
        }
    }

    fun restorePurchases() {
        billing.restore()
        viewModelScope.launch { reloadSettingsIfConfigured() }
    }

    fun setBaseUrl(value: String) {
        _state.update { it.copy(baseUrl = value) }
    }

    fun setApiKey(value: String) {
        _state.update { it.copy(apiKey = value) }
    }

    fun setLookSpeed(value: String) {
        _state.update { it.copy(lookSpeed = value) }
    }

    fun setQualityVsPrice(value: String) {
        _state.update { it.copy(qualityVsPrice = value) }
    }

    fun setMonthlyBudgetText(value: String) {
        _state.update { it.copy(monthlyBudgetText = value) }
    }

    fun setDailyBudgetText(value: String) {
        _state.update { it.copy(dailyBudgetText = value) }
    }

    fun setPermissionProfile(value: String) {
        _state.update { it.copy(permissionProfile = value) }
    }

    fun persistConnection() {
        connectionStore.save(
            Connection(
                baseUrl = _state.value.baseUrl,
                apiKey = _state.value.apiKey,
            ),
        )
    }

    fun testConnection() {
        persistConnection()
        viewModelScope.launch {
            _state.update { it.copy(busy = true, status = "", statusIsError = false) }
            try {
                val health = client.health()
                _state.update {
                    it.copy(
                        busy = false,
                        status = if (health.ok) "Connected to Jarvis." else "Server answered, but Jarvis is not ready.",
                        statusIsError = !health.ok,
                    )
                }
                if (health.ok) {
                    loadSettingsQuiet()
                }
            } catch (exc: Exception) {
                _state.update {
                    it.copy(busy = false, status = publicError(exc), statusIsError = true)
                }
            }
        }
    }

    fun refreshFromServer() {
        persistConnection()
        viewModelScope.launch {
            _state.update { it.copy(busy = true, status = "", statusIsError = false) }
            try {
                loadSettingsQuiet()
                _state.update { it.copy(busy = false) }
            } catch (exc: Exception) {
                _state.update {
                    it.copy(
                        busy = false,
                        status = publicError(exc),
                        statusIsError = true,
                    )
                }
            }
        }
    }

    fun save() {
        persistConnection()
        viewModelScope.launch {
            _state.update { it.copy(busy = true, status = "", statusIsError = false) }
            try {
                val saved = client.putSettings(
                    JarvisSettingsUpdate(
                        permissionProfile = _state.value.permissionProfile,
                        lookSpeed = _state.value.lookSpeed,
                        qualityVsPrice = _state.value.qualityVsPrice,
                        monthlyBudgetUsd = parseCap(_state.value.monthlyBudgetText),
                        dailyBudgetUsd = parseCap(_state.value.dailyBudgetText),
                        writeMonthlyBudget = true,
                        writeDailyBudget = true,
                    ),
                )
                applyServer(saved)
                _state.update {
                    it.copy(busy = false, status = "Saved", statusIsError = false)
                }
            } catch (exc: Exception) {
                _state.update {
                    it.copy(busy = false, status = publicError(exc), statusIsError = true)
                }
            }
        }
    }

    private suspend fun reloadSettingsIfConfigured() {
        if (!connectionStore.load().isConfigured()) return
        try {
            loadSettingsQuiet()
        } catch (_: Exception) {
            // Billing already reported its own message.
        }
    }

    private suspend fun loadSettingsQuiet() {
        applyServer(client.getSettings())
    }

    private fun applyServer(settings: JarvisSettings) {
        _state.update {
            it.copy(
                lookSpeed = settings.lookSpeed.ifBlank { it.lookSpeed },
                lookSpeeds = settings.lookSpeeds.ifEmpty { it.lookSpeeds },
                qualityVsPrice = settings.qualityVsPrice.ifBlank { "balanced" },
                qualityChoices = settings.qualityVsPriceChoices.ifEmpty { JarvisJson.defaultQualityChoices() },
                monthlyBudgetText = capText(settings.monthlyBudgetUsd),
                dailyBudgetText = capText(settings.dailyBudgetUsd),
                budget = settings.budget,
                permissionProfile = settings.permissionProfile.ifBlank { it.permissionProfile },
                permissionProfiles = settings.permissionProfiles.ifEmpty { it.permissionProfiles },
                loadedFromServer = true,
            )
        }
    }

    companion object {
        fun factory(
            client: JarvisClient,
            connectionStore: ConnectionStore,
            billing: PlayBillingCoordinator,
        ): ViewModelProvider.Factory {
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return SettingsViewModel(client, connectionStore, billing) as T
                }
            }
        }
    }
}

internal fun parseCap(raw: String): Double? {
    val trimmed = raw.trim()
    if (trimmed.isEmpty()) return null
    return trimmed.toDoubleOrNull()?.takeIf { it > 0.0 }
}

internal fun capText(value: Double?): String {
    if (value == null || value <= 0.0) return ""
    return if (value == value.toLong().toDouble()) value.toLong().toString() else value.toString()
}

internal fun publicError(exc: Exception): String {
    val detail = (exc as? JarvisApiException)?.message?.trim().orEmpty()
    return detail.ifBlank { "Could not reach the Jarvis server." }
}
