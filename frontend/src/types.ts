// Data types for styrened web UI

export interface MeshDevice {
  id: string
  destination_hash: string
  identity_hash?: string
  label: string
  name?: string
  type: string
  status: string
  last_seen?: number
  last_seen_display?: string
  announce_count?: number
  capabilities?: string[]
  version?: string
  lxmf_destination_hash?: string
}

export interface TopologyData {
  nodes: TopologyNode[]
  edges: TopologyEdge[]
}

export interface TopologyNode {
  id: string
  label: string
  type: string
  status: string
  last_seen?: number
  announce_count?: number
  capabilities?: string[]
  version?: string
}

export interface TopologyEdge {
  from: string
  to: string
  hops?: number
  interface_type?: string
  interface_name?: string
  bitrate?: number
}

export interface Conversation {
  peer_hash: string
  display_name: string | null
  unread_count: number
  last_message_time: number | null
  last_message_preview: string | null
  last_message_outgoing: boolean | null
  message_count: number
}

export interface Message {
  id: number
  source_hash: string
  destination_hash: string
  timestamp: number
  content: string | null
  title: string | null
  protocol: string
  status: string
  is_outgoing: boolean
  signature_valid?: boolean | null
  transport_encrypted?: boolean | null
  delivery_method?: string | null
  delivery_attempts?: number
  lxmf_hash?: string | null
  has_attachment?: boolean
  attachment_type?: string
  attachment_name?: string
  attachment_size?: number
  attachment_mime?: string
  thread_id?: string | null
  reply_to_hash?: string | null
}

export interface Contact {
  peer_hash: string
  alias: string
  notes: string | null
  created_at: number
  updated_at: number
}

export interface Identity {
  identity_hash: string
  destination_hash: string
  lxmf_destination_hash: string
}

export interface MeshStatus {
  uptime: number
  version: string | null
  device_count: number
  styrene_count: number
  active: number
  stale: number
  lost: number
  path_snapshot_running: boolean
}

export interface ExecResult {
  exit_code: number
  stdout: string
  stderr: string
}

export interface DeviceStatus {
  uptime: number
  ip: string
  services: string[]
  disk_used: number
  disk_total: number
}

// Graph rendering types (from specularium)

export interface NodeTypeConfig {
  icon: string
  color: string
  size: number
}

export interface BorderConfig {
  id: string
  path: string
  scale: number
  shape: string
}

export interface SegmentumColor {
  base: string
  glow: string
}

export interface NodeVisuals {
  borderColor: string
  iconDataUri: string | null
  hoverIconDataUri: string | null
  selectedIconDataUri: string | null
  label: string
  shape: string
  size: number
  typeConfig: NodeTypeConfig
}

export interface ZoomConfig {
  step: number
  minScale: number
  maxScale: number
  dynamicMin: number
  dynamicMax: number
  baseScale: number
  fitScale?: number
}
