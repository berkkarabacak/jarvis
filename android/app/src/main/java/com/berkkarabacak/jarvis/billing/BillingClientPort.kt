package com.berkkarabacak.jarvis.billing

import android.app.Activity
import kotlinx.coroutines.flow.SharedFlow

/**
 * Narrow BillingClient surface so unit tests can use a fake without
 * Play Console or a device Google account.
 */
interface BillingClientPort {
    val purchases: SharedFlow<BillingPurchaseEvent>

    suspend fun connect(): BillingAvailability

    suspend fun querySubscriptionProducts(productIds: List<String>): List<BillingProduct>

    suspend fun querySubscriptionPurchases(): List<BillingPurchase>

    fun launchPurchase(activity: Activity?, product: BillingProduct): BillingLaunchResult

    suspend fun acknowledge(purchaseToken: String): Boolean

    fun endConnection()
}

sealed class BillingAvailability {
    data object Ready : BillingAvailability()
    data class Unavailable(val message: String = PlayCatalog.PLAY_NEEDED) : BillingAvailability()
}

data class BillingProduct(
    val productId: String,
    val playTitle: String? = null,
    val playPriceLabel: String? = null,
    val offerToken: String? = null,
)

data class BillingPurchase(
    val productId: String,
    val purchaseToken: String,
    val acknowledged: Boolean,
    val purchased: Boolean,
)

data class BillingPurchaseEvent(
    val ok: Boolean,
    val userCanceled: Boolean = false,
    val purchases: List<BillingPurchase> = emptyList(),
    val message: String = "",
)

sealed class BillingLaunchResult {
    data object Started : BillingLaunchResult()
    data object PlayUnavailable : BillingLaunchResult()
    data class Failed(val message: String) : BillingLaunchResult()
}
