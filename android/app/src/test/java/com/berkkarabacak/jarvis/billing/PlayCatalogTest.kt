package com.berkkarabacak.jarvis.billing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PlayCatalogTest {
    @Test
    fun exactlyThreeProductsNoFourth() {
        assertEquals(3, PlayCatalog.PRODUCT_IDS.size)
        assertEquals(3, PlayCatalog.PLANS.size)
        assertEquals(
            listOf("jarvis_free", "jarvis_3", "jarvis_8"),
            PlayCatalog.PRODUCT_IDS,
        )
        assertEquals(PlayCatalog.PRODUCT_IDS, PlayCatalog.PLANS.map { it.productId })
        assertFalse(PlayCatalog.isKnown("jarvis_20"))
        assertFalse(PlayCatalog.isKnown("premium"))
        assertFalse(PlayCatalog.isKnown("jarvis_5"))
        assertNull(PlayCatalog.monthlyBudgetUsd("jarvis_20"))
        assertNull(PlayCatalog.plan("yearly"))
    }

    @Test
    fun mapsFreeThreeEightToMonthlyBudgetOnly() {
        assertEquals(1.0, PlayCatalog.monthlyBudgetUsd(PlayCatalog.FREE))
        assertEquals(3.0, PlayCatalog.monthlyBudgetUsd(PlayCatalog.THREE))
        assertEquals(8.0, PlayCatalog.monthlyBudgetUsd(PlayCatalog.EIGHT))
        assertTrue(PlayCatalog.PLANS.none { it.monthlyBudgetUsd !in setOf(1.0, 3.0, 8.0) })
    }

    @Test
    fun activeProductIgnoresUnknownFourthId() {
        assertEquals(PlayCatalog.FREE, PlayCatalog.activeProductId(emptyList()))
        assertEquals(PlayCatalog.FREE, PlayCatalog.activeProductId(listOf("jarvis_99", "premium")))
        assertEquals(PlayCatalog.THREE, PlayCatalog.activeProductId(listOf("jarvis_3", "jarvis_99")))
        assertEquals(PlayCatalog.EIGHT, PlayCatalog.activeProductId(listOf("jarvis_3", "jarvis_8")))
        assertEquals(PlayCatalog.FREE, PlayCatalog.activeProductId(listOf("jarvis_free")))
    }
}
