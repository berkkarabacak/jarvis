package com.berkkarabacak.jarvis.billing

/**
 * ORCH-388 — exactly three Play Billing subscription products.
 *
 * Do not add a fourth product. Do not invent a Play Store listing URL.
 * Spend caps are written through GET/PUT `/api/jarvis/settings`
 * (`monthly_budget_usd` only). Windows aliases are not used.
 */
object PlayCatalog {
    const val FREE = "jarvis_free"
    const val THREE = "jarvis_3"
    const val EIGHT = "jarvis_8"

    const val PLAY_NEEDED = "Google Play is needed to subscribe"

    val PRODUCT_IDS: List<String> = listOf(FREE, THREE, EIGHT)

    data class Plan(
        val productId: String,
        val title: String,
        val fallbackPriceLabel: String,
        val monthlyBudgetUsd: Double,
        val description: String,
        val purchasable: Boolean,
    )

    val PLANS: List<Plan> = listOf(
        Plan(
            productId = FREE,
            title = "Free",
            fallbackPriceLabel = "Free",
            monthlyBudgetUsd = 1.0,
            description = "Try Jarvis, with a tiny spend cap.",
            purchasable = false,
        ),
        Plan(
            productId = THREE,
            title = "$3",
            fallbackPriceLabel = "$3",
            monthlyBudgetUsd = 3.0,
            description = "Spend limit.",
            purchasable = true,
        ),
        Plan(
            productId = EIGHT,
            title = "$8",
            fallbackPriceLabel = "$8",
            monthlyBudgetUsd = 8.0,
            description = "Spend limit.",
            purchasable = true,
        ),
    )

    fun plan(productId: String): Plan? = PLANS.firstOrNull { it.productId == productId }

    fun isKnown(productId: String): Boolean = plan(productId) != null

    fun monthlyBudgetUsd(productId: String): Double? = plan(productId)?.monthlyBudgetUsd

    /**
     * Paid plans win over Free. Unknown Play product IDs are ignored
     * (no fourth plan).
     */
    fun activeProductId(ownedProductIds: Collection<String>): String {
        val known = ownedProductIds.filter(::isKnown).toSet()
        return when {
            EIGHT in known -> EIGHT
            THREE in known -> THREE
            FREE in known -> FREE
            else -> FREE
        }
    }
}
