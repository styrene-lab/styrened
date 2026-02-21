// Status panel — local system dashboard

import {
  fetchSystemStatus,
  fetchReticulumStatus,
  fetchDisks,
  fetchNetworkInterfaces,
} from '../api'
import type { SystemStatus, ReticulumStatus, DiskInfo, NetworkInterface } from '../types'

let mounted = false
let refreshTimer: ReturnType<typeof setInterval> | null = null

function createHTML(): string {
  return `
    <div class="status-panel">
      <div class="status-panel-header">
        <span class="panel-title">SYSTEM STATUS</span>
      </div>
      <div class="status-cards">
        <div class="status-card" id="system-info-card">
          <div class="status-card-title">SYSTEM</div>
          <div class="status-card-body" id="system-info-body">
            <div class="output-placeholder">Loading...</div>
          </div>
        </div>
        <div class="status-card" id="rns-status-card">
          <div class="status-card-title">RETICULUM</div>
          <div class="status-card-body" id="rns-status-body">
            <div class="output-placeholder">Loading...</div>
          </div>
        </div>
        <div class="status-card" id="disk-info-card">
          <div class="status-card-title">DISKS</div>
          <div class="status-card-body" id="disk-info-body">
            <div class="output-placeholder">Loading...</div>
          </div>
        </div>
        <div class="status-card" id="network-info-card">
          <div class="status-card-title">NETWORK</div>
          <div class="status-card-body" id="network-info-body">
            <div class="output-placeholder">Loading...</div>
          </div>
        </div>
      </div>
    </div>
  `
}

function renderSystemInfo(info: SystemStatus): void {
  const el = document.getElementById('system-info-body')
  if (!el) return

  el.innerHTML = `
    <div class="status-grid">
      <div class="status-cell"><span class="output-label">HOSTNAME</span><span class="output-value">${escapeHtml(info.hostname)}</span></div>
      <div class="status-cell"><span class="output-label">PLATFORM</span><span class="output-value">${escapeHtml(info.platform)}</span></div>
      <div class="status-cell"><span class="output-label">CPU</span><span class="output-value">${escapeHtml(info.cpu_model)}</span></div>
      <div class="status-cell"><span class="output-label">CORES</span><span class="output-value">${info.cpu_cores}</span></div>
      <div class="status-cell"><span class="output-label">RAM</span><span class="output-value">${info.ram_total_gb} GB</span></div>
      <div class="status-cell"><span class="output-label">VERSION</span><span class="output-value">${escapeHtml(info.version)}</span></div>
      <div class="status-cell"><span class="output-label">UPTIME</span><span class="output-value">${formatUptime(info.uptime)}</span></div>
    </div>
  `
}

function renderReticulumStatus(status: ReticulumStatus): void {
  const el = document.getElementById('rns-status-body')
  if (!el) return

  const initClass = status.initialized ? 'success' : 'error'
  const transportLabel = status.transport_enabled ? 'ENABLED' : 'DISABLED'

  let interfaceRows = ''
  if (status.interfaces.length > 0) {
    interfaceRows = status.interfaces.map(i =>
      `<tr><td>${escapeHtml(i.name)}</td><td>${escapeHtml(i.type)}</td><td>${escapeHtml(i.status)}</td></tr>`
    ).join('')
  }

  el.innerHTML = `
    <div class="status-grid">
      <div class="status-cell"><span class="output-label">INITIALIZED</span><span class="output-value output-exit ${initClass}">${status.initialized ? 'YES' : 'NO'}</span></div>
      <div class="status-cell"><span class="output-label">TRANSPORT</span><span class="output-value">${transportLabel}</span></div>
      <div class="status-cell"><span class="output-label">IDENTITY</span><span class="output-value">${status.identity_hash ? status.identity_hash.slice(0, 16) + '...' : 'NONE'}</span></div>
      <div class="status-cell"><span class="output-label">PATHS</span><span class="output-value">${status.path_count}</span></div>
      <div class="status-cell"><span class="output-label">ANNOUNCES</span><span class="output-value">${status.announce_count}</span></div>
    </div>
    ${interfaceRows ? `<table class="status-table"><thead><tr><th>NAME</th><th>TYPE</th><th>STATUS</th></tr></thead><tbody>${interfaceRows}</tbody></table>` : ''}
  `
}

function renderDisks(disks: DiskInfo[]): void {
  const el = document.getElementById('disk-info-body')
  if (!el) return

  if (disks.length === 0) {
    el.innerHTML = '<div class="output-placeholder">No disks detected</div>'
    return
  }

  const rows = disks.map(d => `
    <tr>
      <td>${escapeHtml(d.name)}</td>
      <td>${escapeHtml(d.disk_type)}</td>
      <td>${d.size_gb} GB</td>
      <td>${d.mount_point ? escapeHtml(d.mount_point) : '-'}</td>
    </tr>
  `).join('')

  el.innerHTML = `
    <table class="status-table">
      <thead><tr><th>NAME</th><th>TYPE</th><th>SIZE</th><th>MOUNT</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `
}

function renderNetwork(interfaces: NetworkInterface[]): void {
  const el = document.getElementById('network-info-body')
  if (!el) return

  if (interfaces.length === 0) {
    el.innerHTML = '<div class="output-placeholder">No interfaces detected</div>'
    return
  }

  const rows = interfaces.map(i => `
    <tr>
      <td>${escapeHtml(i.name)}</td>
      <td>${escapeHtml(i.interface_type)}</td>
      <td>${escapeHtml(i.category)}</td>
      <td>${i.mac_address ? escapeHtml(i.mac_address) : '-'}</td>
      <td>${i.ip_address ? escapeHtml(i.ip_address) : '-'}</td>
    </tr>
  `).join('')

  el.innerHTML = `
    <table class="status-table">
      <thead><tr><th>NAME</th><th>TYPE</th><th>CATEGORY</th><th>MAC</th><th>IP</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `
}

async function refreshAll(): Promise<void> {
  if (!mounted) return

  try {
    const [sysStatus, rnsStatus, disks, network] = await Promise.all([
      fetchSystemStatus(),
      fetchReticulumStatus(),
      fetchDisks(),
      fetchNetworkInterfaces(),
    ])
    if (!mounted) return
    renderSystemInfo(sysStatus)
    renderReticulumStatus(rnsStatus)
    renderDisks(disks)
    renderNetwork(network)
  } catch (err: any) {
    console.error('Status refresh failed:', err)
  }
}

export async function mount(target: HTMLElement): Promise<void> {
  target.innerHTML = createHTML()
  mounted = true

  await refreshAll()

  // Auto-refresh every 30s
  refreshTimer = setInterval(refreshAll, 30000)
}

export function unmount(): void {
  mounted = false
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}
