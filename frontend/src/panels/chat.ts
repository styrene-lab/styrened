// Chat panel — conversation list + message thread + OOO toggle

import {
  fetchConversations, fetchMessages, sendChat, markRead,
  fetchAutoReplyStatus, toggleAutoReply,
} from '../api'
import {
  chatStore, setConversations, setActiveConversation, setMessages,
  addMessage, subscribe, autoReplyStore, setAutoReplyState,
} from '../state'
import * as sse from '../sse'
import type { Conversation, Message } from '../types'

let mounted = false

function createHTML(): string {
  return `
    <div class="chat-panel">
      <div class="chat-sidebar">
        <div class="chat-sidebar-header">
          <span class="sidebar-title">CONVERSATIONS</span>
          <button id="ooo-toggle" class="auto-reply-btn" title="Out of Office">OOO</button>
        </div>
        <div id="ooo-popover" class="auto-reply-popover hidden">
          <div class="auto-reply-popover-header">
            <span class="sidebar-title">AUTO-REPLY</span>
            <label class="auto-reply-switch">
              <input type="checkbox" id="ooo-enabled" />
              <span class="auto-reply-switch-label" id="ooo-switch-label">OFF</span>
            </label>
          </div>
          <textarea id="ooo-message" class="form-input auto-reply-textarea" rows="3" maxlength="1024" placeholder="Auto-reply message..."></textarea>
          <div class="auto-reply-popover-footer">
            <button id="ooo-save" class="modal-btn modal-btn-primary modal-btn-small">SAVE</button>
            <button id="ooo-cancel" class="modal-btn modal-btn-small">CLOSE</button>
          </div>
        </div>
        <div class="conversation-list" id="conversation-list"></div>
      </div>
      <div class="chat-main">
        <div class="chat-header" id="chat-header">
          <span class="chat-peer-name">SELECT A CONVERSATION</span>
        </div>
        <div class="message-list" id="message-list"></div>
        <div class="chat-input-area" id="chat-input-area" style="display:none">
          <div class="delivery-selector">
            <select id="delivery-method" class="form-select-small">
              <option value="auto">AUTO</option>
              <option value="direct">DIRECT</option>
              <option value="propagated">PROPAGATED</option>
            </select>
          </div>
          <input type="text" id="chat-input" class="form-input" placeholder="Type a message..." maxlength="65536" />
          <button id="send-btn" class="modal-btn modal-btn-primary">SEND</button>
        </div>
      </div>
    </div>
  `
}

function updateOOOButton(): void {
  const btn = document.getElementById('ooo-toggle')
  if (!btn) return
  if (autoReplyStore.enabled) {
    btn.classList.add('active')
  } else {
    btn.classList.remove('active')
  }
}

function updateOOOPopover(): void {
  const checkbox = document.getElementById('ooo-enabled') as HTMLInputElement
  const textarea = document.getElementById('ooo-message') as HTMLTextAreaElement
  const label = document.getElementById('ooo-switch-label')
  if (checkbox) checkbox.checked = autoReplyStore.enabled
  if (textarea) textarea.value = autoReplyStore.message
  if (label) label.textContent = autoReplyStore.enabled ? 'ON' : 'OFF'
}

function toggleOOOPopover(): void {
  const popover = document.getElementById('ooo-popover')
  if (!popover) return
  const isHidden = popover.classList.contains('hidden')
  if (isHidden) {
    updateOOOPopover()
    popover.classList.remove('hidden')
  } else {
    popover.classList.add('hidden')
  }
}

async function handleOOOSave(): Promise<void> {
  const checkbox = document.getElementById('ooo-enabled') as HTMLInputElement
  const textarea = document.getElementById('ooo-message') as HTMLTextAreaElement
  if (!checkbox || !textarea) return

  try {
    const result = await toggleAutoReply(checkbox.checked, textarea.value || undefined)
    setAutoReplyState(result)
    updateOOOButton()
    const popover = document.getElementById('ooo-popover')
    popover?.classList.add('hidden')
  } catch (err) {
    console.error('Failed to update auto-reply:', err)
  }
}

function onOOOEnabledChange(): void {
  const checkbox = document.getElementById('ooo-enabled') as HTMLInputElement
  const label = document.getElementById('ooo-switch-label')
  if (label && checkbox) label.textContent = checkbox.checked ? 'ON' : 'OFF'
}

function renderConversationList(): void {
  const list = document.getElementById('conversation-list')
  if (!list) return

  const conversations = chatStore.conversations.sort(
    (a, b) => (b.last_message_time || 0) - (a.last_message_time || 0),
  )

  list.innerHTML = conversations.map(c => {
    const active = c.peer_hash === chatStore.activeConversation ? ' active' : ''
    const unread = c.unread_count > 0 ? `<span class="unread-badge">${c.unread_count}</span>` : ''
    const name = escapeHtml(c.display_name || c.peer_hash.slice(0, 16) + '...')
    const preview = c.last_message_preview
      ? escapeHtml(c.last_message_preview.slice(0, 40))
      : ''
    const direction = c.last_message_outgoing ? '\u2192 ' : ''

    return `
      <div class="conversation-item${active}" data-peer="${c.peer_hash}">
        <div class="conv-header">
          <span class="conv-name">${name}</span>
          ${unread}
        </div>
        <div class="conv-preview">${direction}${preview}</div>
      </div>
    `
  }).join('')

  // Click handlers
  list.querySelectorAll('.conversation-item').forEach(el => {
    el.addEventListener('click', () => {
      const peer = (el as HTMLElement).dataset.peer!
      openConversation(peer)
    })
  })
}

function renderMessages(): void {
  const list = document.getElementById('message-list')
  if (!list) return

  list.innerHTML = chatStore.messages.map(m => {
    const cls = m.is_outgoing ? 'outgoing' : 'incoming'
    const statusIcon = getStatusIcon(m.status)
    const time = formatTime(m.timestamp)
    const content = escapeHtml(m.content || '')
    const title = m.title ? `<div class="msg-title">${escapeHtml(m.title)}</div>` : ''
    const retry = m.status === 'failed' && m.is_outgoing
      ? `<button class="retry-btn" data-msg-id="${m.id}">\u21BB RETRY</button>`
      : ''

    return `
      <div class="message ${cls}" data-msg-id="${m.id}">
        ${title}
        <div class="msg-content">${content}</div>
        <div class="msg-meta">
          <span class="msg-time">${time}</span>
          ${m.is_outgoing ? `<span class="msg-status ${m.status}">${statusIcon}</span>` : ''}
          ${retry}
        </div>
      </div>
    `
  }).join('')

  // Scroll to bottom
  list.scrollTop = list.scrollHeight

  // Retry handlers
  list.querySelectorAll('.retry-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation()
      const msgId = parseInt((btn as HTMLElement).dataset.msgId!)
      try {
        const { retryMessage } = await import('../api')
        await retryMessage(msgId)
      } catch (err) {
        console.error('Retry failed:', err)
      }
    })
  })
}

async function openConversation(peerHash: string): Promise<void> {
  setActiveConversation(peerHash)

  const header = document.getElementById('chat-header')
  const inputArea = document.getElementById('chat-input-area')

  // Find display name
  const conv = chatStore.conversations.find(c => c.peer_hash === peerHash)
  const name = conv?.display_name || peerHash.slice(0, 16) + '...'

  if (header) header.innerHTML = `<span class="chat-peer-name">${escapeHtml(name)}</span>`
  if (inputArea) inputArea.style.display = 'flex'

  // Load messages
  try {
    const { messages } = await fetchMessages(peerHash)
    setMessages(messages)
    renderMessages()
  } catch (err) {
    console.error('Failed to load messages:', err)
  }

  // Mark as read
  if (conv && conv.unread_count > 0) {
    try {
      await markRead(peerHash)
      conv.unread_count = 0
      renderConversationList()
    } catch { /* ignore */ }
  }
}

async function handleSend(): Promise<void> {
  const input = document.getElementById('chat-input') as HTMLInputElement
  const method = document.getElementById('delivery-method') as HTMLSelectElement
  if (!input || !chatStore.activeConversation) return

  const content = input.value.trim()
  if (!content) return

  input.value = ''
  input.disabled = true

  try {
    await sendChat(chatStore.activeConversation, content, {
      delivery_method: method.value,
    })
    // Reload messages to get the sent message
    const { messages } = await fetchMessages(chatStore.activeConversation)
    setMessages(messages)
    renderMessages()
  } catch (err) {
    console.error('Send failed:', err)
  } finally {
    input.disabled = false
    input.focus()
  }
}

function onMessageEvent(data: any): void {
  // Refresh conversation list for any message event
  fetchConversations().then(({ conversations }) => {
    setConversations(conversations)
    renderConversationList()
  }).catch(() => {})

  // If the event is for the active conversation, refresh messages
  if (data.peer_hash === chatStore.activeConversation && chatStore.activeConversation) {
    fetchMessages(chatStore.activeConversation).then(({ messages }) => {
      setMessages(messages)
      renderMessages()
    }).catch(() => {})
  }
}

function onConversationUpdated(data: any): void {
  fetchConversations().then(({ conversations }) => {
    setConversations(conversations)
    renderConversationList()
  }).catch(() => {})
}

function onAutoReplyUpdated(data: any): void {
  setAutoReplyState({
    enabled: data.enabled,
    message: data.message,
    cooldown: autoReplyStore.cooldown,
  })
  updateOOOButton()
  updateOOOPopover()
}

export async function mount(target: HTMLElement): Promise<void> {
  target.innerHTML = createHTML()
  mounted = true

  // Load initial data
  try {
    const [{ conversations }, autoReply] = await Promise.all([
      fetchConversations(),
      fetchAutoReplyStatus(),
    ])
    setConversations(conversations)
    setAutoReplyState(autoReply)
    renderConversationList()
    updateOOOButton()
  } catch (err) {
    console.error('Failed to load chat data:', err)
  }

  // Wire OOO toggle
  document.getElementById('ooo-toggle')?.addEventListener('click', toggleOOOPopover)
  document.getElementById('ooo-save')?.addEventListener('click', handleOOOSave)
  document.getElementById('ooo-cancel')?.addEventListener('click', () => {
    document.getElementById('ooo-popover')?.classList.add('hidden')
  })
  document.getElementById('ooo-enabled')?.addEventListener('change', onOOOEnabledChange)

  // Wire input
  document.getElementById('send-btn')?.addEventListener('click', handleSend)
  document.getElementById('chat-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  })

  // SSE handlers
  sse.on('message-event', onMessageEvent)
  sse.on('conversation-updated', onConversationUpdated)
  sse.on('auto-reply-updated', onAutoReplyUpdated)
}

export function unmount(): void {
  mounted = false
  sse.off('message-event', onMessageEvent)
  sse.off('conversation-updated', onConversationUpdated)
  sse.off('auto-reply-updated', onAutoReplyUpdated)
}

// --- Helpers ---

function getStatusIcon(status: string): string {
  switch (status) {
    case 'pending': return '\u23F3'  // hourglass
    case 'sent': return '\u2713'      // check
    case 'delivered': return '\u2713\u2713' // double check
    case 'failed': return '\u2717'    // X
    default: return ''
  }
}

function formatTime(timestamp: number): string {
  const d = new Date(timestamp * 1000)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
