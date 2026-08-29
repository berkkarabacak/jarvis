package com.berkkarabacak.jarvis.billing

import com.berkkarabacak.jarvis.data.Connection
import com.berkkarabacak.jarvis.data.JarvisSettings
import com.berkkarabacak.jarvis.data.MemoryConnectionStore
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlayBillingCoordinatorTest {
    @Test
    fun playUnavailableShowsThreePlansAndDoesNotFakePaidPurchase() = runTest {
        val fake = FakeBillingClientPort(available = false)
        val writer = RecordingBudgetWriter()
        val coordinator = coordinator(fake, writer)
        coordinator.refresh(applyBudget = true)

        assertEquals(PlayCatalog.PRODUCT_IDS, coordinator.state.value.plans.map { it.productId })
        assertEquals(3, coordinator.state.value.plans.size)
        assertEquals(PlayCatalog.PLAY_NEEDED, coordinator.state.value.message)
        assertFalse(coordinator.state.value.playAvailable)
        assertEquals(PlayCatalog.FREE, coordinator.state.value.currentProductId)

        coordinator.subscribeNow(PlayCatalog.THREE, activity = null)
        coordinator.subscribeNow(PlayCatalog.EIGHT, activity = null)

        assertTrue(writer.amounts.isEmpty())
        assertTrue(fake.launchedProductIds.isEmpty())
        assertEquals(PlayCatalog.PLAY_NEEDED, coordinator.state.value.message)
    }

    @Test
    fun restoreQueriesExactlyThreeCatalogIds() = runTest {
        val fake = FakeBillingClientPort()
        val coordinator = coordinator(fake, RecordingBudgetWriter())
        coordinator.refresh(applyBudget = true)

        assertEquals(listOf(PlayCatalog.PRODUCT_IDS), fake.queriedProductIds)
        assertEquals(3, fake.queriedProductIds.single().size)
        assertFalse(fake.queriedProductIds.single().contains("jarvis_20"))
    }

    @Test
    fun restoreNoPurchaseIsFreeAndPutsMonthlyBudget1() = runTest {
        val fake = FakeBillingClientPort()
        val writer = RecordingBudgetWriter()
        val coordinator = coordinator(fake, writer)
        coordinator.refresh(applyBudget = true)

        assertEquals(PlayCatalog.FREE, coordinator.state.value.currentProductId)
        assertEquals(listOf(1.0), writer.amounts)
        assertEquals(setOf("monthly_budget_usd"), writer.keys)
    }

    @Test
    fun restoreThreePutsMonthlyBudget3() = runTest {
        val fake = FakeBillingClientPort(
            owned = mutableListOf(purchased(PlayCatalog.THREE)),
        )
        val writer = RecordingBudgetWriter()
        val coordinator = coordinator(fake, writer)
        coordinator.refresh(applyBudget = true)

        assertEquals(PlayCatalog.THREE, coordinator.state.value.currentProductId)
        assertEquals(listOf(3.0), writer.amounts)
        assertEquals(setOf("monthly_budget_usd"), writer.keys)
        assertEquals(listOf("token-jarvis_3"), fake.acknowledgedTokens)
    }

    @Test
    fun restoreEightPutsMonthlyBudget8() = runTest {
        val fake = FakeBillingClientPort(
            owned = mutableListOf(purchased(PlayCatalog.EIGHT)),
        )
        val writer = RecordingBudgetWriter()
        val coordinator = coordinator(fake, writer)
        coordinator.refresh(applyBudget = true)

        assertEquals(PlayCatalog.EIGHT, coordinator.state.value.currentProductId)
        assertEquals(listOf(8.0), writer.amounts)
        assertEquals(setOf("monthly_budget_usd"), writer.keys)
    }

    @Test
    fun purchaseThreePutsMonthlyBudget3() = runTest {
        val fake = FakeBillingClientPort()
        val writer = RecordingBudgetWriter()
        val coordinator = coordinator(fake, writer)
        coordinator.refresh(applyBudget = true)
        writer.amounts.clear()

        coordinator.subscribeNow(PlayCatalog.THREE, activity = null)
        assertEquals(listOf(PlayCatalog.THREE), fake.launchedProductIds)
        assertTrue(writer.amounts.isEmpty())

        coordinator.deliverPurchases(
            BillingPurchaseEvent(ok = true, purchases = listOf(purchased(PlayCatalog.THREE))),
        )

        assertEquals(PlayCatalog.THREE, coordinator.state.value.currentProductId)
        assertEquals(listOf(3.0), writer.amounts)
        assertEquals(setOf("monthly_budget_usd"), writer.keys)
        assertFalse(writer.keys.contains("model_preference"))
        assertFalse(writer.keys.contains("model_speed"))
        assertFalse(writer.keys.contains("budget"))
        assertFalse(writer.keys.contains("spend"))
    }

    @Test
    fun purchaseEightPutsMonthlyBudget8() = runTest {
        val fake = FakeBillingClientPort()
        val writer = RecordingBudgetWriter()
        val coordinator = coordinator(fake, writer)
        coordinator.refresh(applyBudget = true)
        writer.amounts.clear()

        coordinator.subscribeNow(PlayCatalog.EIGHT, activity = null)
        coordinator.deliverPurchases(
            BillingPurchaseEvent(ok = true, purchases = listOf(purchased(PlayCatalog.EIGHT))),
        )

        assertEquals(PlayCatalog.EIGHT, coordinator.state.value.currentProductId)
        assertEquals(listOf(8.0), writer.amounts)
    }

    @Test
    fun unknownFourthProductIsIgnored() = runTest {
        val fake = FakeBillingClientPort(
            products = defaultPlayProducts() + BillingProduct(
                productId = "jarvis_20",
                playPriceLabel = "$20.00",
                offerToken = "offer-20",
            ),
            owned = mutableListOf(purchased("jarvis_20")),
        )
        val writer = RecordingBudgetWriter()
        val coordinator = coordinator(fake, writer)
        coordinator.refresh(applyBudget = true)

        assertEquals(3, coordinator.state.value.plans.size)
        assertEquals(PlayCatalog.PRODUCT_IDS, coordinator.state.value.plans.map { it.productId })
        assertEquals(PlayCatalog.FREE, coordinator.state.value.currentProductId)
        assertEquals(listOf(1.0), writer.amounts)
        assertFalse(coordinator.state.value.plans.any { it.productId == "jarvis_20" })
    }

    @Test
    fun showsPlayPriceStringsWhenReturned() = runTest {
        val fake = FakeBillingClientPort()
        val coordinator = coordinator(fake, RecordingBudgetWriter())
        coordinator.refresh(applyBudget = true)

        val labels = coordinator.state.value.plans.associate { it.productId to it.priceLabel }
        assertEquals("Free", labels[PlayCatalog.FREE])
        assertEquals("$3.00", labels[PlayCatalog.THREE])
        assertEquals("$8.00", labels[PlayCatalog.EIGHT])
    }

    @Test
    fun missingOfferTokenDoesNotFakePaidPurchase() = runTest {
        val fake = FakeBillingClientPort(
            products = PlayCatalog.PLANS.map { plan ->
                BillingProduct(productId = plan.productId, playPriceLabel = plan.fallbackPriceLabel)
            },
        )
        val writer = RecordingBudgetWriter()
        val coordinator = coordinator(fake, writer)
        coordinator.refresh(applyBudget = true)
        writer.amounts.clear()

        coordinator.subscribeNow(PlayCatalog.THREE, activity = null)

        assertTrue(fake.launchedProductIds.isEmpty())
        assertTrue(writer.amounts.isEmpty())
        assertEquals(PlayCatalog.PLAY_NEEDED, coordinator.state.value.message)
    }

    @Test
    fun unconfiguredServerDoesNotPut() = runTest {
        val fake = FakeBillingClientPort()
        val writer = RecordingBudgetWriter()
        val coordinator = PlayBillingCoordinator(
            billing = fake,
            budgetWriter = writer,
            connectionStore = MemoryConnectionStore(),
        )
        coordinator.refresh(applyBudget = true)
        assertTrue(writer.amounts.isEmpty())
    }

    private fun coordinator(
        fake: FakeBillingClientPort,
        writer: RecordingBudgetWriter,
    ): PlayBillingCoordinator {
        return PlayBillingCoordinator(
            billing = fake,
            budgetWriter = writer,
            connectionStore = MemoryConnectionStore(
                Connection(baseUrl = "http://127.0.0.1:8787", apiKey = "test"),
            ),
        )
    }

    private fun purchased(productId: String): BillingPurchase {
        return BillingPurchase(
            productId = productId,
            purchaseToken = "token-$productId",
            acknowledged = false,
            purchased = true,
        )
    }
}

private class RecordingBudgetWriter : SettingsBudgetWriter {
    val amounts = mutableListOf<Double>()
    val keys = mutableSetOf<String>()

    override suspend fun writeMonthlyBudgetUsd(amount: Double): JarvisSettings {
        amounts += amount
        keys += "monthly_budget_usd"
        return JarvisSettings(
            permissionProfile = "personal",
            permissionProfiles = emptyList(),
            provider = "openrouter",
            providers = emptyList(),
            model = "",
            realtimeVoice = "",
            lookSpeed = "off",
            lookSpeeds = emptyList(),
            qualityVsPrice = "balanced",
            qualityVsPriceChoices = emptyList(),
            monthlyBudgetUsd = amount,
            dailyBudgetUsd = null,
            budget = null,
        )
    }
}
