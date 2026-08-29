package com.berkkarabacak.jarvis.billing

import com.berkkarabacak.jarvis.data.Connection
import com.berkkarabacak.jarvis.data.JarvisClient
import com.berkkarabacak.jarvis.data.JarvisJson
import com.berkkarabacak.jarvis.data.JarvisSettingsUpdate
import com.berkkarabacak.jarvis.data.MemoryConnectionStore
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class BillingSettingsPutTest {
    private val json = Json { ignoreUnknownKeys = true }
    private lateinit var server: MockWebServer
    private val puts = mutableListOf<JsonObject>()

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                if (request.path == "/api/jarvis/settings" && request.method == "PUT") {
                    val body = json.parseToJsonElement(request.body.readUtf8()).jsonObject
                    puts += body
                    val extra = body.keys - setOf(
                        "permission_profile",
                        "provider",
                        "model",
                        "model_lock",
                        "model_lock_pin",
                        "unlock_pin",
                        "realtime_voice",
                        "look_speed",
                        "quality_vs_price",
                        "monthly_budget_usd",
                        "daily_budget_usd",
                    )
                    check(extra.isEmpty()) { "billing sent unpublished Settings keys: $extra" }
                    check("model_preference" !in body && "model_speed" !in body)
                    return MockResponse()
                        .setResponseCode(200)
                        .setHeader("Content-Type", "application/json")
                        .setBody("""{"ok":true,"changed":["monthly_budget_usd"],"monthly_budget_usd":${body["monthly_budget_usd"]}}""")
                }
                return MockResponse().setResponseCode(404)
            }
        }
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun writerPutsOnlyMonthlyBudgetKey() = runBlocking {
        val store = MemoryConnectionStore(
            Connection(baseUrl = server.url("/").toString().trimEnd('/'), apiKey = "secret"),
        )
        val writer = JarvisSettingsBudgetWriter(JarvisClient(store))
        writer.writeMonthlyBudgetUsd(3.0)
        writer.writeMonthlyBudgetUsd(8.0)
        writer.writeMonthlyBudgetUsd(1.0)

        assertEquals(3, puts.size)
        puts.forEach { body ->
            assertEquals(setOf("monthly_budget_usd"), body.keys)
            assertFalse(body.containsKey("daily_budget_usd"))
            assertFalse(body.containsKey("budget"))
            assertFalse(body.containsKey("spend"))
            assertFalse(body.containsKey("model_preference"))
            assertFalse(body.containsKey("model_speed"))
        }
        assertEquals(3.0, puts[0]["monthly_budget_usd"]?.jsonPrimitive?.doubleOrNull)
        assertEquals(8.0, puts[1]["monthly_budget_usd"]?.jsonPrimitive?.doubleOrNull)
        assertEquals(1.0, puts[2]["monthly_budget_usd"]?.jsonPrimitive?.doubleOrNull)
    }

    @Test
    fun catalogCapsUseRealSettingsUpdateBody() {
        PlayCatalog.PLANS.forEach { plan ->
            val body = JarvisJson.settingsUpdateBody(
                JarvisSettingsUpdate(
                    monthlyBudgetUsd = plan.monthlyBudgetUsd,
                    writeMonthlyBudget = true,
                ),
            )
            assertEquals(setOf("monthly_budget_usd"), body.keys)
            assertEquals(plan.monthlyBudgetUsd, body["monthly_budget_usd"]?.jsonPrimitive?.doubleOrNull)
            assertFalse(body.containsKey("model_preference"))
            assertFalse(body.containsKey("model_speed"))
            assertTrue(body["monthly_budget_usd"] !is JsonNull)
        }
        assertEquals(3, PlayCatalog.PLANS.size)
    }
}
