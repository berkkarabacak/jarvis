package com.berkkarabacak.jarvis.billing

import android.app.Activity
import com.berkkarabacak.jarvis.data.ConnectionStore
import com.berkkarabacak.jarvis.data.JarvisSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class SubscribePlan(
    val productId: String,
    val title: String,
    val priceLabel: String,
    val description: String,
    val monthlyBudgetUsd: Double,
    val current: Boolean,
    val purchasable: Boolean,
    val offerToken: String? = null,
)

data class SubscribeUiState(
    val playAvailable: Boolean = false,
    val currentProductId: String = PlayCatalog.FREE,
    val plans: List<SubscribePlan> = defaultPlans(PlayCatalog.FREE),
    val message: String = "",
    val busy: Boolean = false,
)

class PlayBillingCoordinator(
    private val billing: BillingClientPort,
    private val budgetWriter: SettingsBudgetWriter,
    private val connectionStore: ConnectionStore,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate),
) {
    private val _state = MutableStateFlow(SubscribeUiState())
    val state: StateFlow<SubscribeUiState> = _state

    private val mutex = Mutex()
    private var collecting = false
    private val productsById = linkedMapOf<String, BillingProduct>()

    fun start() {
        if (!collecting) {
            collecting = true
            scope.launch {
                billing.purchases.collect { event -> handlePurchaseEvent(event) }
            }
        }
        scope.launch { refresh(applyBudget = true) }
    }

    fun restore() {
        scope.launch { refresh(applyBudget = true) }
    }

    suspend fun refresh(applyBudget: Boolean) {
        mutex.withLock {
            _state.update { it.copy(busy = true, message = "") }
            val availability = billing.connect()
            if (availability is BillingAvailability.Unavailable) {
                productsById.clear()
                _state.value = SubscribeUiState(
                    playAvailable = false,
                    currentProductId = PlayCatalog.FREE,
                    plans = defaultPlans(PlayCatalog.FREE),
                    message = availability.message.ifBlank { PlayCatalog.PLAY_NEEDED },
                    busy = false,
                )
                // Play did not confirm a plan. Do not write a cap and do not
                // fake a paid purchase.
                return
            }

            val queried = billing.querySubscriptionProducts(PlayCatalog.PRODUCT_IDS)
                .filter { PlayCatalog.isKnown(it.productId) }
            productsById.clear()
            queried.forEach { productsById[it.productId] = it }

            val owned = acknowledgeKnown(billing.querySubscriptionPurchases())
            val currentId = PlayCatalog.activeProductId(owned.map { it.productId })
            _state.value = SubscribeUiState(
                playAvailable = true,
                currentProductId = currentId,
                plans = plansFor(currentId),
                message = "",
                busy = false,
            )
            if (applyBudget) {
                writeBudget(currentId)
            }
        }
    }

    fun subscribe(productId: String, activity: Activity?) {
        scope.launch { subscribeNow(productId, activity) }
    }

    suspend fun subscribeNow(productId: String, activity: Activity?): JarvisSettings? {
        return mutex.withLock {
            val plan = PlayCatalog.plan(productId) ?: return@withLock null
            if (plan.productId == PlayCatalog.FREE) {
                return@withLock handleFreeTap()
            }
            if (!_state.value.playAvailable) {
                _state.update { it.copy(message = PlayCatalog.PLAY_NEEDED) }
                return@withLock null
            }
            if (_state.value.currentProductId == plan.productId) {
                _state.update { it.copy(message = "You're already on this plan.") }
                return@withLock null
            }
            val product = productsById[plan.productId]
            if (product?.offerToken.isNullOrBlank()) {
                _state.update { it.copy(message = PlayCatalog.PLAY_NEEDED) }
                return@withLock null
            }
            _state.update { it.copy(busy = true, message = "") }
            when (val launched = billing.launchPurchase(activity, product)) {
                BillingLaunchResult.Started -> {
                    _state.update { it.copy(busy = false) }
                    null
                }
                BillingLaunchResult.PlayUnavailable -> {
                    _state.update {
                        it.copy(busy = false, message = PlayCatalog.PLAY_NEEDED)
                    }
                    null
                }
                is BillingLaunchResult.Failed -> {
                    _state.update {
                        it.copy(
                            busy = false,
                            message = launched.message.ifBlank { PlayCatalog.PLAY_NEEDED },
                        )
                    }
                    null
                }
            }
        }
    }

    private suspend fun handleFreeTap(): JarvisSettings? {
        if (!_state.value.playAvailable) {
            _state.update { it.copy(message = PlayCatalog.PLAY_NEEDED) }
            return null
        }
        val current = _state.value.currentProductId
        if (current == PlayCatalog.THREE || current == PlayCatalog.EIGHT) {
            _state.update {
                it.copy(message = "Cancel the paid plan in Google Play to go back to Free.")
            }
            return null
        }
        showCurrent(PlayCatalog.FREE)
        return writeBudget(PlayCatalog.FREE)
    }

    internal suspend fun deliverPurchases(event: BillingPurchaseEvent) {
        handlePurchaseEvent(event)
    }

    private suspend fun handlePurchaseEvent(event: BillingPurchaseEvent) {
        mutex.withLock {
            if (event.userCanceled) {
                _state.update { it.copy(busy = false, message = "Subscribe was canceled.") }
                return
            }
            if (!event.ok) {
                _state.update {
                    it.copy(
                        busy = false,
                        message = event.message.ifBlank { PlayCatalog.PLAY_NEEDED },
                    )
                }
                return
            }
            val owned = acknowledgeKnown(event.purchases)
            if (owned.isEmpty()) {
                return
            }
            val currentId = PlayCatalog.activeProductId(owned.map { it.productId })
            showCurrent(currentId, message = "You're on the ${PlayCatalog.plan(currentId)?.title} plan.")
            writeBudget(currentId)
        }
    }

    private suspend fun acknowledgeKnown(purchases: List<BillingPurchase>): List<BillingPurchase> {
        return purchases.mapNotNull { purchase ->
            if (!purchase.purchased || !PlayCatalog.isKnown(purchase.productId)) {
                return@mapNotNull null
            }
            if (!purchase.acknowledged && purchase.purchaseToken.isNotBlank()) {
                billing.acknowledge(purchase.purchaseToken)
            }
            purchase.copy(acknowledged = true)
        }
    }

    private suspend fun writeBudget(productId: String): JarvisSettings? {
        val amount = PlayCatalog.monthlyBudgetUsd(productId) ?: return null
        if (!connectionStore.load().isConfigured()) {
            return null
        }
        return try {
            budgetWriter.writeMonthlyBudgetUsd(amount)
        } catch (_: Exception) {
            _state.update {
                it.copy(message = "Could not save the spend limit to Jarvis.")
            }
            null
        }
    }

    private fun showCurrent(productId: String, message: String = "") {
        _state.update {
            it.copy(
                currentProductId = productId,
                plans = plansFor(productId),
                busy = false,
                message = message,
            )
        }
    }

    private fun plansFor(currentId: String): List<SubscribePlan> {
        return PlayCatalog.PLANS.map { catalog ->
            val play = productsById[catalog.productId]
            SubscribePlan(
                productId = catalog.productId,
                title = catalog.title,
                priceLabel = play?.playPriceLabel?.takeIf { it.isNotBlank() }
                    ?: catalog.fallbackPriceLabel,
                description = catalog.description,
                monthlyBudgetUsd = catalog.monthlyBudgetUsd,
                current = catalog.productId == currentId,
                purchasable = catalog.purchasable,
                offerToken = play?.offerToken,
            )
        }
    }
}

internal fun defaultPlans(currentId: String): List<SubscribePlan> {
    return PlayCatalog.PLANS.map { catalog ->
        SubscribePlan(
            productId = catalog.productId,
            title = catalog.title,
            priceLabel = catalog.fallbackPriceLabel,
            description = catalog.description,
            monthlyBudgetUsd = catalog.monthlyBudgetUsd,
            current = catalog.productId == currentId,
            purchasable = catalog.purchasable,
        )
    }
}
