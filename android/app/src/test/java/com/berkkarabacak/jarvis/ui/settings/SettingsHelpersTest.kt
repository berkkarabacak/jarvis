package com.berkkarabacak.jarvis.ui.settings

import com.berkkarabacak.jarvis.billing.PlayCatalog
import com.berkkarabacak.jarvis.billing.SubscribePlan
import com.berkkarabacak.jarvis.data.BudgetStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SettingsHelpersTest {
    @Test
    fun parseCapTreatsBlankAndZeroAsNoLimit() {
        assertNull(parseCap(""))
        assertNull(parseCap("0"))
        assertEquals(20.0, parseCap("20"))
        assertEquals(2.5, parseCap("2.5"))
    }

    @Test
    fun spendLabelDoesNotInventNumbers() {
        assertNull(spendLabel(null, monthly = true))
        assertNull(
            spendLabel(
                BudgetStatus(
                    monthlyCapUsd = null,
                    monthlySpentUsd = null,
                    monthlyRemainingUsd = null,
                    dailyCapUsd = null,
                    dailySpentUsd = null,
                    dailyRemainingUsd = null,
                    hit = null,
                    nearCap = null,
                    action = null,
                ),
                monthly = true,
            ),
        )
        assertEquals(
            "Spent $3.50 of $20 this month.",
            spendLabel(
                BudgetStatus(
                    monthlyCapUsd = 20.0,
                    monthlySpentUsd = 3.5,
                    monthlyRemainingUsd = 16.5,
                    dailyCapUsd = null,
                    dailySpentUsd = null,
                    dailyRemainingUsd = null,
                    hit = false,
                    nearCap = false,
                    action = "ok",
                ),
                monthly = true,
            ),
        )
    }

    @Test
    fun subscribeLabelsCoverExactlyThreePlans() {
        val plans = PlayCatalog.PLANS.map { catalog ->
            SubscribePlan(
                productId = catalog.productId,
                title = catalog.title,
                priceLabel = catalog.fallbackPriceLabel,
                description = catalog.description,
                monthlyBudgetUsd = catalog.monthlyBudgetUsd,
                current = catalog.productId == PlayCatalog.FREE,
                purchasable = catalog.purchasable,
            )
        }
        assertEquals(3, plans.size)
        assertEquals("Current plan: Free", currentPlanLabel(plans.first()))
        assertEquals("Free · current", planChipLabel(plans[0]))
        assertEquals("$3", planChipLabel(plans[1]))
        assertEquals("$8", planChipLabel(plans[2]))
    }
}
