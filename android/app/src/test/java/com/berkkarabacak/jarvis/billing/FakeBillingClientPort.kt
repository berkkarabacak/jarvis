package com.berkkarabacak.jarvis.billing

import android.app.Activity
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow

/**
 * In-memory BillingClient for ORCH-388 tests. Never talks to Play Console.
 */
class FakeBillingClientPort(
    var available: Boolean = true,
    var products: List<BillingProduct> = defaultPlayProducts(),
    var owned: MutableList<BillingPurchase> = mutableListOf(),
    var acknowledgeFails: Boolean = false,
) : BillingClientPort {
    private val _purchases = MutableSharedFlow<BillingPurchaseEvent>(extraBufferCapacity = 16)
    override val purchases: SharedFlow<BillingPurchaseEvent> = _purchases

    val queriedProductIds = mutableListOf<List<String>>()
    val launchedProductIds = mutableListOf<String>()
    val acknowledgedTokens = mutableListOf<String>()
    var connectCalls = 0

    override suspend fun connect(): BillingAvailability {
        connectCalls += 1
        return if (available) {
            BillingAvailability.Ready
        } else {
            BillingAvailability.Unavailable(PlayCatalog.PLAY_NEEDED)
        }
    }

    override suspend fun querySubscriptionProducts(productIds: List<String>): List<BillingProduct> {
        queriedProductIds += productIds
        if (!available) return emptyList()
        return products.filter { it.productId in productIds }
    }

    override suspend fun querySubscriptionPurchases(): List<BillingPurchase> {
        if (!available) return emptyList()
        return owned.toList()
    }

    override fun launchPurchase(activity: Activity?, product: BillingProduct): BillingLaunchResult {
        launchedProductIds += product.productId
        if (!available) return BillingLaunchResult.PlayUnavailable
        if (product.offerToken.isNullOrBlank()) return BillingLaunchResult.PlayUnavailable
        return BillingLaunchResult.Started
    }

    override suspend fun acknowledge(purchaseToken: String): Boolean {
        acknowledgedTokens += purchaseToken
        return !acknowledgeFails
    }

    override fun endConnection() = Unit

    fun emitPurchased(productId: String, token: String = "token-$productId") {
        val purchase = BillingPurchase(
            productId = productId,
            purchaseToken = token,
            acknowledged = false,
            purchased = true,
        )
        owned.removeAll { it.productId == productId }
        owned += purchase
        _purchases.tryEmit(BillingPurchaseEvent(ok = true, purchases = listOf(purchase)))
    }

    fun emitCanceled() {
        _purchases.tryEmit(BillingPurchaseEvent(ok = false, userCanceled = true))
    }
}

internal fun defaultPlayProducts(): List<BillingProduct> {
    return PlayCatalog.PLANS.map { plan ->
        BillingProduct(
            productId = plan.productId,
            playTitle = plan.title,
            playPriceLabel = when (plan.productId) {
                PlayCatalog.FREE -> "Free"
                PlayCatalog.THREE -> "$3.00"
                PlayCatalog.EIGHT -> "$8.00"
                else -> plan.fallbackPriceLabel
            },
            offerToken = if (plan.purchasable) "offer-${plan.productId}" else null,
        )
    }
}
