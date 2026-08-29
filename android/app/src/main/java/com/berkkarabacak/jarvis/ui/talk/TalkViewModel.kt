package com.berkkarabacak.jarvis.ui.talk

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.berkkarabacak.jarvis.data.ConnectionStore
import com.berkkarabacak.jarvis.data.JarvisApiException
import com.berkkarabacak.jarvis.data.JarvisClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ChatLine(
    val fromUser: Boolean,
    val text: String,
)

data class TalkUiState(
    val draft: String = "",
    val lines: List<ChatLine> = emptyList(),
    val sending: Boolean = false,
    val status: String = "",
)

class TalkViewModel(
    private val client: JarvisClient,
    private val connectionStore: ConnectionStore,
) : ViewModel() {
    private val _state = MutableStateFlow(TalkUiState())
    val state: StateFlow<TalkUiState> = _state
    private var sessionId: String? = null

    fun setDraft(value: String) {
        _state.update { it.copy(draft = value) }
    }

    fun send() {
        val text = _state.value.draft.trim()
        if (text.isEmpty() || _state.value.sending) return
        if (!connectionStore.load().isConfigured()) {
            _state.update { it.copy(status = "Open Settings and enter the Jarvis server address first.") }
            return
        }
        _state.update {
            it.copy(
                draft = "",
                sending = true,
                status = "",
                lines = it.lines + ChatLine(fromUser = true, text = text),
            )
        }
        viewModelScope.launch {
            try {
                val sid = ensureSession(text)
                val reply = client.sendMessage(sid, text)
                sessionId = reply.sessionId.ifBlank { sid }
                _state.update {
                    it.copy(
                        sending = false,
                        lines = it.lines + ChatLine(fromUser = false, text = reply.text),
                    )
                }
            } catch (exc: Exception) {
                sessionId = null
                _state.update {
                    it.copy(
                        sending = false,
                        status = publicTalkError(exc),
                    )
                }
            }
        }
    }

    private suspend fun ensureSession(firstMessage: String): String {
        val existing = sessionId
        if (!existing.isNullOrBlank()) return existing
        val opened = client.openTalkSession(brief = firstMessage.take(200))
        sessionId = opened.sessionId
        return opened.sessionId
    }

    companion object {
        fun factory(client: JarvisClient, connectionStore: ConnectionStore): ViewModelProvider.Factory {
            return object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return TalkViewModel(client, connectionStore) as T
                }
            }
        }
    }
}

internal fun publicTalkError(exc: Exception): String {
    val detail = (exc as? JarvisApiException)?.message?.trim().orEmpty()
    return detail.ifBlank { "Jarvis could not answer. Check the server and try again." }
}
