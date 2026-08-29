package com.berkkarabacak.jarvis.billing

import android.app.Activity
import android.content.Context
import com.android.billingclient.api.AcknowledgePurchaseParams
import com.android.billingclient.api.AcknowledgePurchaseResponseListener
import com.android.billingclient.api.BillingClient
import com.android.billingclient.api.BillingClientStateListener
import com.android.billingclient.api.BillingFlowParams
import com.android.billingclient.api.BillingResult
import com.android.billingclient.api.PendingPurchasesParams
import com.android.billingclient.api.ProductDetails
import com.android.billingclient.api.ProductDetailsResponseListener
import com.android.billingclient.api.Purchase
import com.android.billingclient.api.PurchasesResponseListener
import com.android.billingclient.api.QueryProductDetailsParams
import com.android.billingclient.api.QueryPurchasesParams
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * Real Google Play Billing Library client.
 *
 * Sideloaded debug builds and machines without a Play developer account
 * get [BillingAvailability.Unavailable] instead of a crash.
 */
class PlayBillingClientPort(
    context: Context,
) : BillingClientPort {
    private val _purchases = MutableSharedFlow<BillingPurchaseEvent>(extraBufferCapacity = 16)
    override val purchases: SharedFlow<BillingPurchaseEvent> = _purchases

    private val detailsById = linkedMapOf<String, ProductDetails>()

    private val client: BillingClient = BillingClient.newBuilder(context.applicationContext)
        .setListener { result, purchaseList ->
            _purchases.tryEmit(eventFrom(result, purchaseList.orEmpty()))
        }
        .enablePendingPurchases(
            PendingPurchasesParams.newBuilder().enableOneTimeProducts().build(),
        )
        .enableAutoServiceReconnection()
        .build()

    override suspend fun connect(): BillingAvailability {
        return try {
            connectInternal()
        } catch (_: Exception) {
            BillingAvailability.Unavailable(PlayCatalog.PLAY_NEEDED)
        }
    }

    private suspend fun connectInternal(): BillingAvailability {
        if (client.isReady) {
            return featureOrUnavailable()
        }
        val setup = suspendCancellableCoroutine { cont ->
            client.startConnection(object : BillingClientStateListener {
                override fun onBillingSetupFinished(billingResult: BillingResult) {
                    if (cont.isActive) {
                        cont.resume(billingResult)
                    }
                }

                override fun onBillingServiceDisconnected() {
                    // enableAutoServiceReconnection handles retries.
                }
            })
        }
        if (setup.responseCode != BillingClient.BillingResponseCode.OK) {
            return BillingAvailability.Unavailable(publicConnectMessage(setup))
        }
        return featureOrUnavailable()
    }

    private fun featureOrUnavailable(): BillingAvailability {
        val feature = client.isFeatureSupported(BillingClient.FeatureType.SUBSCRIPTIONS)
        return if (feature.responseCode == BillingClient.BillingResponseCode.OK) {
            BillingAvailability.Ready
        } else {
            BillingAvailability.Unavailable(PlayCatalog.PLAY_NEEDED)
        }
    }

    override suspend fun querySubscriptionProducts(productIds: List<String>): List<BillingProduct> {
        if (productIds.isEmpty()) return emptyList()
        return try {
            val params = QueryProductDetailsParams.newBuilder()
                .setProductList(
                    productIds.map { id ->
                        QueryProductDetailsParams.Product.newBuilder()
                            .setProductId(id)
                            .setProductType(BillingClient.ProductType.SUBS)
                            .build()
                    },
                )
                .build()
            val result = queryProductDetails(params)
            if (result.first.responseCode != BillingClient.BillingResponseCode.OK) {
                return emptyList()
            }
            detailsById.clear()
            result.second.mapNotNull { details ->
                if (!PlayCatalog.isKnown(details.productId)) return@mapNotNull null
                detailsById[details.productId] = details
                BillingProduct(
                    productId = details.productId,
                    playTitle = details.name.takeIf { it.isNotBlank() } ?: details.title,
                    playPriceLabel = formattedPrice(details),
                    offerToken = offerToken(details),
                )
            }
        } catch (_: Exception) {
            emptyList()
        }
    }

    override suspend fun querySubscriptionPurchases(): List<BillingPurchase> {
        return try {
            val result = queryPurchases()
            if (result.first.responseCode != BillingClient.BillingResponseCode.OK) {
                return emptyList()
            }
            result.second.mapNotNull(::toKnownPurchase)
        } catch (_: Exception) {
            emptyList()
        }
    }

    override fun launchPurchase(activity: Activity?, product: BillingProduct): BillingLaunchResult {
        if (activity == null) {
            return BillingLaunchResult.Failed(PlayCatalog.PLAY_NEEDED)
        }
        val details = detailsById[product.productId]
        val token = product.offerToken ?: offerToken(details)
        if (details == null || token.isNullOrBlank()) {
            return BillingLaunchResult.PlayUnavailable
        }
        return try {
            val flowParams = BillingFlowParams.newBuilder()
                .setProductDetailsParamsList(
                    listOf(
                        BillingFlowParams.ProductDetailsParams.newBuilder()
                            .setProductDetails(details)
                            .setOfferToken(token)
                            .build(),
                    ),
                )
                .build()
            val launched = client.launchBillingFlow(activity, flowParams)
            when (launched.responseCode) {
                BillingClient.BillingResponseCode.OK -> BillingLaunchResult.Started
                BillingClient.BillingResponseCode.BILLING_UNAVAILABLE,
                BillingClient.BillingResponseCode.SERVICE_UNAVAILABLE,
                BillingClient.BillingResponseCode.FEATURE_NOT_SUPPORTED,
                -> BillingLaunchResult.PlayUnavailable
                else -> BillingLaunchResult.Failed(PlayCatalog.PLAY_NEEDED)
            }
        } catch (_: Exception) {
            BillingLaunchResult.PlayUnavailable
        }
    }

    override suspend fun acknowledge(purchaseToken: String): Boolean {
        if (purchaseToken.isBlank()) return false
        return try {
            val result = acknowledgePurchase(purchaseToken)
            result.responseCode == BillingClient.BillingResponseCode.OK
        } catch (_: Exception) {
            false
        }
    }

    override fun endConnection() {
        try {
            client.endConnection()
        } catch (_: Exception) {
            // Sideload / missing Play should not crash teardown.
        }
    }

    private fun eventFrom(result: BillingResult, purchases: List<Purchase>): BillingPurchaseEvent {
        return when (result.responseCode) {
            BillingClient.BillingResponseCode.OK -> BillingPurchaseEvent(
                ok = true,
                purchases = purchases.mapNotNull(::toKnownPurchase),
            )
            BillingClient.BillingResponseCode.USER_CANCELED -> BillingPurchaseEvent(
                ok = false,
                userCanceled = true,
            )
            else -> BillingPurchaseEvent(
                ok = false,
                message = PlayCatalog.PLAY_NEEDED,
            )
        }
    }

    private fun toKnownPurchase(purchase: Purchase): BillingPurchase? {
        val productId = purchase.products.firstOrNull { PlayCatalog.isKnown(it) } ?: return null
        return BillingPurchase(
            productId = productId,
            purchaseToken = purchase.purchaseToken,
            acknowledged = purchase.isAcknowledged,
            purchased = purchase.purchaseState == Purchase.PurchaseState.PURCHASED,
        )
    }

    private fun formattedPrice(details: ProductDetails): String? {
        val phase = details.subscriptionOfferDetails
            ?.firstOrNull()
            ?.pricingPhases
            ?.pricingPhaseList
            ?.firstOrNull()
        return phase?.formattedPrice?.takeIf { it.isNotBlank() }
    }

    private fun offerToken(details: ProductDetails?): String? {
        return details?.subscriptionOfferDetails
            ?.firstOrNull()
            ?.offerToken
            ?.takeIf { it.isNotBlank() }
    }

    private suspend fun queryProductDetails(
        params: QueryProductDetailsParams,
    ): Pair<BillingResult, List<ProductDetails>> {
        return suspendCancellableCoroutine { cont ->
            client.queryProductDetailsAsync(
                params,
                ProductDetailsResponseListener { billingResult, productDetailsResult ->
                    if (cont.isActive) {
                        cont.resume(billingResult to productDetailsResult.productDetailsList.orEmpty())
                    }
                },
            )
        }
    }

    private suspend fun queryPurchases(): Pair<BillingResult, List<Purchase>> {
        return suspendCancellableCoroutine { cont ->
            client.queryPurchasesAsync(
                QueryPurchasesParams.newBuilder()
                    .setProductType(BillingClient.ProductType.SUBS)
                    .build(),
                PurchasesResponseListener { billingResult, purchases ->
                    if (cont.isActive) {
                        cont.resume(billingResult to purchases.orEmpty())
                    }
                },
            )
        }
    }

    private suspend fun acknowledgePurchase(purchaseToken: String): BillingResult {
        return suspendCancellableCoroutine { cont ->
            client.acknowledgePurchase(
                AcknowledgePurchaseParams.newBuilder()
                    .setPurchaseToken(purchaseToken)
                    .build(),
                AcknowledgePurchaseResponseListener { billingResult ->
                    if (cont.isActive) {
                        cont.resume(billingResult)
                    }
                },
            )
        }
    }

    private fun publicConnectMessage(result: BillingResult): String {
        return when (result.responseCode) {
            BillingClient.BillingResponseCode.BILLING_UNAVAILABLE,
            BillingClient.BillingResponseCode.SERVICE_UNAVAILABLE,
            BillingClient.BillingResponseCode.FEATURE_NOT_SUPPORTED,
            BillingClient.BillingResponseCode.SERVICE_DISCONNECTED,
            -> PlayCatalog.PLAY_NEEDED
            else -> PlayCatalog.PLAY_NEEDED
        }
    }
}
