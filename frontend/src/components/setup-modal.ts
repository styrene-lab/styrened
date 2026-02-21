// Setup modal — single-screen first-run configuration

import { fetchSetupStatus, updateConfig } from '../api'

const DISMISSED_KEY = 'styrene-setup-dismissed'
const MAX_NAME_LEN = 100

const MODES: Record<string, string> = {
  standalone: 'Auto-discovery on local network',
  hub: 'Act as a transport relay for other nodes',
  peer: 'Connect to an existing hub',
}

// State — never read back from DOM
let displayName = ''
let deploymentMode = 'standalone'

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function buildModeOptions(): string {
  return Object.entries(MODES)
    .map(
      ([value, desc]) =>
        `<option value="${value}"${value === deploymentMode ? ' selected' : ''}>${value.toUpperCase()} — ${desc}</option>`,
    )
    .join('')
}

function renderPreview(): string {
  const name = displayName.trim() || '(not set)'
  const mode = deploymentMode.toUpperCase()
  return `
    <div class="setup-preview">
      <div class="setup-preview-title">WILL BE SAVED</div>
      <div class="setup-preview-row"><span class="setup-preview-label">DISPLAY NAME</span><span class="setup-preview-value">${escapeHtml(name)}</span></div>
      <div class="setup-preview-row"><span class="setup-preview-label">MODE</span><span class="setup-preview-value">${escapeHtml(mode)}</span></div>
    </div>
  `
}

function createModalHTML(): string {
  return `
    <div class="modal-overlay" id="setup-overlay">
      <div class="modal-dialog setup-dialog">
        <div class="modal-header">
          <span class="panel-title">FIRST-RUN SETUP</span>
          <button id="setup-dismiss-btn" class="modal-close">&times;</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label class="form-label" for="setup-display-name">DISPLAY NAME</label>
            <input type="text" id="setup-display-name" class="form-input" placeholder="My Styrene Node" maxlength="${MAX_NAME_LEN}" />
            <div class="setup-field-row">
              <span class="setup-field-hint">How other nodes see you on the mesh</span>
              <span class="setup-char-count" id="setup-char-count">0 / ${MAX_NAME_LEN}</span>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label" for="setup-mode">DEPLOYMENT MODE</label>
            <select id="setup-mode" class="form-select">${buildModeOptions()}</select>
            <span class="setup-field-hint">${escapeHtml(MODES[deploymentMode])}</span>
          </div>
          <div id="setup-preview">${renderPreview()}</div>
          <div class="setup-error" id="setup-error"></div>
        </div>
        <div class="modal-footer">
          <button id="setup-skip-btn" class="modal-btn">SKIP</button>
          <button id="setup-save-btn" class="modal-btn modal-btn-primary">SAVE</button>
        </div>
      </div>
    </div>
  `
}

function updatePreview(): void {
  const el = document.getElementById('setup-preview')
  if (el) el.innerHTML = renderPreview()
}

function updateCharCount(): void {
  const el = document.getElementById('setup-char-count')
  if (el) el.textContent = `${displayName.length} / ${MAX_NAME_LEN}`
}

function clearError(): void {
  const el = document.getElementById('setup-error')
  if (el) el.textContent = ''
}

function showError(msg: string): void {
  const el = document.getElementById('setup-error')
  if (el) el.textContent = msg
}

function bindEvents(): void {
  const nameInput = document.getElementById('setup-display-name') as HTMLInputElement
  const modeSelect = document.getElementById('setup-mode') as HTMLSelectElement

  nameInput?.addEventListener('input', () => {
    displayName = nameInput.value
    updateCharCount()
    updatePreview()
    clearError()
  })

  modeSelect?.addEventListener('change', () => {
    deploymentMode = modeSelect.value
    // Update the hint below the select
    const hint = modeSelect.parentElement?.querySelector('.setup-field-hint')
    if (hint) hint.textContent = MODES[deploymentMode] ?? ''
    updatePreview()
  })

  document.getElementById('setup-dismiss-btn')?.addEventListener('click', dismiss)
  document.getElementById('setup-skip-btn')?.addEventListener('click', dismiss)
  document.getElementById('setup-save-btn')?.addEventListener('click', handleSave)
}

function dismiss(): void {
  const overlay = document.getElementById('setup-overlay')
  if (overlay) overlay.remove()
  localStorage.setItem(DISMISSED_KEY, 'true')
}

async function handleSave(): Promise<void> {
  clearError()

  const name = displayName.trim()
  if (!name) {
    showError('Display name is required')
    return
  }
  if (name.length > MAX_NAME_LEN) {
    showError(`Display name must be ${MAX_NAME_LEN} characters or less`)
    return
  }

  const saveBtn = document.getElementById('setup-save-btn') as HTMLButtonElement
  if (saveBtn) {
    saveBtn.disabled = true
    saveBtn.textContent = 'SAVING...'
  }

  try {
    await updateConfig({
      identity: { display_name: name },
      reticulum: { mode: deploymentMode },
    })
    // Success — close modal, don't set dismissed flag (setup is actually complete)
    const overlay = document.getElementById('setup-overlay')
    if (overlay) overlay.remove()
  } catch (e: any) {
    showError(`Save failed: ${e.message}`)
    if (saveBtn) {
      saveBtn.disabled = false
      saveBtn.textContent = 'SAVE'
    }
  }
}

export async function checkAndShow(): Promise<void> {
  if (localStorage.getItem(DISMISSED_KEY) === 'true') return

  try {
    const status = await fetchSetupStatus()
    if (status.is_complete) return
  } catch {
    return
  }

  // Reset state
  displayName = ''
  deploymentMode = 'standalone'

  document.body.insertAdjacentHTML('beforeend', createModalHTML())
  bindEvents()
}
