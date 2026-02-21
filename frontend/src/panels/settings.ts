// Settings panel — section-tabbed config editor

import { fetchConfig, fetchIdentity, updateConfig } from '../api'
import * as sse from '../sse'
import { appState } from '../state'

let mounted = false
let currentSection = 'reticulum'
let configData: Record<string, any> = {}
let profileValue = 'operator'
let identityData: { identity_hash: string; destination_hash: string; lxmf_destination_hash: string } | null = null
let sseHandler: ((data: any) => void) | null = null

const SECTIONS = [
  'reticulum', 'identity', 'rpc', 'discovery', 'chat',
  'api', 'ipc', 'notifications', 'lxmf', 'terminal',
]

// Enum field definitions — constrained to valid backend values
const ENUM_FIELDS: Record<string, Record<string, string[]>> = {
  _toplevel: {
    profile: ['operator', 'endpoint', 'hub'],
  },
  reticulum: {
    mode: ['standalone', 'hub', 'peer'],
  },
  identity: {
    provider: ['file', 'yubikey'],
  },
}

function createHTML(): string {
  const isPublic = appState.publicMode
  const disabledAttr = isPublic ? ' disabled' : ''

  const tabs = SECTIONS.map(s =>
    `<button class="settings-tab${s === currentSection ? ' active' : ''}" data-section="${s}">${s.toUpperCase()}</button>`
  ).join('')

  const profileOptions = ENUM_FIELDS._toplevel.profile.map(opt =>
    `<option value="${opt}" ${profileValue === opt ? 'selected' : ''}>${opt.toUpperCase()}</option>`
  ).join('')

  const headerAction = isPublic
    ? '<span class="read-only-badge">READ-ONLY</span>'
    : '<button id="settings-save-btn" class="modal-btn modal-btn-primary" disabled>SAVE</button>'

  return `
    <div class="settings-panel">
      <div class="settings-header">
        <span class="panel-title">CONFIGURATION</span>
        ${headerAction}
      </div>
      <div class="settings-field" style="padding: 0.5rem 1rem;">
        <label class="form-label" for="field-profile">PROFILE</label>
        <select id="field-profile" class="form-select settings-input" data-section="_toplevel" data-key="profile" data-type="string"${disabledAttr}>
          ${profileOptions}
        </select>
      </div>
      <div class="settings-tabs" id="settings-tabs">${tabs}</div>
      <div class="settings-form" id="settings-form">
        <div class="output-placeholder">Loading configuration...</div>
      </div>
      <div class="settings-toast" id="settings-toast"></div>
    </div>
  `
}

async function loadConfig(): Promise<void> {
  try {
    const [result, identity] = await Promise.all([
      fetchConfig(),
      fetchIdentity().catch(() => null),
    ])
    configData = result.config
    profileValue = configData.profile || 'operator'
    identityData = identity
    // Update profile dropdown without full re-render
    const profileSelect = document.getElementById('field-profile') as HTMLSelectElement
    if (profileSelect) profileSelect.value = profileValue
    renderSection(currentSection)
  } catch (err: any) {
    const form = document.getElementById('settings-form')
    if (form) form.innerHTML = `<div class="output-error">Failed to load config: ${escapeHtml(err.message)}</div>`
  }
}

function renderSection(section: string): void {
  const form = document.getElementById('settings-form')
  if (!form || !configData[section]) return

  currentSection = section
  updateTabActive()

  const data = configData[section]
  const fields = Object.entries(data)
    .filter(([key]) => key !== 'interfaces' && key !== 'propagation_node' && key !== 'yubikey' && key !== 'metrics')
    .map(([key, value]) => renderField(section, key, value))
    .join('')

  // Render nested objects
  let nested = ''
  if (data.interfaces) {
    nested += '<div class="settings-nested"><div class="output-label">INTERFACES</div>'
    nested += renderField(section, 'interfaces.auto', data.interfaces.auto)
    if (data.interfaces.server) {
      nested += '<div class="settings-nested"><div class="output-label">SERVER</div>'
      for (const [k, v] of Object.entries(data.interfaces.server)) {
        nested += renderField(section, `interfaces.server.${k}`, v)
      }
      nested += '</div>'
    }
    nested += '</div>'
  }
  if (data.propagation_node) {
    nested += '<div class="settings-nested"><div class="output-label">PROPAGATION NODE</div>'
    for (const [k, v] of Object.entries(data.propagation_node)) {
      nested += renderField(section, `propagation_node.${k}`, v)
    }
    nested += '</div>'
  }
  if (data.metrics) {
    nested += '<div class="settings-nested"><div class="output-label">METRICS</div>'
    for (const [k, v] of Object.entries(data.metrics)) {
      nested += renderField(section, `metrics.${k}`, v)
    }
    nested += '</div>'
  }

  // Show read-only identity hashes on the identity tab
  let identityInfo = ''
  if (section === 'identity' && identityData) {
    identityInfo = '<div class="settings-nested"><div class="output-label">ADDRESSES (READ-ONLY)</div>'
    identityInfo += renderReadonlyField('OPERATOR DESTINATION', identityData.destination_hash)
    identityInfo += renderReadonlyField('LXMF DELIVERY', identityData.lxmf_destination_hash)
    identityInfo += renderReadonlyField('IDENTITY HASH', identityData.identity_hash)
    identityInfo += '</div>'
  }

  form.innerHTML = fields + nested + identityInfo
  enableSaveButton()
}

function renderField(section: string, key: string, value: any): string {
  const id = `field-${section}-${key.replace(/\./g, '-')}`
  const label = key.replace(/_/g, ' ').toUpperCase()
  // Use the leaf key for enum lookup (e.g., 'mode' from 'reticulum.mode')
  const leafKey = key.split('.').pop() || key
  const disabledAttr = appState.publicMode ? ' disabled' : ''

  // Check for enum fields first
  const enumOptions = ENUM_FIELDS[section]?.[leafKey]
  if (enumOptions && typeof value === 'string') {
    const options = enumOptions.map(opt =>
      `<option value="${opt}" ${value === opt ? 'selected' : ''}>${opt.toUpperCase()}</option>`
    ).join('')
    return `
      <div class="settings-field">
        <label class="form-label" for="${id}">${label}</label>
        <select id="${id}" class="form-select settings-input" data-section="${section}" data-key="${key}" data-type="string"${disabledAttr}>
          ${options}
        </select>
      </div>
    `
  }

  if (typeof value === 'boolean') {
    return `
      <div class="settings-field">
        <label class="form-label" for="${id}">${label}</label>
        <select id="${id}" class="form-select settings-input" data-section="${section}" data-key="${key}" data-type="bool"${disabledAttr}>
          <option value="true" ${value ? 'selected' : ''}>TRUE</option>
          <option value="false" ${!value ? 'selected' : ''}>FALSE</option>
        </select>
      </div>
    `
  }

  if (typeof value === 'number') {
    return `
      <div class="settings-field">
        <label class="form-label" for="${id}">${label}</label>
        <input type="number" id="${id}" class="form-input settings-input" value="${value}"
               data-section="${section}" data-key="${key}" data-type="number"${disabledAttr} />
      </div>
    `
  }

  // String or other
  return `
    <div class="settings-field">
      <label class="form-label" for="${id}">${label}</label>
      <input type="text" id="${id}" class="form-input settings-input" value="${escapeHtml(String(value ?? ''))}"
             data-section="${section}" data-key="${key}" data-type="string"${disabledAttr} />
    </div>
  `
}

function renderReadonlyField(label: string, value: string): string {
  return `
    <div class="settings-field">
      <label class="form-label">${label}</label>
      <input type="text" class="form-input" value="${escapeHtml(value || '---')}" disabled readonly />
    </div>
  `
}

function enableSaveButton(): void {
  const btn = document.getElementById('settings-save-btn') as HTMLButtonElement
  if (btn) btn.disabled = false

  // Listen for changes
  document.querySelectorAll('.settings-input').forEach(el => {
    el.addEventListener('change', () => {
      if (btn) btn.disabled = false
    })
  })
}

function updateTabActive(): void {
  document.querySelectorAll('.settings-tab').forEach(el => {
    el.classList.toggle('active', (el as HTMLElement).dataset.section === currentSection)
  })
}

async function handleSave(): Promise<void> {
  const toast = document.getElementById('settings-toast')
  const changes: Record<string, any> = {}

  document.querySelectorAll('.settings-input').forEach(el => {
    const input = el as HTMLInputElement | HTMLSelectElement
    const section = input.dataset.section!
    const key = input.dataset.key!
    const type = input.dataset.type!

    let value: any
    if (type === 'bool') {
      value = input.value === 'true'
    } else if (type === 'number') {
      value = Number(input.value)
    } else {
      value = input.value
    }

    // Top-level fields (profile) go directly on the changes root
    if (section === '_toplevel') {
      changes[key] = value
      return
    }

    // Build nested structure from dot-notation keys
    if (!changes[section]) changes[section] = {}
    const parts = key.split('.')
    let target = changes[section]
    for (let i = 0; i < parts.length - 1; i++) {
      if (!target[parts[i]]) target[parts[i]] = {}
      target = target[parts[i]]
    }
    target[parts[parts.length - 1]] = value
  })

  try {
    const result = await updateConfig(changes)
    configData = result.config
    showToast('Configuration saved', 'success')
  } catch (err: any) {
    showToast(`Save failed: ${err.message}`, 'error')
  }
}

function showToast(message: string, type: 'success' | 'error'): void {
  const toast = document.getElementById('settings-toast')
  if (!toast) return
  toast.textContent = message
  toast.className = `settings-toast toast-${type} toast-visible`
  setTimeout(() => {
    toast.className = 'settings-toast'
  }, 3000)
}

function onTabClick(e: Event): void {
  const target = (e.target as HTMLElement).closest('.settings-tab') as HTMLElement
  if (!target) return
  const section = target.dataset.section
  if (section) renderSection(section)
}

export async function mount(target: HTMLElement): Promise<void> {
  target.innerHTML = createHTML()
  mounted = true

  document.getElementById('settings-tabs')?.addEventListener('click', onTabClick)
  document.getElementById('settings-save-btn')?.addEventListener('click', handleSave)

  // Listen for external config changes via SSE
  sseHandler = () => {
    loadConfig()
  }
  sse.on('config-updated', sseHandler)

  await loadConfig()
}

export function unmount(): void {
  mounted = false
  if (sseHandler) {
    sse.off('config-updated', sseHandler)
    sseHandler = null
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
