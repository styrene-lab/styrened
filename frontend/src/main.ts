// Styrened Web UI — entry point

import { fetchConfig, fetchIdentity } from './api'
import { addRoute, navigate, startRouter } from './router'
import { appState, setActivePanel, setConnectionStatus, setPublicMode } from './state'
import * as sse from './sse'
import { checkAndShow as checkSetup } from './components/setup-modal'
import type { Identity } from './types'

// Panel modules (lazy-loaded on first nav)
const panelModules = {
  topology: () => import('./panels/topology'),
  chat: () => import('./panels/chat'),
  contacts: () => import('./panels/contacts'),
  fleet: () => import('./panels/fleet'),
  settings: () => import('./panels/settings'),
  status: () => import('./panels/status'),
}

let currentPanel: string | null = null
let currentUnmount: (() => void) | null = null

const PRIVATE_PANELS = new Set(['chat', 'contacts', 'fleet'])

// --- Panel switching ---

async function switchPanel(panel: string, params: Record<string, string> = {}): Promise<void> {
  // Guard: redirect private panels to topology in public mode
  if (appState.publicMode && PRIVATE_PANELS.has(panel)) {
    navigate('#/topology')
    return
  }

  const container = document.getElementById('panel-container')
  if (!container) return

  // Unmount current panel
  if (currentUnmount) {
    currentUnmount()
    currentUnmount = null
  }

  currentPanel = panel
  setActivePanel(panel)
  updateNavActive(panel)

  // Show loading
  container.innerHTML = `
    <div class="loading-container">
      <div class="loading-spinner"></div>
      <div class="loading-text">LOADING<span class="cursor">_</span></div>
    </div>
  `

  try {
    const loader = panelModules[panel as keyof typeof panelModules]
    if (!loader) {
      container.innerHTML = '<div class="panel-error">UNKNOWN PANEL</div>'
      return
    }

    const mod = await loader()
    // Check that we're still on this panel (user may have navigated away during load)
    if (currentPanel !== panel) return

    await mod.mount(container)
    currentUnmount = mod.unmount

    // If chat panel with specific peer, open that conversation
    if (panel === 'chat' && params.peer) {
      // The chat panel will need to handle this — dispatch a custom event
      window.dispatchEvent(new CustomEvent('open-conversation', { detail: { peer: params.peer } }))
    }
  } catch (err) {
    console.error(`Failed to load panel ${panel}:`, err)
    if (currentPanel === panel) {
      container.innerHTML = `<div class="panel-error">FAILED TO LOAD ${panel.toUpperCase()}</div>`
    }
  }
}

// --- Navigation ---

function updateNavActive(panel: string): void {
  const nav = document.getElementById('nav-sidebar')
  if (!nav) return
  nav.querySelectorAll('.nav-item').forEach(el => {
    const p = (el as HTMLElement).dataset.panel
    el.classList.toggle('active', p === panel)
  })
}

// --- Public mode ---

function updateNavForPublicMode(publicMode: boolean): void {
  const hidePanels = ['chat', 'contacts', 'fleet']
  hidePanels.forEach(panel => {
    const el = document.querySelector(`.nav-item[data-panel="${panel}"]`) as HTMLElement
    if (el) el.style.display = publicMode ? 'none' : ''
  })

  const badge = document.getElementById('header-readonly-badge')
  const sep = badge?.previousElementSibling as HTMLElement | null

  if (publicMode) {
    // Add badge if not present
    const statsEl = document.getElementById('header-stats')
    if (statsEl && !badge) {
      const newSep = document.createElement('span')
      newSep.className = 'stat-sep'
      newSep.textContent = '|'
      const newBadge = document.createElement('span')
      newBadge.id = 'header-readonly-badge'
      newBadge.className = 'read-only-badge'
      newBadge.textContent = 'READ-ONLY'
      statsEl.appendChild(newSep)
      statsEl.appendChild(newBadge)
    }
  } else {
    // Remove badge if present
    if (sep) sep.remove()
    if (badge) badge.remove()
  }
}

// --- Header ---

function updateIdentity(identity: Identity): void {
  const el = document.getElementById('header-identity')
  if (el) el.textContent = identity.display_name || identity.destination_hash.slice(0, 16) + '...'
}

function updateConnectionStatus(status: string): void {
  const el = document.getElementById('header-status')
  const footer = document.getElementById('footer-connection')
  if (el) {
    el.textContent = status.toUpperCase()
    el.className = `stat-inline connection-${status}`
  }
  if (footer) {
    footer.textContent = `SSE: ${status.toUpperCase()}`
    footer.className = `footer-status connection-${status}`
  }
}

// --- SSE connection status ---

sse.onStatus((status) => {
  setConnectionStatus(status as typeof appState.connectionStatus)
  updateConnectionStatus(status)
})

// --- Initialize ---

async function init(): Promise<void> {
  // Setup routes
  addRoute('/topology', () => switchPanel('topology'))
  addRoute('/chat', () => switchPanel('chat'))
  addRoute('/chat/{peer}', (params) => switchPanel('chat', params))
  addRoute('/contacts', () => switchPanel('contacts'))
  addRoute('/fleet', () => switchPanel('fleet'))
  addRoute('/settings', () => switchPanel('settings'))
  addRoute('/status', () => switchPanel('status'))

  // Load identity and config in parallel
  try {
    const [identity, configResult] = await Promise.all([
      fetchIdentity(),
      fetchConfig().catch(() => null),
    ])
    appState.identity = identity
    updateIdentity(identity)

    if (configResult?.config?.api?.public_mode) {
      setPublicMode(true)
      updateNavForPublicMode(true)
    }
  } catch (err) {
    console.error('Failed to load identity:', err)
  }

  // Start SSE
  sse.connect()

  // Listen for config changes to re-check public mode
  sse.on('config-updated', async () => {
    try {
      const result = await fetchConfig()
      const isPublic = !!result?.config?.api?.public_mode
      if (isPublic !== appState.publicMode) {
        setPublicMode(isPublic)
        updateNavForPublicMode(isPublic)
      }
    } catch {
      // Ignore — SSE reconnect will retry
    }
  })

  // Check first-run setup
  checkSetup()

  // Start router (triggers first panel load)
  startRouter()
}

init()
