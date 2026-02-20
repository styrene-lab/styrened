// Mesh topology panel — graph + device list sidebar

import { fetchTopology, fetchMeshStatus, fetchDevices } from '../api'
import { renderNetwork, handleZoomIn, handleZoomOut, handleZoomFit, updateNode } from '../graph/graph'
import * as sse from '../sse'
import type { MeshDevice, MeshStatus } from '../types'

let mounted = false
let statusInterval: ReturnType<typeof setInterval> | null = null

function createHTML(): string {
  return `
    <div class="topology-panel">
      <div class="topology-graph-area">
        <div id="network-container"></div>
        <div class="graph-controls">
          <div class="zoom-controls">
            <button class="zoom-btn" id="zoom-in" title="Zoom in">+</button>
            <button class="zoom-btn" id="zoom-out" title="Zoom out">\u2212</button>
            <button class="zoom-btn zoom-fit" id="zoom-fit" title="Fit to view">\u2922</button>
          </div>
        </div>
        <div class="loading-container" id="loading">
          <div class="loading-spinner"></div>
          <div class="loading-text">LOADING MESH<span class="cursor">_</span></div>
        </div>
      </div>
      <div class="topology-sidebar">
        <div class="sidebar-header">
          <span class="sidebar-title">DEVICES</span>
          <span class="sidebar-count" id="device-count">0</span>
        </div>
        <div class="device-list" id="device-list"></div>
        <div class="sidebar-stats" id="mesh-stats"></div>
      </div>
    </div>
  `
}

function renderDeviceList(devices: MeshDevice[]): void {
  const list = document.getElementById('device-list')
  const count = document.getElementById('device-count')
  if (!list) return
  if (count) count.textContent = String(devices.length)

  list.innerHTML = devices.map(d => `
    <div class="device-item ${d.status}">
      <div class="device-name">${escapeHtml(d.name || d.destination_hash.slice(0, 16))}</div>
      <div class="device-meta">
        <span class="device-type">${d.type}</span>
        <span class="device-status ${d.status}">${d.status.toUpperCase()}</span>
      </div>
      ${d.last_seen_display ? `<div class="device-seen">${escapeHtml(d.last_seen_display)}</div>` : ''}
    </div>
  `).join('')
}

function renderStats(status: MeshStatus): void {
  const el = document.getElementById('mesh-stats')
  if (!el) return
  const uptime = formatUptime(status.uptime)
  el.innerHTML = `
    <div class="stat-row"><span class="stat-label">UPTIME</span><span class="stat-value">${uptime}</span></div>
    <div class="stat-row"><span class="stat-label">ACTIVE</span><span class="stat-value active">${status.active}</span></div>
    <div class="stat-row"><span class="stat-label">STALE</span><span class="stat-value stale">${status.stale}</span></div>
    <div class="stat-row"><span class="stat-label">LOST</span><span class="stat-value lost">${status.lost}</span></div>
  `
}

async function loadTopology(): Promise<void> {
  const loading = document.getElementById('loading')
  const container = document.getElementById('network-container')
  if (!container) return

  try {
    loading?.classList.remove('hidden')
    const [topology, devices, status] = await Promise.all([
      fetchTopology(),
      fetchDevices(),
      fetchMeshStatus(),
    ])
    await renderNetwork(topology, container)
    renderDeviceList(devices)
    renderStats(status)
    loading?.classList.add('hidden')
  } catch (error: any) {
    console.error('Failed to load topology:', error)
    loading?.classList.add('hidden')
  }
}

function onDeviceUpdated(data: any): void {
  updateNode(data)
}

export function mount(target: HTMLElement): void {
  target.innerHTML = createHTML()
  mounted = true

  // Wire zoom controls
  document.getElementById('zoom-in')?.addEventListener('click', handleZoomIn)
  document.getElementById('zoom-out')?.addEventListener('click', handleZoomOut)
  document.getElementById('zoom-fit')?.addEventListener('click', handleZoomFit)

  // SSE handler
  sse.on('device-updated', onDeviceUpdated)

  // Refresh status periodically
  statusInterval = setInterval(async () => {
    try {
      const [devices, status] = await Promise.all([fetchDevices(), fetchMeshStatus()])
      renderDeviceList(devices)
      renderStats(status)
    } catch { /* ignore */ }
  }, 30000)

  loadTopology()
}

export function unmount(): void {
  mounted = false
  sse.off('device-updated', onDeviceUpdated)
  if (statusInterval) {
    clearInterval(statusInterval)
    statusInterval = null
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
