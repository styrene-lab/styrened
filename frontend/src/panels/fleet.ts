// Fleet panel — remote exec, device status, announce

import { fetchDevices, fleetExec, fleetStatus, announce } from '../api'
import type { MeshDevice, ExecResult, DeviceStatus } from '../types'

let mounted = false
let selectedDevice: string | null = null

function createHTML(): string {
  return `
    <div class="fleet-panel">
      <div class="fleet-header">
        <span class="panel-title">FLEET OPERATIONS</span>
        <button id="announce-btn" class="modal-btn modal-btn-primary">ANNOUNCE</button>
      </div>
      <div class="fleet-device-select">
        <label class="form-label">TARGET DEVICE</label>
        <select id="device-select" class="form-select">
          <option value="">-- Select device --</option>
        </select>
        <button id="device-status-btn" class="modal-btn" disabled>STATUS</button>
      </div>
      <div class="fleet-exec-area">
        <label class="form-label">REMOTE EXECUTE</label>
        <div class="exec-input-row">
          <input type="text" id="exec-command" class="form-input" placeholder="Command" />
          <input type="text" id="exec-args" class="form-input" placeholder="Args (space-separated)" />
          <input type="number" id="exec-timeout" class="form-input exec-timeout" value="60" min="1" max="300" />
          <button id="exec-btn" class="modal-btn modal-btn-primary" disabled>EXEC</button>
        </div>
      </div>
      <div class="fleet-output" id="fleet-output">
        <div class="output-placeholder">Select a device and run a command</div>
      </div>
    </div>
  `
}

async function loadDevices(): Promise<void> {
  const select = document.getElementById('device-select') as HTMLSelectElement
  if (!select) return

  try {
    const devices = await fetchDevices()
    const options = devices
      .filter(d => d.status === 'active')
      .map(d => `<option value="${d.destination_hash}">${escapeHtml(d.name || d.destination_hash.slice(0, 16))}</option>`)

    select.innerHTML = '<option value="">-- Select device --</option>' + options.join('')
  } catch (err) {
    console.error('Failed to load devices:', err)
  }
}

function onDeviceSelect(e: Event): void {
  const select = e.target as HTMLSelectElement
  selectedDevice = select.value || null
  const statusBtn = document.getElementById('device-status-btn') as HTMLButtonElement
  const execBtn = document.getElementById('exec-btn') as HTMLButtonElement
  if (statusBtn) statusBtn.disabled = !selectedDevice
  if (execBtn) execBtn.disabled = !selectedDevice
}

async function handleExec(): Promise<void> {
  if (!selectedDevice) return

  const cmdInput = document.getElementById('exec-command') as HTMLInputElement
  const argsInput = document.getElementById('exec-args') as HTMLInputElement
  const timeoutInput = document.getElementById('exec-timeout') as HTMLInputElement
  const output = document.getElementById('fleet-output')

  if (!cmdInput || !output) return

  const command = cmdInput.value.trim()
  if (!command) return

  const args = argsInput?.value.trim().split(/\s+/).filter(Boolean) || []
  const timeout = parseInt(timeoutInput?.value || '60')

  output.innerHTML = '<div class="output-running">EXECUTING...</div>'

  try {
    const result = await fleetExec(selectedDevice, command, args, timeout)
    renderExecResult(result)
  } catch (err: any) {
    output.innerHTML = `<div class="output-error">ERROR: ${escapeHtml(err.message)}</div>`
  }
}

function renderExecResult(result: ExecResult): void {
  const output = document.getElementById('fleet-output')
  if (!output) return

  const exitClass = result.exit_code === 0 ? 'success' : 'error'
  output.innerHTML = `
    <div class="output-header">
      <span class="output-label">EXIT CODE:</span>
      <span class="output-exit ${exitClass}">${result.exit_code}</span>
    </div>
    ${result.stdout ? `
      <div class="output-section">
        <div class="output-label">STDOUT</div>
        <pre class="output-pre">${escapeHtml(result.stdout)}</pre>
      </div>
    ` : ''}
    ${result.stderr ? `
      <div class="output-section">
        <div class="output-label stderr">STDERR</div>
        <pre class="output-pre stderr">${escapeHtml(result.stderr)}</pre>
      </div>
    ` : ''}
  `
}

async function handleDeviceStatus(): Promise<void> {
  if (!selectedDevice) return
  const output = document.getElementById('fleet-output')
  if (!output) return

  output.innerHTML = '<div class="output-running">QUERYING STATUS...</div>'

  try {
    const status = await fleetStatus(selectedDevice)
    renderDeviceStatus(status)
  } catch (err: any) {
    output.innerHTML = `<div class="output-error">ERROR: ${escapeHtml(err.message)}</div>`
  }
}

function renderDeviceStatus(status: DeviceStatus): void {
  const output = document.getElementById('fleet-output')
  if (!output) return

  const uptime = formatUptime(status.uptime)
  const diskPct = status.disk_total > 0
    ? Math.round((status.disk_used / status.disk_total) * 100)
    : 0

  output.innerHTML = `
    <div class="status-grid">
      <div class="status-cell"><span class="output-label">UPTIME</span><span class="output-value">${uptime}</span></div>
      <div class="status-cell"><span class="output-label">IP</span><span class="output-value">${escapeHtml(status.ip)}</span></div>
      <div class="status-cell"><span class="output-label">DISK</span><span class="output-value">${diskPct}%</span></div>
      <div class="status-cell">
        <span class="output-label">SERVICES</span>
        <span class="output-value">${status.services.map(s => escapeHtml(s)).join(', ') || 'none'}</span>
      </div>
    </div>
  `
}

async function handleAnnounce(): Promise<void> {
  const output = document.getElementById('fleet-output')
  if (!output) return

  try {
    const result = await announce()
    output.innerHTML = `<div class="output-success">ANNOUNCED: ${result.destination_hash}</div>`
  } catch (err: any) {
    output.innerHTML = `<div class="output-error">ANNOUNCE FAILED: ${escapeHtml(err.message)}</div>`
  }
}

export async function mount(target: HTMLElement): Promise<void> {
  target.innerHTML = createHTML()
  mounted = true

  document.getElementById('device-select')?.addEventListener('change', onDeviceSelect)
  document.getElementById('exec-btn')?.addEventListener('click', handleExec)
  document.getElementById('device-status-btn')?.addEventListener('click', handleDeviceStatus)
  document.getElementById('announce-btn')?.addEventListener('click', handleAnnounce)
  document.getElementById('exec-command')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleExec()
  })

  await loadDevices()
}

export function unmount(): void {
  mounted = false
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
