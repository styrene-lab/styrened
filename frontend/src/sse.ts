// Server-Sent Events lifecycle for styrened

type SSEHandler = (data: any) => void
type StatusCallback = (status: string) => void

const handlers: Record<string, SSEHandler[]> = {}
const statusCallbacks: StatusCallback[] = []
let eventSource: EventSource | null = null
let reconnectTimeout: ReturnType<typeof setTimeout> | null = null

export function onStatus(cb: StatusCallback): void {
  statusCallbacks.push(cb)
}

function notifyStatus(status: string): void {
  for (const cb of statusCallbacks) cb(status)
}

export function on(eventType: string, handler: SSEHandler): void {
  if (!handlers[eventType]) handlers[eventType] = []
  handlers[eventType].push(handler)
}

export function off(eventType: string, handler: SSEHandler): void {
  const list = handlers[eventType]
  if (list) {
    const idx = list.indexOf(handler)
    if (idx >= 0) list.splice(idx, 1)
  }
}

function dispatch(eventType: string, data: any): void {
  const list = handlers[eventType]
  if (list) {
    for (const h of list) {
      try {
        h(data)
      } catch (e) {
        console.error(`SSE handler error for ${eventType}:`, e)
      }
    }
  }
}

export function connect(): void {
  if (eventSource) {
    eventSource.close()
  }

  eventSource = new EventSource('/events')

  eventSource.onopen = () => {
    console.log('SSE connected')
    notifyStatus('connected')
    dispatch('connection', { status: 'connected' })
  }

  eventSource.onerror = () => {
    console.log('SSE disconnected, reconnecting...')
    notifyStatus('reconnecting')
    dispatch('connection', { status: 'reconnecting' })
    eventSource?.close()
    eventSource = null
    reconnectTimeout = setTimeout(connect, 5000)
  }

  // Styrened event types
  const eventTypes = [
    'device-updated',
    'message-event',
    'conversation-updated',
    'contact-updated',
  ]

  for (const type of eventTypes) {
    eventSource.addEventListener(type, (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        dispatch(type, data)
      } catch (e) {
        console.error(`Failed to parse SSE ${type}:`, e)
      }
    })
  }
}

export function disconnect(): void {
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout)
    reconnectTimeout = null
  }
  if (eventSource) {
    eventSource.close()
    eventSource = null
  }
}
