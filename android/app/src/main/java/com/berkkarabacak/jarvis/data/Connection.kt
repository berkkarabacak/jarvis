package com.berkkarabacak.jarvis.data

/**
 * How this phone reaches a Jarvis server. Not the shared Settings object.
 *
 * Server URL + API secret only. Jarvis settings (look_speed, profile, …)
 * live on GET/PUT `/api/jarvis/settings` and must not be mirrored here.
 */
data class Connection(
    val baseUrl: String,
    val apiKey: String,
) {
    fun normalizedBaseUrl(): String = baseUrl.trim().trimEnd('/')

    fun isConfigured(): Boolean = normalizedBaseUrl().isNotEmpty()
}

interface ConnectionStore {
    fun load(): Connection

    fun save(connection: Connection)
}

class MemoryConnectionStore(
    initial: Connection = Connection(baseUrl = "", apiKey = ""),
) : ConnectionStore {
    private var value: Connection = initial

    override fun load(): Connection = value

    override fun save(connection: Connection) {
        value = connection
    }
}
