// vis-network configuration for mesh topology graph

import { theme } from '../state'

export const networkOptions = {
  nodes: {
    font: {
      color: theme.greenBright,
      face: 'JetBrains Mono, monospace',
      size: 14,
    },
    margin: { top: 10, right: 14, bottom: 10, left: 14 },
  },
  edges: {
    color: {
      color: theme.greenMedium,
      highlight: theme.greenBright,
      hover: theme.greenBright,
    },
    width: 2,
    smooth: {
      enabled: true,
      type: 'continuous' as const,
      roundness: 0.5,
    },
  },
  physics: {
    enabled: true,
    solver: 'barnesHut' as const,
    barnesHut: {
      gravitationalConstant: -3000,
      centralGravity: 0.1,
      springLength: 150,
      springConstant: 0.02,
      damping: 0.09,
      avoidOverlap: 0.5,
    },
    stabilization: {
      enabled: true,
      iterations: 200,
      updateInterval: 25,
      fit: true,
    },
  },
  interaction: {
    dragNodes: true,
    dragView: true,
    zoomView: true,
    zoomSpeed: 0.5,
    hover: true,
    tooltipDelay: 200,
    hideEdgesOnDrag: false,
    hideEdgesOnZoom: false,
  },
  layout: {
    improvedLayout: true,
    hierarchical: false,
  },
}

// Edge color mapping for mesh interface types
export function getEdgeStyle(interfaceType?: string): { color: string; width: number; dashes: boolean | number[] } {
  switch (interfaceType) {
    case 'RNodeInterface':
      return { color: theme.amber, width: 2, dashes: false }
    case 'TCPClientInterface':
    case 'TCPServerInterface':
      return { color: theme.greenMedium, width: 2, dashes: false }
    case 'UDPInterface':
      return { color: theme.blue, width: 1.5, dashes: [5, 5] }
    case 'LocalInterface':
      return { color: theme.purple, width: 1, dashes: [2, 4] }
    case 'AutoInterface':
      return { color: theme.teal, width: 2, dashes: false }
    default:
      return { color: theme.greenMedium, width: 2, dashes: false }
  }
}

// Format bitrate for display
export function formatBitrate(bps: number): string {
  if (bps >= 1000000) return `${(bps / 1000000).toFixed(1)} Mbps`
  if (bps >= 1000) return `${(bps / 1000).toFixed(1)} kbps`
  return `${bps} bps`
}
