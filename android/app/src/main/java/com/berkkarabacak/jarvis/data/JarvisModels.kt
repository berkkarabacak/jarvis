package com.berkkarabacak.jarvis.data

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Shared Jarvis Settings object from GET/PUT `/api/jarvis/settings`.
 *
 * Keys match `{JARVIS_WORKSPACE}/Memory/jarvis_settings.json` (`config_version` 2)
 * and `app.jarvis.settings_store`. Do not add a parallel schema.
 *
 * Quality and look-speed use only `quality_vs_price` and `look_speed`.
 * Ignore Windows aliases `model_preference` and `model_speed` — do not map
 * them and do not persist them.
 *
 * PUT may also send write-only `model_lock_pin` / `unlock_pin`. The PIN hash
 * is never returned and this client never displays it.
 */
data class JarvisSettings(
    val permissionProfile: String,
    val permissionProfiles: List<PermissionProfileOption>,
    val provider: String,
    val providers: List<String>,
    val model: String,
    val realtimeVoice: String,
    val lookSpeed: String,
    val lookSpeeds: List<LookSpeedOption>,
    val qualityVsPrice: String,
    val qualityVsPriceChoices: List<QualityOption>,
    val monthlyBudgetUsd: Double?,
    val dailyBudgetUsd: Double?,
    val budget: BudgetStatus?,
    val modelLock: Boolean = false,
    val modelLockPinSet: Boolean = false,
    val ok: Boolean? = null,
    val changed: List<String> = emptyList(),
)

data class PermissionProfileOption(
    val id: String,
    val label: String,
    val allows: String,
)

data class LookSpeedOption(
    val id: String,
    val label: String,
    val allows: String,
)

data class QualityOption(
    val id: String,
    val label: String,
    val allows: String,
)

/**
 * Spend so far vs cap from GET `/api/jarvis/settings` → `budget`.
 * Numbers come from the server. Do not invent spent amounts.
 */
data class BudgetStatus(
    val monthlyCapUsd: Double?,
    val monthlySpentUsd: Double?,
    val monthlyRemainingUsd: Double?,
    val dailyCapUsd: Double?,
    val dailySpentUsd: Double?,
    val dailyRemainingUsd: Double?,
    val hit: Boolean?,
    val nearCap: Boolean?,
    val action: String?,
)

/**
 * PUT body for `/api/jarvis/settings` (partial; extra="forbid" on the server).
 *
 * Caps: `0` or `null` means no limit. Never send `model_lock_pin` hash.
 */
data class JarvisSettingsUpdate(
    val permissionProfile: String? = null,
    val provider: String? = null,
    val model: String? = null,
    val realtimeVoice: String? = null,
    val lookSpeed: String? = null,
    val qualityVsPrice: String? = null,
    val monthlyBudgetUsd: Double? = null,
    val dailyBudgetUsd: Double? = null,
    val writeMonthlyBudget: Boolean = false,
    val writeDailyBudget: Boolean = false,
    val modelLock: Boolean? = null,
    val modelLockPin: String? = null,
    val unlockPin: String? = null,
)

data class JarvisHealth(
    val ok: Boolean,
    val realtime: Boolean? = null,
    val tools: Boolean? = null,
    val gateway: Boolean? = null,
)

data class TalkSession(
    val sessionId: String,
    val missionId: String,
    val status: String,
)

data class TalkReply(
    val text: String,
    val messageId: String,
    val sessionId: String,
)

internal object JarvisJson {
    private val WINDOWS_ALIAS_KEYS = setOf("model_preference", "model_speed")

    private val PUT_KEYS = linkedSetOf(
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

    fun settingsFrom(obj: JsonObject): JarvisSettings {
        val profiles = obj["permission_profiles"].asObjectList().map { item ->
            PermissionProfileOption(
                id = item.str("id"),
                label = item.str("label").ifBlank { item.str("id") },
                allows = item.str("allows"),
            )
        }
        val speeds = obj["look_speeds"].asObjectList().map { item ->
            LookSpeedOption(
                id = item.str("id"),
                label = item.str("label").ifBlank { item.str("id") },
                allows = item.str("allows"),
            )
        }
        val qualities = obj["quality_vs_price_choices"].asObjectList().map { item ->
            QualityOption(
                id = item.str("id"),
                label = item.str("label").ifBlank { item.str("id") },
                allows = item.str("allows"),
            )
        }
        // Read only the Android/web keys. Windows aliases in the same JSON
        // are ignored even when they disagree with quality_vs_price / look_speed.
        val quality = obj.str("quality_vs_price").ifBlank { "balanced" }
        return JarvisSettings(
            permissionProfile = obj.str("permission_profile"),
            permissionProfiles = profiles,
            provider = obj.str("provider"),
            providers = obj["providers"].asStringList(),
            model = obj.str("model"),
            realtimeVoice = obj.str("realtime_voice"),
            lookSpeed = obj.str("look_speed").ifBlank { "off" },
            lookSpeeds = speeds.ifEmpty { defaultLookSpeeds() },
            qualityVsPrice = if (quality in setOf("fast", "balanced", "smart")) quality else "balanced",
            qualityVsPriceChoices = qualities.ifEmpty { defaultQualityChoices() },
            monthlyBudgetUsd = obj.cap("monthly_budget_usd"),
            dailyBudgetUsd = obj.cap("daily_budget_usd"),
            budget = budgetFrom(obj["budget"] as? JsonObject),
            modelLock = obj["model_lock"]?.jsonPrimitive?.booleanOrNull ?: false,
            modelLockPinSet = obj["model_lock_pin_set"]?.jsonPrimitive?.booleanOrNull ?: false,
            ok = obj["ok"]?.jsonPrimitive?.booleanOrNull,
            changed = obj["changed"].asStringList(),
        )
    }

    fun settingsUpdateBody(update: JarvisSettingsUpdate): JsonObject {
        val fields = linkedMapOf<String, JsonElement>()
        update.permissionProfile?.let { fields["permission_profile"] = JsonPrimitive(it) }
        update.provider?.let { fields["provider"] = JsonPrimitive(it) }
        update.model?.let { fields["model"] = JsonPrimitive(it) }
        update.realtimeVoice?.let { fields["realtime_voice"] = JsonPrimitive(it) }
        update.lookSpeed?.let { fields["look_speed"] = JsonPrimitive(it) }
        update.qualityVsPrice?.let { fields["quality_vs_price"] = JsonPrimitive(it) }
        if (update.writeMonthlyBudget) {
            fields["monthly_budget_usd"] = capJson(update.monthlyBudgetUsd)
        }
        if (update.writeDailyBudget) {
            fields["daily_budget_usd"] = capJson(update.dailyBudgetUsd)
        }
        update.modelLock?.let { fields["model_lock"] = JsonPrimitive(it) }
        if (update.modelLockPin != null) {
            fields["model_lock_pin"] = JsonPrimitive(update.modelLockPin)
        }
        if (update.unlockPin != null) {
            fields["unlock_pin"] = JsonPrimitive(update.unlockPin)
        }
        check(fields.keys.none { it in WINDOWS_ALIAS_KEYS }) {
            "refusing to persist Windows aliases model_preference / model_speed"
        }
        check(fields.keys.all { it in PUT_KEYS }) {
            "refusing to send a Settings key that is not on the live persist API"
        }
        check("model_lock_pin" !in fields || fields["model_lock_pin"] is JsonPrimitive) {
            "PIN must be sent write-only as the plain 4-digit value"
        }
        return JsonObject(fields)
    }

    fun healthFrom(obj: JsonObject): JarvisHealth {
        return JarvisHealth(
            ok = obj["ok"]?.jsonPrimitive?.booleanOrNull ?: false,
            realtime = obj["realtime"]?.jsonPrimitive?.booleanOrNull,
            tools = obj["tools"]?.jsonPrimitive?.booleanOrNull,
            gateway = obj["gateway"]?.jsonPrimitive?.booleanOrNull,
        )
    }

    fun talkSessionFrom(obj: JsonObject): TalkSession {
        return TalkSession(
            sessionId = obj.str("session_id"),
            missionId = obj.str("mission_id"),
            status = obj.str("status"),
        )
    }

    fun talkReplyFrom(obj: JsonObject): TalkReply {
        val message = obj["message"]?.jsonObject ?: obj
        return TalkReply(
            text = message.str("text"),
            messageId = message.str("message_id"),
            sessionId = message.str("session_id").ifBlank { obj.str("session_id") },
        )
    }

    fun defaultLookSpeeds(): List<LookSpeedOption> = listOf(
        LookSpeedOption("off", "Off", "I only look when a job needs a picture."),
        LookSpeedOption("30s", "Every 30 seconds", "While I work on the screen, I look again every 30 seconds."),
        LookSpeedOption("10s", "Every 10 seconds", "While I work on the screen, I look again every 10 seconds."),
        LookSpeedOption("1s", "Every second", "While I work on the screen, I look again every second."),
    )

    fun defaultQualityChoices(): List<QualityOption> = listOf(
        QualityOption("fast", "Fast", "Cheaper and quicker. Good for everyday asks."),
        QualityOption("balanced", "Balanced", "A middle path — not the cheapest, not the most expensive."),
        QualityOption("smart", "Smart", "Thinks harder. May cost more."),
    )

    fun budgetFrom(obj: JsonObject?): BudgetStatus? {
        if (obj == null) return null
        val action = obj.str("action")
        return BudgetStatus(
            monthlyCapUsd = obj.num("monthly_cap_usd"),
            monthlySpentUsd = obj.num("monthly_spent_usd"),
            monthlyRemainingUsd = obj.num("monthly_remaining_usd"),
            dailyCapUsd = obj.num("daily_cap_usd"),
            dailySpentUsd = obj.num("daily_spent_usd"),
            dailyRemainingUsd = obj.num("daily_remaining_usd"),
            hit = obj["hit"]?.jsonPrimitive?.booleanOrNull,
            nearCap = obj["near_cap"]?.jsonPrimitive?.booleanOrNull,
            action = action.takeIf { it in setOf("ok", "cheaper", "stop") },
        )
    }

    private fun capJson(value: Double?): JsonElement {
        return if (value == null || value <= 0.0) JsonNull else JsonPrimitive(value)
    }

    private fun JsonObject.str(key: String): String {
        val el = this[key] ?: return ""
        val prim = el as? JsonPrimitive ?: return ""
        return prim.contentOrNull?.trim().orEmpty()
    }

    private fun JsonObject.num(key: String): Double? {
        val el = this[key] ?: return null
        if (el is JsonNull) return null
        val prim = el as? JsonPrimitive ?: return null
        return prim.doubleOrNull
    }

    private fun JsonObject.cap(key: String): Double? {
        val n = num(key) ?: return null
        return if (n > 0.0) n else null
    }

    private fun JsonElement?.asStringList(): List<String> {
        val arr = this as? JsonArray ?: return emptyList()
        return arr.mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.trim()?.takeIf { s -> s.isNotEmpty() } }
    }

    private fun JsonElement?.asObjectList(): List<JsonObject> {
        val arr = this as? JsonArray ?: return emptyList()
        return arr.mapNotNull { it as? JsonObject }
    }
}
