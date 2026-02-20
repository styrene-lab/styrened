// Contacts panel — contact CRUD + name resolution

import { fetchContacts, setContact, removeContact, resolveContact } from '../api'
import { contactStore, setContacts } from '../state'
import * as sse from '../sse'
import type { Contact } from '../types'

let mounted = false

function createHTML(): string {
  return `
    <div class="contacts-panel">
      <div class="contacts-header">
        <span class="panel-title">CONTACTS</span>
        <button id="add-contact-btn" class="modal-btn">+ ADD</button>
      </div>
      <div class="contacts-search">
        <input type="text" id="contact-search" class="form-input" placeholder="Search or resolve name..." />
        <button id="resolve-btn" class="modal-btn">RESOLVE</button>
      </div>
      <div class="contact-list" id="contact-list"></div>
      <div class="contact-edit-form hidden" id="contact-form">
        <div class="form-group">
          <label class="form-label">PEER HASH</label>
          <input type="text" id="form-peer-hash" class="form-input" placeholder="16-32 hex characters" />
        </div>
        <div class="form-group">
          <label class="form-label">ALIAS</label>
          <input type="text" id="form-alias" class="form-input" placeholder="Display name" maxlength="100" />
        </div>
        <div class="form-group">
          <label class="form-label">NOTES</label>
          <input type="text" id="form-notes" class="form-input" placeholder="Optional notes" maxlength="500" />
        </div>
        <div class="form-actions">
          <button id="form-cancel" class="modal-btn">CANCEL</button>
          <button id="form-save" class="modal-btn modal-btn-primary">SAVE</button>
        </div>
      </div>
    </div>
  `
}

function renderContactList(): void {
  const list = document.getElementById('contact-list')
  if (!list) return

  const contacts = contactStore.contacts

  if (contacts.length === 0) {
    list.innerHTML = '<div class="contacts-empty">No contacts yet</div>'
    return
  }

  list.innerHTML = contacts.map(c => `
    <div class="contact-item" data-peer="${c.peer_hash}">
      <div class="contact-info">
        <div class="contact-alias">${escapeHtml(c.alias)}</div>
        <div class="contact-hash">${c.peer_hash.slice(0, 16)}...</div>
        ${c.notes ? `<div class="contact-notes">${escapeHtml(c.notes)}</div>` : ''}
      </div>
      <div class="contact-actions">
        <button class="edit-contact-btn modal-btn modal-btn-small" data-peer="${c.peer_hash}">EDIT</button>
        <button class="remove-contact-btn modal-btn modal-btn-small modal-btn-danger" data-peer="${c.peer_hash}">DEL</button>
      </div>
    </div>
  `).join('')

  // Edit handlers
  list.querySelectorAll('.edit-contact-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation()
      const peer = (btn as HTMLElement).dataset.peer!
      const contact = contacts.find(c => c.peer_hash === peer)
      if (contact) showEditForm(contact)
    })
  })

  // Remove handlers
  list.querySelectorAll('.remove-contact-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation()
      const peer = (btn as HTMLElement).dataset.peer!
      try {
        await removeContact(peer)
        await refreshContacts()
      } catch (err) {
        console.error('Failed to remove contact:', err)
      }
    })
  })
}

function showEditForm(contact?: Contact): void {
  const form = document.getElementById('contact-form')
  const peerInput = document.getElementById('form-peer-hash') as HTMLInputElement
  const aliasInput = document.getElementById('form-alias') as HTMLInputElement
  const notesInput = document.getElementById('form-notes') as HTMLInputElement

  if (!form || !peerInput || !aliasInput || !notesInput) return

  if (contact) {
    peerInput.value = contact.peer_hash
    peerInput.disabled = true
    aliasInput.value = contact.alias
    notesInput.value = contact.notes || ''
  } else {
    peerInput.value = ''
    peerInput.disabled = false
    aliasInput.value = ''
    notesInput.value = ''
  }

  form.classList.remove('hidden')
}

function hideEditForm(): void {
  const form = document.getElementById('contact-form')
  if (form) form.classList.add('hidden')
}

async function handleSave(): Promise<void> {
  const peerInput = document.getElementById('form-peer-hash') as HTMLInputElement
  const aliasInput = document.getElementById('form-alias') as HTMLInputElement
  const notesInput = document.getElementById('form-notes') as HTMLInputElement

  if (!peerInput || !aliasInput) return

  const peerHash = peerInput.value.trim()
  const alias = aliasInput.value.trim()
  const notes = notesInput?.value.trim() || undefined

  if (!peerHash || !alias) return

  try {
    await setContact(peerHash, alias, notes)
    hideEditForm()
    await refreshContacts()
  } catch (err) {
    console.error('Failed to save contact:', err)
  }
}

async function handleResolve(): Promise<void> {
  const input = document.getElementById('contact-search') as HTMLInputElement
  if (!input) return

  const name = input.value.trim()
  if (name.length < 1) return

  try {
    const { peer_hash } = await resolveContact(name)
    if (peer_hash) {
      showEditForm()
      const peerInput = document.getElementById('form-peer-hash') as HTMLInputElement
      if (peerInput) {
        peerInput.value = peer_hash
        peerInput.disabled = true
      }
    }
  } catch (err) {
    console.error('Name resolution failed:', err)
  }
}

async function refreshContacts(): Promise<void> {
  try {
    const { contacts } = await fetchContacts()
    setContacts(contacts)
    renderContactList()
  } catch (err) {
    console.error('Failed to refresh contacts:', err)
  }
}

function onContactUpdated(): void {
  refreshContacts()
}

export async function mount(target: HTMLElement): Promise<void> {
  target.innerHTML = createHTML()
  mounted = true

  document.getElementById('add-contact-btn')?.addEventListener('click', () => showEditForm())
  document.getElementById('form-cancel')?.addEventListener('click', hideEditForm)
  document.getElementById('form-save')?.addEventListener('click', handleSave)
  document.getElementById('resolve-btn')?.addEventListener('click', handleResolve)
  document.getElementById('contact-search')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleResolve()
  })

  sse.on('contact-updated', onContactUpdated)
  await refreshContacts()
}

export function unmount(): void {
  mounted = false
  sse.off('contact-updated', onContactUpdated)
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
