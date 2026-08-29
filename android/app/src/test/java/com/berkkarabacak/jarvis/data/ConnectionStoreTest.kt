package com.berkkarabacak.jarvis.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConnectionStoreTest {
    @Test
    fun memoryStoreSurvivesReload() {
        val store = MemoryConnectionStore()
        assertFalse(store.load().isConfigured())
        store.save(Connection(baseUrl = "http://192.168.1.20:8787/", apiKey = " secret "))
        val loaded = store.load()
        assertEquals("http://192.168.1.20:8787/", loaded.baseUrl)
        assertEquals(" secret ", loaded.apiKey)
        assertEquals("http://192.168.1.20:8787", loaded.normalizedBaseUrl())
        assertTrue(loaded.isConfigured())
    }
}
