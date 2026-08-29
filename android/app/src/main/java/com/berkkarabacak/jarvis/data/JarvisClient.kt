package com.berkkarabacak.jarvis.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * HTTP client for the existing Jarvis / Control Room contract.
 *
 * Talk: POST `/api/executive/runtime/missions` then
 *       POST `/api/executive/runtime/sessions/{id}/messages`
 * Settings: GET/PUT `/api/jarvis/settings`
 * Health: GET `/api/jarvis/health`
 *
 * Auth: `X-Api-Key` (same header as the web/API clients).
 */
class JarvisClient(
    private val connectionStore: ConnectionStore,
    private val http: OkHttpClient = defaultHttp(),
    private val json: Json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    },
) {
    suspend fun health(): JarvisHealth = withContext(Dispatchers.IO) {
        val obj = getJson("/api/jarvis/health")
        JarvisJson.healthFrom(obj)
    }

    suspend fun getSettings(): JarvisSettings = withContext(Dispatchers.IO) {
        val obj = getJson("/api/jarvis/settings")
        JarvisJson.settingsFrom(obj)
    }

    suspend fun putSettings(update: JarvisSettingsUpdate): JarvisSettings =
        withContext(Dispatchers.IO) {
            val body = JarvisJson.settingsUpdateBody(update)
            val obj = putJson("/api/jarvis/settings", body)
            JarvisJson.settingsFrom(obj)
        }

    suspend fun openTalkSession(brief: String = ""): TalkSession =
        withContext(Dispatchers.IO) {
            val body = JsonObject(
                buildMap {
                    if (brief.isNotBlank()) {
                        put("brief", JsonPrimitive(brief))
                    }
                },
            )
            val obj = postJson("/api/executive/runtime/missions", body)
            val session = JarvisJson.talkSessionFrom(obj)
            if (session.sessionId.isBlank()) {
                throw JarvisApiException("talk session is missing session_id")
            }
            session
        }

    suspend fun sendMessage(sessionId: String, message: String): TalkReply =
        withContext(Dispatchers.IO) {
            val body = JsonObject(mapOf("message" to JsonPrimitive(message)))
            val path = "/api/executive/runtime/sessions/${sessionId.trim()}/messages"
            val obj = postJson(path, body)
            val reply = JarvisJson.talkReplyFrom(obj)
            if (reply.text.isBlank()) {
                throw JarvisApiException("Jarvis returned an empty reply")
            }
            reply
        }

    private fun getJson(path: String): JsonObject {
        val request = authorized(Request.Builder().url(url(path)).get()).build()
        return execute(request)
    }

    private fun putJson(path: String, body: JsonObject): JsonObject {
        val request = authorized(
            Request.Builder()
                .url(url(path))
                .put(json.encodeToString(JsonObject.serializer(), body).toJsonBody()),
        ).build()
        return execute(request)
    }

    private fun postJson(path: String, body: JsonObject): JsonObject {
        val request = authorized(
            Request.Builder()
                .url(url(path))
                .post(json.encodeToString(JsonObject.serializer(), body).toJsonBody()),
        ).build()
        return execute(request)
    }

    private fun authorized(builder: Request.Builder): Request.Builder {
        val key = connectionStore.load().apiKey.trim()
        if (key.isNotEmpty()) {
            builder.header("X-Api-Key", key)
        }
        builder.header("Accept", "application/json")
        return builder
    }

    private fun url(path: String): String {
        val base = connectionStore.load().normalizedBaseUrl()
        if (base.isEmpty()) {
            throw JarvisApiException("Set the Jarvis server address in Settings")
        }
        val suffix = if (path.startsWith("/")) path else "/$path"
        return base + suffix
    }

    private fun execute(request: Request): JsonObject {
        http.newCall(request).execute().use { response ->
            val raw = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw JarvisApiException(publicError(response.code, raw))
            }
            if (raw.isBlank()) {
                throw JarvisApiException("empty response from Jarvis")
            }
            return try {
                json.parseToJsonElement(raw).jsonObject
            } catch (exc: Exception) {
                throw JarvisApiException("Jarvis returned a response this app cannot read", exc)
            }
        }
    }

    private fun publicError(code: Int, raw: String): String {
        val detail = try {
            json.parseToJsonElement(raw).jsonObject["detail"]
                ?.let { el -> (el as? JsonPrimitive)?.content }
                ?.trim()
                .orEmpty()
        } catch (_: Exception) {
            ""
        }
        return when {
            detail.isNotEmpty() -> detail
            code == 401 -> "The API key was rejected"
            code == 404 -> "Jarvis could not find that conversation"
            else -> "Jarvis request failed ($code)"
        }
    }

    companion object {
        fun defaultHttp(): OkHttpClient {
            return OkHttpClient.Builder()
                .connectTimeout(20, TimeUnit.SECONDS)
                .readTimeout(90, TimeUnit.SECONDS)
                .writeTimeout(30, TimeUnit.SECONDS)
                .build()
        }
    }
}

class JarvisApiException(message: String, cause: Throwable? = null) : IOException(message, cause)

private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

private fun String.toJsonBody() = toRequestBody(JSON_MEDIA)
