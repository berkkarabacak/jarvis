package com.berkkarabacak.jarvis.data

import android.content.Context

/**
 * Persists only the server pointer (URL + API key) across process death.
 *
 * This is not a copy of `jarvis_settings.json`. Settings fields are loaded
 * and saved through [JarvisClient] so the phone and the web page share one
 * persist API.
 */
class PrefsConnectionStore(context: Context) : ConnectionStore {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    override fun load(): Connection {
        return Connection(
            baseUrl = prefs.getString(KEY_BASE_URL, "").orEmpty(),
            apiKey = prefs.getString(KEY_API_KEY, "").orEmpty(),
        )
    }

    override fun save(connection: Connection) {
        prefs.edit()
            .putString(KEY_BASE_URL, connection.normalizedBaseUrl())
            .putString(KEY_API_KEY, connection.apiKey.trim())
            .apply()
    }

    companion object {
        private const val PREFS = "jarvis_server_connection"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_API_KEY = "api_key"
    }
}
