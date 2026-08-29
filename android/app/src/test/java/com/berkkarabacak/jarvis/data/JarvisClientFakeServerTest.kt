package com.berkkarabacak.jarvis.data

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * Fake Jarvis server for the ORCH-380 persist + talk paths.
 * Settings survive a new client instance the way a process restart would.
 */
class JarvisClientFakeServerTest {
    private val json = Json { ignoreUnknownKeys = true }
    private lateinit var server: MockWebServer
    private lateinit var store: MemoryConnectionStore

    private val persisted = mutableMapOf<String, Any?>(
        "permission_profile" to "personal",
        "provider" to "openrouter",
        "model" to "openai/gpt-4.1-mini",
        "realtime_voice" to "marin",
        "look_speed" to "off",
        "quality_vs_price" to "balanced",
        "monthly_budget_usd" to null,
        "daily_budget_usd" to null,
        "month_usd" to 1.25,
        "day_usd" to 0.4,
    )

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                return when {
                    request.path == "/api/jarvis/health" && request.method == "GET" ->
                        jsonOk("""{"ok":true,"realtime":false,"tools":true,"gateway":true}""")
                    request.path == "/api/jarvis/settings" && request.method == "GET" ->
                        jsonOk(settingsPayload())
                    request.path == "/api/jarvis/settings" && request.method == "PUT" -> {
                        val body = json.parseToJsonElement(request.body.readUtf8()).jsonObject
                        forbidGuessedKeys(body)
                        for (key in listOf(
                            "permission_profile",
                            "provider",
                            "model",
                            "realtime_voice",
                            "look_speed",
                            "quality_vs_price",
                        )) {
                            body[key]?.jsonPrimitive?.contentOrNull?.let { persisted[key] = it }
                        }
                        if ("monthly_budget_usd" in body) {
                            persisted["monthly_budget_usd"] = capValue(body["monthly_budget_usd"])
                        }
                        if ("daily_budget_usd" in body) {
                            persisted["daily_budget_usd"] = capValue(body["daily_budget_usd"])
                        }
                        jsonOk(settingsPayload(ok = true, changed = body.keys.sorted()))
                    }
                    request.path == "/api/executive/runtime/missions" && request.method == "POST" ->
                        jsonOk(
                            """
                            {
                              "session_id": "sess-android-1",
                              "mission_id": "mission-android-1",
                              "status": "active"
                            }
                            """.trimIndent(),
                        )
                    request.path == "/api/executive/runtime/sessions/sess-android-1/messages" &&
                        request.method == "POST" -> {
                        val body = json.parseToJsonElement(request.body.readUtf8()).jsonObject
                        val message = body["message"]?.jsonPrimitive?.contentOrNull.orEmpty()
                        jsonOk(
                            """
                            {
                              "contract": "orch.executive.chat",
                              "contract_version": "1.0",
                              "message": {
                                "message_id": "msg-1",
                                "session_id": "sess-android-1",
                                "text": "You said: $message",
                                "safety_filtered": false
                              }
                            }
                            """.trimIndent(),
                        )
                    }
                    else -> MockResponse().setResponseCode(404).setBody("""{"detail":"not found"}""")
                }
            }
        }
        server.start()
        store = MemoryConnectionStore(
            Connection(baseUrl = server.url("/").toString().trimEnd('/'), apiKey = "test-secret"),
        )
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun settingsSaveThenReloadAfterNewClient() = runBlocking {
        val first = JarvisClient(store)
        val before = first.getSettings()
        assertEquals("off", before.lookSpeed)
        assertEquals("balanced", before.qualityVsPrice)
        assertNull(before.monthlyBudgetUsd)
        assertEquals(1.25, before.budget?.monthlySpentUsd)

        val saved = first.putSettings(
            JarvisSettingsUpdate(
                lookSpeed = "30s",
                permissionProfile = "locked",
                qualityVsPrice = "smart",
                monthlyBudgetUsd = 20.0,
                dailyBudgetUsd = 2.0,
                writeMonthlyBudget = true,
                writeDailyBudget = true,
            ),
        )
        assertEquals("30s", saved.lookSpeed)
        assertEquals("locked", saved.permissionProfile)
        assertEquals("smart", saved.qualityVsPrice)
        assertEquals(20.0, saved.monthlyBudgetUsd)
        assertEquals(2.0, saved.dailyBudgetUsd)
        assertEquals(1.25, saved.budget?.monthlySpentUsd)
        assertTrue(saved.changed.contains("quality_vs_price"))

        val afterRestart = JarvisClient(store).getSettings()
        assertEquals("30s", afterRestart.lookSpeed)
        assertEquals("smart", afterRestart.qualityVsPrice)
        assertEquals(20.0, afterRestart.monthlyBudgetUsd)
        assertEquals(2.0, afterRestart.dailyBudgetUsd)
        assertEquals(1.25, afterRestart.budget?.monthlySpentUsd)
    }

    @Test
    fun talkOpensSessionAndSendsMessage() = runBlocking {
        val client = JarvisClient(store)
        val health = client.health()
        assertTrue(health.ok)

        val session = client.openTalkSession(brief = "hello")
        assertEquals("sess-android-1", session.sessionId)

        val reply = client.sendMessage(session.sessionId, "What is on my calendar?")
        assertEquals("You said: What is on my calendar?", reply.text)
        assertEquals("msg-1", reply.messageId)
    }

    @Test
    fun requestsSendApiKeyHeader() = runBlocking {
        JarvisClient(store).getSettings()
        val recorded = server.takeRequest()
        assertEquals("test-secret", recorded.getHeader("X-Api-Key"))
    }

    private fun settingsPayload(
        ok: Boolean = false,
        changed: List<String> = emptyList(),
    ): String {
        val monthly = persisted["monthly_budget_usd"]
        val daily = persisted["daily_budget_usd"]
        val monthUsd = persisted["month_usd"] as Double
        val dayUsd = persisted["day_usd"] as Double
        val monthlyJson = if (monthly is Number) monthly.toString() else "null"
        val dailyJson = if (daily is Number) daily.toString() else "null"
        val monthlyCapJson = monthlyJson
        val dailyCapJson = dailyJson
        val changedJson = changed.joinToString(prefix = "[", postfix = "]") { "\"$it\"" }
        return """
            {
              "config_version": 2,
              "permission_profile": "${persisted["permission_profile"]}",
              "permission_profiles": [
                {"id": "locked", "label": "Locked", "allows": "Read-only."},
                {"id": "personal", "label": "Personal", "allows": "Everyday help."},
                {"id": "power", "label": "Power", "allows": "Trusted."}
              ],
              "provider": "${persisted["provider"]}",
              "providers": ["openrouter", "openai", "xai"],
              "model": "${persisted["model"]}",
              "model_lock": false,
              "model_lock_pin_set": false,
              "realtime_voice": "${persisted["realtime_voice"]}",
              "look_speed": "${persisted["look_speed"]}",
              "look_speeds": [
                {"id": "off", "label": "Off", "allows": "Only when needed."},
                {"id": "30s", "label": "Every 30 seconds", "allows": "Look every 30s."}
              ],
              "quality_vs_price": "${persisted["quality_vs_price"]}",
              "quality_vs_price_choices": [
                {"id": "fast", "label": "Fast", "allows": "Cheaper."},
                {"id": "balanced", "label": "Balanced", "allows": "Middle."},
                {"id": "smart", "label": "Smart", "allows": "Harder."}
              ],
              "model_preference": "cheap_fast",
              "model_speed": "careful",
              "monthly_budget_usd": $monthlyJson,
              "daily_budget_usd": $dailyJson,
              "budget": {
                "monthly_cap_usd": $monthlyCapJson,
                "monthly_spent_usd": $monthUsd,
                "monthly_remaining_usd": null,
                "daily_cap_usd": $dailyCapJson,
                "daily_spent_usd": $dayUsd,
                "daily_remaining_usd": null,
                "hit": false,
                "near_cap": false,
                "action": "ok"
              },
              "ok": $ok,
              "changed": $changedJson
            }
        """.trimIndent()
    }

    private fun jsonOk(body: String): MockResponse {
        return MockResponse()
            .setResponseCode(200)
            .setHeader("Content-Type", "application/json")
            .setBody(body)
    }

    private fun capValue(el: kotlinx.serialization.json.JsonElement?): Double? {
        if (el == null || el is JsonNull) return null
        val n = el.jsonPrimitive.doubleOrNull ?: return null
        return if (n > 0.0) n else null
    }

    private fun forbidGuessedKeys(body: JsonObject) {
        val allowed = setOf(
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
        val extra = body.keys - allowed
        check(extra.isEmpty()) { "client sent unpublished Settings keys: $extra" }
        check("model_preference" !in body && "model_speed" !in body) {
            "client must not persist Windows aliases"
        }
    }
}
