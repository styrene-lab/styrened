// Reactive stores for styrened web UI

import type { Network } from 'vis-network/standalone'
import type { DataSet } from 'vis-data/standalone'
import type {
  Conversation, Message, Contact, MeshDevice, Identity,
  ZoomConfig, NodeTypeConfig, BorderConfig, SegmentumColor,
  AutoReplyState,
} from './types'

// Theme colors
export const theme = {
  greenBright: '#7ee8d2',
  greenMedium: '#4fb8a5',
  greenDim: '#38897a',
  greenDark: '#1c3530',
  greenDarker: '#111e1c',
  offBlack: '#0c1117',
  blue: '#6caed4',
  orange: '#e8b560',
  red: '#e06060',
  teal: '#5de4c7',
  yellow: '#e8d560',
  gray: '#4a5568',
  gold: '#c9a84c',
  amber: '#d4a04a',
  purple: '#7b6eb8',
}

// Status colors for mesh device state
export const statusColors: Record<string, string> = {
  active: theme.greenBright,
  stale: theme.orange,
  lost: theme.red,
  unknown: theme.gray,
}

// Icon composition constants
export const ICON_CONSTANTS = {
  BORDER_SCALE_NOVA: 1.5,
  BORDER_SCALE_SIMPLE: 1.0,
  HOVER_BRIGHTEN_AMOUNT: 0.3,
  SVG_CENTER: 32,
  SVG_BASE_SIZE: 64,
  BACKGROUND_CIRCLE_RADIUS: 28,
  BACKGROUND_FILL: '#0c1117',
}

// Border configuration
export const BORDER_CONFIGS: Record<string, BorderConfig> = {
  nova: {
    id: 'N',
    path: '/icons/border/round/nova.svg',
    scale: ICON_CONSTANTS.BORDER_SCALE_NOVA,
    shape: 'image',
  },
  simple: {
    id: 'S',
    path: '/icons/border/round/simple.svg',
    scale: ICON_CONSTANTS.BORDER_SCALE_SIMPLE,
    shape: 'circularImage',
  },
}

// Node type visual configuration for mesh devices
export const nodeTypes: Record<string, NodeTypeConfig> = {
  styrene_node: { icon: '/icons/base/styrene_node.svg', color: theme.amber, size: 30 },
  hub: { icon: '/icons/base/server.svg', color: theme.amber, size: 32 },
  rnode: { icon: '/icons/base/rnode.svg', color: theme.amber, size: 28 },
  transport: { icon: '/icons/base/router.svg', color: theme.amber, size: 30 },
  mesh_device: { icon: '/icons/base/mesh_device.svg', color: theme.amber, size: 26 },
  sbc: { icon: '/icons/base/sbc.svg', color: theme.teal, size: 26 },
  mcu: { icon: '/icons/base/mcu.svg', color: theme.teal, size: 24 },
  server: { icon: '/icons/base/server.svg', color: theme.greenMedium, size: 30 },
  router: { icon: '/icons/base/router.svg', color: theme.orange, size: 35 },
  client: { icon: '/icons/base/client.svg', color: theme.blue, size: 26 },
  generic: { icon: '/icons/base/unknown.svg', color: theme.greenDim, size: 28 },
  unknown: { icon: '/icons/base/unknown.svg', color: theme.greenDim, size: 28 },
}

// Segmentum palette for subnet nebulae
export const segmentumPalette: SegmentumColor[] = [
  { base: 'rgba(94, 228, 199, 0.10)', glow: 'rgba(94, 228, 199, 0.22)' },
  { base: 'rgba(108, 174, 212, 0.08)', glow: 'rgba(108, 174, 212, 0.18)' },
  { base: 'rgba(232, 181, 96, 0.08)', glow: 'rgba(232, 181, 96, 0.18)' },
  { base: 'rgba(93, 228, 199, 0.08)', glow: 'rgba(93, 228, 199, 0.18)' },
  { base: 'rgba(224, 96, 96, 0.08)', glow: 'rgba(224, 96, 96, 0.18)' },
  { base: 'rgba(123, 110, 184, 0.08)', glow: 'rgba(123, 110, 184, 0.18)' },
]

// Simple event emitter for store changes
type Listener = () => void
const listeners: Record<string, Listener[]> = {}

export function subscribe(store: string, fn: Listener): () => void {
  if (!listeners[store]) listeners[store] = []
  listeners[store].push(fn)
  return () => {
    const list = listeners[store]
    if (list) {
      const idx = list.indexOf(fn)
      if (idx >= 0) list.splice(idx, 1)
    }
  }
}

function notify(store: string): void {
  const list = listeners[store]
  if (list) list.forEach(fn => fn())
}

// --- Mesh store ---

export const meshStore = {
  network: null as Network | null,
  nodesDataSet: null as DataSet<any> | null,
  edgesDataSet: null as DataSet<any> | null,
  iconCache: {} as Record<string, string>,
  zoomConfig: {
    step: 0.2,
    minScale: 0.1,
    maxScale: 3.0,
    dynamicMin: 0.1,
    dynamicMax: 3.0,
    baseScale: 1.0,
  } as ZoomConfig,
  segmentumColors: {} as Record<string, SegmentumColor>,
  segmentumColorIndex: 0,
  devices: [] as MeshDevice[],
}

// --- Chat store ---

export const chatStore = {
  conversations: [] as Conversation[],
  activeConversation: null as string | null,
  messages: [] as Message[],
  loading: false,
}

export function setConversations(conversations: Conversation[]): void {
  chatStore.conversations = conversations
  notify('chat')
}

export function setActiveConversation(peerHash: string | null): void {
  chatStore.activeConversation = peerHash
  notify('chat')
}

export function setMessages(messages: Message[]): void {
  chatStore.messages = messages
  notify('chat')
}

export function addMessage(message: Message): void {
  chatStore.messages.push(message)
  notify('chat')
}

// --- Contact store ---

export const contactStore = {
  contacts: [] as Contact[],
}

export function setContacts(contacts: Contact[]): void {
  contactStore.contacts = contacts
  notify('contacts')
}

// --- Auto-reply store ---

export const autoReplyStore: AutoReplyState = {
  enabled: false,
  message: '',
  cooldown: 300,
}

export function setAutoReplyState(state: AutoReplyState): void {
  autoReplyStore.enabled = state.enabled
  autoReplyStore.message = state.message
  autoReplyStore.cooldown = state.cooldown
  notify('autoReply')
}

// --- App state ---

export const appState = {
  identity: null as Identity | null,
  connectionStatus: 'connecting' as 'connecting' | 'connected' | 'reconnecting' | 'error',
  activePanel: 'topology' as string,
}

export function setConnectionStatus(status: typeof appState.connectionStatus): void {
  appState.connectionStatus = status
  notify('app')
}

export function setActivePanel(panel: string): void {
  appState.activePanel = panel
  notify('app')
}
