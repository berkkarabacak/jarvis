package com.berkkarabacak.jarvis.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class JarvisSettingsContractTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun parsesOrch380SettingsAndBudgetObject() {
        val raw = """
            {
              "config_version": 2,
              "permission_profile": "personal",
              "permission_profiles": [
                {"id": "locked", "label": "Locked", "allows": "Read-only facts only."},
                {"id": "personal", "label": "Personal", "allows": "Everyday help."}
              ],
              "provider": "openrouter",
              "providers": ["openai", "openrouter", "xai"],
              "model": "openai/gpt-4.1-mini",
              "model_lock": false,
              "model_lock_pin_set": false,
              "realtime_voice": "marin",
              "look_speed": "10s",
              "look_speeds": [
                {"id": "off", "label": "Off", "allows": "Only when needed."},
                {"id": "10s", "label": "Every 10 seconds", "allows": "Look often."}
              ],
              "quality_vs_price": "smart",
              "quality_vs_price_choices": [
                {"id": "fast", "label": "Fast", "allows": "Cheaper."},
                {"id": "balanced", "label": "Balanced", "allows": "Middle."},
                {"id": "smart", "label": "Smart", "allows": "Harder."}
              ],
              "monthly_budget_usd": 20,
              "daily_budget_usd": 2,
              "budget": {
                "monthly_cap_usd": 20,
                "monthly_spent_usd": 3.5,
                "monthly_remaining_usd": 16.5,
                "daily_cap_usd": 2,
                "daily_spent_usd": 0.25,
                "daily_remaining_usd": 1.75,
                "hit": false,
                "near_cap": false,
                "action": "ok"
              },
              "model_lock_pin": "should-never-appear",
              "invented_field": "nope"
            }
        """.trimIndent()

        val settings = JarvisJson.settingsFrom(json.parseToJsonElement(raw).jsonObject)
        assertEquals("personal", settings.permissionProfile)
        assertEquals("10s", settings.lookSpeed)
        assertEquals("smart", settings.qualityVsPrice)
        assertEquals(20.0, settings.monthlyBudgetUsd)
        assertEquals(2.0, settings.dailyBudgetUsd)
        assertEquals(3.5, settings.budget?.monthlySpentUsd)
        assertEquals(0.25, settings.budget?.dailySpentUsd)
        assertEquals("ok", settings.budget?.action)
        assertFalse(settings.modelLockPinSet)
    }

    @Test
    fun ignoresWindowsAliasesAndDoesNotMapThem() {
        val raw = """
            {
              "look_speed": "off",
              "quality_vs_price": "smart",
              "model_preference": "cheap_fast",
              "model_speed": "careful",
              "model_preferences": [{"id": "cheap_fast", "label": "Cheaper"}],
              "model_speeds": [{"id": "careful", "label": "Careful"}]
            }
        """.trimIndent()
        val settings = JarvisJson.settingsFrom(json.parseToJsonElement(raw).jsonObject)
        assertEquals("smart", settings.qualityVsPrice)
        assertEquals("off", settings.lookSpeed)
        val body = JarvisJson.settingsUpdateBody(
            JarvisSettingsUpdate(
                lookSpeed = settings.lookSpeed,
                qualityVsPrice = settings.qualityVsPrice,
            ),
        )
        assertEquals("smart", body["quality_vs_price"]?.jsonPrimitive?.content)
        assertEquals("off", body["look_speed"]?.jsonPrimitive?.content)
        assertFalse(body.containsKey("model_preference"))
        assertFalse(body.containsKey("model_speed"))
    }

    @Test
    fun unsetQualityDefaultsToBalancedWithoutReadingAlias() {
        val raw = """{"look_speed":"off","quality_vs_price":null,"model_preference":"cheap_fast","model_speed":"careful"}"""
        val settings = JarvisJson.settingsFrom(json.parseToJsonElement(raw).jsonObject)
        assertEquals("balanced", settings.qualityVsPrice)
        assertEquals("off", settings.lookSpeed)
    }

    @Test
    fun unsetQualityDefaultsToBalanced() {
        val raw = """{"look_speed":"off","quality_vs_price":null}"""
        val settings = JarvisJson.settingsFrom(json.parseToJsonElement(raw).jsonObject)
        assertEquals("balanced", settings.qualityVsPrice)
    }

    @Test
    fun zeroCapMeansNoLimit() {
        val raw = """{"monthly_budget_usd":0,"daily_budget_usd":null}"""
        val settings = JarvisJson.settingsFrom(json.parseToJsonElement(raw).jsonObject)
        assertNull(settings.monthlyBudgetUsd)
        assertNull(settings.dailyBudgetUsd)
    }

    @Test
    fun missingBudgetObjectIsNotFaked() {
        val raw = """{"look_speed":"off"}"""
        val settings = JarvisJson.settingsFrom(json.parseToJsonElement(raw).jsonObject)
        assertNull(settings.budget)
    }

    @Test
    fun putBodyUsesOnlyOrch380Keys() {
        val body = JarvisJson.settingsUpdateBody(
            JarvisSettingsUpdate(
                permissionProfile = "power",
                lookSpeed = "30s",
                qualityVsPrice = "fast",
                monthlyBudgetUsd = 20.0,
                dailyBudgetUsd = null,
                writeMonthlyBudget = true,
                writeDailyBudget = true,
            ),
        )
        assertEquals(
            setOf(
                "permission_profile",
                "look_speed",
                "quality_vs_price",
                "monthly_budget_usd",
                "daily_budget_usd",
            ),
            body.keys,
        )
        assertEquals("fast", body["quality_vs_price"]?.jsonPrimitive?.content)
        assertEquals(20.0, body["monthly_budget_usd"]?.jsonPrimitive?.doubleOrNull)
        assertEquals(JsonNull, body["daily_budget_usd"])
        assertFalse(body.containsKey("budget"))
        assertFalse(body.containsKey("budget_usd"))
        assertFalse(body.containsKey("model_preference"))
        assertFalse(body.containsKey("model_speed"))
        assertFalse(body.containsKey("cheap_fast"))
        assertFalse(body.containsKey("quality_mode"))
        assertFalse(body.containsKey("model_lock_pin"))
        assertFalse(body.containsKey("spend"))
    }

    @Test
    fun putOmitsUnsetFields() {
        val body = JarvisJson.settingsUpdateBody(
            JarvisSettingsUpdate(lookSpeed = "1s"),
        )
        assertEquals(setOf("look_speed"), body.keys)
        assertEquals("1s", body["look_speed"]?.toString()?.trim('"'))
    }

    @Test
    fun talkReplyReadsExecutiveMessageContract() {
        val raw = """
            {
              "contract": "orch.executive.chat",
              "contract_version": "1.0",
              "message": {
                "message_id": "msg-1",
                "session_id": "sess-1",
                "text": "Hello from Jarvis.",
                "safety_filtered": false
              }
            }
        """.trimIndent()
        val reply = JarvisJson.talkReplyFrom(json.parseToJsonElement(raw).jsonObject)
        assertEquals("Hello from Jarvis.", reply.text)
        assertEquals("msg-1", reply.messageId)
        assertEquals("sess-1", reply.sessionId)
    }

    @Test
    fun defaultLookSpeedsMatchWebLabels() {
        val ids = JarvisJson.defaultLookSpeeds().map { it.id }
        assertEquals(listOf("off", "30s", "10s", "1s"), ids)
        assertTrue(JarvisJson.defaultLookSpeeds().any { it.label == "Every 30 seconds" })
    }

    @Test
    fun defaultQualityIdsAreFastBalancedSmart() {
        assertEquals(listOf("fast", "balanced", "smart"), JarvisJson.defaultQualityChoices().map { it.id })
    }
}
