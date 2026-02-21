// Fetch wrappers for all styrened REST API endpoints

import type {
  TopologyData,
  MeshDevice,
  MeshStatus,
  Identity,
  Conversation,
  Message,
  Contact,
  ExecResult,
  DeviceStatus,
  SystemStatus,
  ReticulumStatus,
  DiskInfo,
  NetworkInterface,
  SetupStatus,
  RebootResult,
  UpdateConfigResult,
  AutoReplyState,
} from './types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status}: ${body}`)
  }
  return res.json()
}

// Identity & Config

export async function fetchIdentity(): Promise<Identity> {
  return request('/api/identity')
}

export async function fetchConfig(): Promise<{ config: Record<string, any> }> {
  return request('/api/config')
}

// Mesh topology

export async function fetchTopology(
  includeUnnamed = false,
  excludeStatus?: string,
): Promise<TopologyData> {
  const params = new URLSearchParams({ include_unnamed: String(includeUnnamed) })
  if (excludeStatus) params.set('exclude_status', excludeStatus)
  return request(`/api/mesh/topology?${params}`)
}

export async function fetchDevices(
  includeUnnamed = false,
  excludeStatus?: string,
): Promise<MeshDevice[]> {
  const params = new URLSearchParams({ include_unnamed: String(includeUnnamed) })
  if (excludeStatus) params.set('exclude_status', excludeStatus)
  return request(`/api/mesh/devices?${params}`)
}

export async function fetchMeshStatus(): Promise<MeshStatus> {
  return request('/api/mesh/status')
}

// Conversations

export async function fetchConversations(): Promise<{ conversations: Conversation[] }> {
  return request('/api/conversations')
}

export async function fetchMessages(
  peerHash: string,
  limit = 50,
  before?: number,
  status?: string,
): Promise<{ messages: Message[] }> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (before !== undefined) params.set('before', String(before))
  if (status) params.set('status', status)
  return request(`/api/conversations/${peerHash}/messages?${params}`)
}

export async function sendChat(
  peerHash: string,
  content: string,
  options?: { title?: string; delivery_method?: string; reply_to_hash?: string },
): Promise<{ message_id: number; sent: boolean; lxmf_hash: string; delivery_method: string }> {
  return request(`/api/conversations/${peerHash}/messages`, {
    method: 'POST',
    body: JSON.stringify({ content, ...options }),
  })
}

export async function markRead(peerHash: string): Promise<{ marked_read: number }> {
  return request(`/api/conversations/${peerHash}/read`, { method: 'POST' })
}

export async function deleteConversation(peerHash: string): Promise<{ deleted: number }> {
  return request(`/api/conversations/${peerHash}`, { method: 'DELETE' })
}

// Messages (cross-conversation)

export async function searchMessages(
  q: string,
  peerHash?: string,
  limit = 50,
): Promise<{ messages: Message[] }> {
  const params = new URLSearchParams({ q, limit: String(limit) })
  if (peerHash) params.set('peer_hash', peerHash)
  return request(`/api/messages/search?${params}`)
}

export async function deleteMessage(messageId: number): Promise<{ deleted: boolean }> {
  return request(`/api/messages/${messageId}`, { method: 'DELETE' })
}

export async function retryMessage(
  messageId: number,
): Promise<{ message_id: number; retried: boolean; lxmf_hash: string; delivery_method: string }> {
  return request(`/api/messages/${messageId}/retry`, { method: 'POST' })
}

// Contacts

export async function fetchContacts(): Promise<{ contacts: Contact[] }> {
  return request('/api/contacts')
}

export async function resolveContact(
  name: string,
  prefixMatch = true,
): Promise<{ peer_hash: string }> {
  return request(`/api/contacts/resolve?name=${encodeURIComponent(name)}&prefix_match=${prefixMatch}`)
}

export async function setContact(
  peerHash: string,
  alias: string,
  notes?: string,
): Promise<Contact> {
  return request(`/api/contacts/${peerHash}`, {
    method: 'PUT',
    body: JSON.stringify({ alias, notes }),
  })
}

export async function removeContact(peerHash: string): Promise<{ removed: boolean }> {
  return request(`/api/contacts/${peerHash}`, { method: 'DELETE' })
}

// Fleet

export async function fleetExec(
  destination: string,
  command: string,
  args: string[] = [],
  timeout = 60,
): Promise<ExecResult> {
  return request(`/api/fleet/${destination}/exec`, {
    method: 'POST',
    body: JSON.stringify({ command, args, timeout }),
  })
}

export async function fleetStatus(destination: string): Promise<DeviceStatus> {
  return request(`/api/fleet/${destination}/status`)
}

export async function announce(): Promise<{ announced: boolean; destination_hash: string }> {
  return request('/api/announce', { method: 'POST' })
}

export async function fleetReboot(
  destination: string,
  delay = 0,
): Promise<RebootResult> {
  return request(`/api/fleet/${destination}/reboot`, {
    method: 'POST',
    body: JSON.stringify({ delay }),
  })
}

export async function fleetConfigUpdate(
  destination: string,
  configUpdates: Record<string, any>,
  timeout = 10,
): Promise<UpdateConfigResult> {
  return request(`/api/fleet/${destination}/config`, {
    method: 'PUT',
    body: JSON.stringify({ config_updates: configUpdates, timeout }),
  })
}

// Auto-reply

export async function fetchAutoReplyStatus(): Promise<AutoReplyState> {
  return request('/api/auto-reply')
}

export async function toggleAutoReply(
  enabled: boolean,
  message?: string,
): Promise<AutoReplyState> {
  return request('/api/auto-reply', {
    method: 'POST',
    body: JSON.stringify({ enabled, message }),
  })
}

// Config

export async function updateConfig(
  updates: Record<string, any>,
): Promise<{ config: Record<string, any> }> {
  return request('/api/config', {
    method: 'PUT',
    body: JSON.stringify(updates),
  })
}

// System

export async function fetchSystemStatus(): Promise<SystemStatus> {
  return request('/api/system/status')
}

export async function fetchReticulumStatus(): Promise<ReticulumStatus> {
  return request('/api/system/reticulum')
}

export async function fetchDisks(): Promise<DiskInfo[]> {
  return request('/api/system/disks')
}

export async function fetchNetworkInterfaces(): Promise<NetworkInterface[]> {
  return request('/api/system/network')
}

export async function fetchSetupStatus(): Promise<SetupStatus> {
  return request('/api/system/setup-status')
}
