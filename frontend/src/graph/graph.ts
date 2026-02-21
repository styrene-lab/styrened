// vis-network graph rendering engine (migrated from specularium)

import { Network } from 'vis-network/standalone'
import { DataSet } from 'vis-data/standalone'
import type { TopologyData, TopologyNode, TopologyEdge, SegmentumColor } from '../types'
import { theme, meshStore, segmentumPalette } from '../state'
import { prepareNodeVisuals } from './icons'
import { networkOptions, getEdgeStyle, formatBitrate } from './config'

// --- Segmentum (subnet nebula) rendering ---

let segmentumColorIndex = 0
const segmentumColors: Record<string, SegmentumColor> = {}

function getSegmentumColor(cidr: string): SegmentumColor {
  if (!segmentumColors[cidr]) {
    segmentumColors[cidr] = segmentumPalette[segmentumColorIndex % segmentumPalette.length]
    segmentumColorIndex++
  }
  return segmentumColors[cidr]
}

function drawSegmenta(ctx: CanvasRenderingContext2D): void {
  if (!meshStore.network || !meshStore.nodesDataSet) return

  const nodesBySegmentum: Record<string, string[]> = {}
  const allNodeIds = meshStore.nodesDataSet.getIds()

  allNodeIds.forEach((nodeId: any) => {
    const nodeData = meshStore.nodesDataSet!.get(nodeId) as any
    if (!nodeData || !nodeData._segmentum) return
    if (!nodesBySegmentum[nodeData._segmentum]) {
      nodesBySegmentum[nodeData._segmentum] = []
    }
    nodesBySegmentum[nodeData._segmentum].push(nodeId as string)
  })

  const positions = meshStore.network.getPositions()

  Object.entries(nodesBySegmentum).forEach(([segmentum, nodeIds]) => {
    if (nodeIds.length < 1) return

    const nodePositions = nodeIds
      .map(id => positions[id])
      .filter((p): p is { x: number; y: number } => !!p)

    if (nodePositions.length === 0) return

    const xs = nodePositions.map(p => p.x)
    const ys = nodePositions.map(p => p.y)

    const minX = Math.min(...xs)
    const maxX = Math.max(...xs)
    const minY = Math.min(...ys)
    const maxY = Math.max(...ys)

    const padding = 120
    const centerX = (minX + maxX) / 2
    const centerY = (minY + maxY) / 2
    const width = Math.max(maxX - minX + padding * 2, 200)
    const height = Math.max(maxY - minY + padding * 2, 200)

    const color = getSegmentumColor(segmentum)
    drawNebula(ctx, centerX, centerY, width, height, color, nodePositions)
    drawSegmentumLabel(ctx, segmentum, centerX, minY - padding - 30)
  })
}

function drawNebula(
  ctx: CanvasRenderingContext2D,
  centerX: number, centerY: number,
  width: number, height: number,
  color: SegmentumColor,
  nodePositions: { x: number; y: number }[],
): void {
  ctx.save()
  const radiusX = width / 2
  const radiusY = height / 2

  const gradient = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, Math.max(radiusX, radiusY))
  gradient.addColorStop(0, color.glow)
  gradient.addColorStop(0.4, color.base)
  gradient.addColorStop(1, 'rgba(0, 0, 0, 0)')

  ctx.beginPath()
  ctx.ellipse(centerX, centerY, radiusX * 1.2, radiusY * 1.2, 0, 0, Math.PI * 2)
  ctx.fillStyle = gradient
  ctx.fill()

  nodePositions.forEach((pos, i) => {
    const wispRadius = 60 + (i % 3) * 20
    const wispGradient = ctx.createRadialGradient(pos.x, pos.y, 0, pos.x, pos.y, wispRadius)
    wispGradient.addColorStop(0, color.glow)
    wispGradient.addColorStop(0.5, color.base)
    wispGradient.addColorStop(1, 'rgba(0, 0, 0, 0)')

    ctx.beginPath()
    ctx.arc(pos.x, pos.y, wispRadius, 0, Math.PI * 2)
    ctx.fillStyle = wispGradient
    ctx.fill()
  })

  ctx.restore()
}

function drawSegmentumLabel(ctx: CanvasRenderingContext2D, segmentum: string, x: number, y: number): void {
  ctx.save()
  ctx.textAlign = 'center'
  ctx.font = '14px JetBrains Mono, monospace'
  ctx.textBaseline = 'middle'
  ctx.shadowColor = 'rgba(94, 228, 199, 0.4)'
  ctx.shadowBlur = 6
  ctx.fillStyle = 'rgba(94, 228, 199, 0.5)'
  ctx.fillText(`SEGMENTUM ${segmentum}`, x, y)
  ctx.restore()
}

// --- Tooltip ---

function buildTooltip(node: TopologyNode): string {
  const lines: string[] = []
  lines.push((node.label || node.id).toUpperCase())
  lines.push('\u2500'.repeat(Math.min(lines[0].length, 28)))

  const statusIcon: Record<string, string> = {
    active: '\u25CF', stale: '\u25D1', lost: '\u2717', unknown: '\u25CB',
  }
  lines.push(`${node.type} ${statusIcon[node.status] || '\u25CB'}`)

  if (node.version) lines.push(`v${node.version}`)
  if (node.capabilities?.length) lines.push(node.capabilities.join(' '))

  return lines.join('\n')
}

// --- Zoom helpers ---

export function calculateZoomBounds(container: HTMLElement): void {
  if (!meshStore.network || !meshStore.nodesDataSet || meshStore.nodesDataSet.length === 0) {
    meshStore.zoomConfig.dynamicMin = meshStore.zoomConfig.minScale
    meshStore.zoomConfig.dynamicMax = meshStore.zoomConfig.maxScale
    return
  }

  const positions = meshStore.network.getPositions()
  const nodeIds = Object.keys(positions)
  if (nodeIds.length === 0) return

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  nodeIds.forEach(id => {
    const pos = positions[id]
    if (pos.x < minX) minX = pos.x
    if (pos.x > maxX) maxX = pos.x
    if (pos.y < minY) minY = pos.y
    if (pos.y > maxY) maxY = pos.y
  })

  const nodePadding = 100
  const graphWidth = maxX - minX + nodePadding * 2
  const graphHeight = maxY - minY + nodePadding * 2
  const viewportWidth = container.clientWidth || 800
  const viewportHeight = container.clientHeight || 600

  const fitScaleX = viewportWidth / graphWidth
  const fitScaleY = viewportHeight / graphHeight
  const fitScale = Math.min(fitScaleX, fitScaleY)

  meshStore.zoomConfig.dynamicMin = Math.max(fitScale * 0.5, meshStore.zoomConfig.minScale)

  const nodeCount = nodeIds.length
  const graphArea = graphWidth * graphHeight
  const density = nodeCount / (graphArea / 10000)

  let densityMaxZoom: number
  if (density < 0.5) densityMaxZoom = 3.0
  else if (density < 2) densityMaxZoom = 2.5 - (density - 0.5) * 0.33
  else densityMaxZoom = Math.max(1.5, 2.0 - (density - 2) * 0.1)

  meshStore.zoomConfig.dynamicMax = Math.min(densityMaxZoom, meshStore.zoomConfig.maxScale)
  meshStore.zoomConfig.fitScale = fitScale
  meshStore.zoomConfig.baseScale = fitScale
}

export function handleZoomIn(): void {
  if (!meshStore.network) return
  const s = meshStore.network.getScale()
  const ns = Math.min(s * (1 + meshStore.zoomConfig.step), meshStore.zoomConfig.dynamicMax)
  meshStore.network.moveTo({ scale: ns, animation: { duration: 200, easingFunction: 'easeInOutQuad' } })
}

export function handleZoomOut(): void {
  if (!meshStore.network) return
  const s = meshStore.network.getScale()
  const ns = Math.max(s / (1 + meshStore.zoomConfig.step), meshStore.zoomConfig.dynamicMin)
  meshStore.network.moveTo({ scale: ns, animation: { duration: 200, easingFunction: 'easeInOutQuad' } })
}

export function handleZoomFit(): void {
  if (!meshStore.network) return
  meshStore.network.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } })
}

// --- Render ---

export async function renderNetwork(graph: TopologyData, container: HTMLElement): Promise<void> {
  // Transform nodes
  const nodes = await Promise.all(
    graph.nodes.map(async n => {
      const visuals = await prepareNodeVisuals(n)
      const hasAutoReply = n.capabilities?.includes('autoreply')
      const nodeOpacity = hasAutoReply ? 0.45 : 1.0
      const label = hasAutoReply ? `${visuals.label} (OOO)` : visuals.label
      return {
        id: n.id,
        label,
        title: buildTooltip(n),
        shape: visuals.shape,
        image: visuals.iconDataUri,
        size: visuals.size,
        opacity: nodeOpacity,
        color: {
          border: visuals.borderColor,
          background: theme.offBlack,
          highlight: { border: theme.greenBright, background: theme.greenDarker },
          hover: { border: theme.greenBright, background: theme.greenDarker },
        },
        borderWidth: 0,
        borderWidthSelected: 0,
        font: {
          color: visuals.borderColor,
          face: 'JetBrains Mono, monospace',
          size: 14,
          vadjust: 8,
        },
        hoverImage: visuals.hoverIconDataUri,
        selectedImage: visuals.selectedIconDataUri,
        normalImage: visuals.iconDataUri,
        _segmentum: null as string | null, // Can be extended for subnet grouping
      }
    }),
  )

  // Transform edges
  const edges = graph.edges.map(e => {
    const style = getEdgeStyle(e.interface_type)
    let edgeTitle: string | null = null
    const parts: string[] = []
    if (e.hops !== undefined) parts.push(`Hops: ${e.hops}`)
    if (e.interface_type) parts.push(`Interface: ${e.interface_type}`)
    if (e.interface_name) parts.push(`Name: ${e.interface_name}`)
    if (e.bitrate) parts.push(`Bitrate: ${formatBitrate(e.bitrate)}`)
    if (parts.length > 0) edgeTitle = parts.join('\n')

    return {
      id: `${e.from}-${e.to}`,
      from: e.from,
      to: e.to,
      color: {
        color: style.color,
        highlight: theme.greenBright,
        hover: theme.greenBright,
      },
      width: style.width,
      dashes: style.dashes,
      title: edgeTitle,
      smooth: { enabled: true, type: 'continuous' as const, roundness: 0.5 },
    }
  })

  // Create or update DataSets
  if (meshStore.nodesDataSet) {
    meshStore.nodesDataSet.clear()
    meshStore.nodesDataSet.add(nodes)
  } else {
    meshStore.nodesDataSet = new DataSet(nodes)
  }

  if (meshStore.edgesDataSet) {
    meshStore.edgesDataSet.clear()
    meshStore.edgesDataSet.add(edges)
  } else {
    meshStore.edgesDataSet = new DataSet(edges)
  }

  // Create network if it doesn't exist
  if (!meshStore.network) {
    meshStore.network = new Network(
      container,
      { nodes: meshStore.nodesDataSet, edges: meshStore.edgesDataSet },
      networkOptions,
    )

    // Hover icon swap
    meshStore.network.on('hoverNode', (params: any) => {
      const nd = meshStore.nodesDataSet!.get(params.node) as any
      if (nd?.hoverImage) meshStore.nodesDataSet!.update({ id: params.node, image: nd.hoverImage })
    })

    meshStore.network.on('blurNode', (params: any) => {
      const nd = meshStore.nodesDataSet!.get(params.node) as any
      if (nd?.normalImage) meshStore.nodesDataSet!.update({ id: params.node, image: nd.normalImage })
    })

    // Segmentum nebula rendering
    meshStore.network.on('beforeDrawing', (ctx: CanvasRenderingContext2D) => {
      drawSegmenta(ctx)
    })

    // Fit after stabilization
    meshStore.network.on('stabilizationIterationsDone', () => {
      meshStore.network!.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } })
      setTimeout(() => calculateZoomBounds(container), 600)
    })

    // Enforce zoom limits
    meshStore.network.on('zoom', () => {
      const s = meshStore.network!.getScale()
      if (s < meshStore.zoomConfig.dynamicMin * 0.99) {
        meshStore.network!.moveTo({ scale: meshStore.zoomConfig.dynamicMin })
      } else if (s > meshStore.zoomConfig.dynamicMax * 1.01) {
        meshStore.network!.moveTo({ scale: meshStore.zoomConfig.dynamicMax })
      }
    })

    window.addEventListener('resize', () => calculateZoomBounds(container))
  }
}

// Incremental update for SSE device-updated events
export async function updateNode(deviceData: any): Promise<void> {
  if (!meshStore.nodesDataSet) return

  const node: TopologyNode = {
    id: deviceData.id,
    label: deviceData.label,
    type: deviceData.type,
    status: deviceData.status,
    last_seen: deviceData.last_seen,
    announce_count: deviceData.announce_count,
    version: deviceData.version,
  }

  const visuals = await prepareNodeVisuals(node)

  meshStore.nodesDataSet.update({
    id: node.id,
    label: visuals.label,
    title: buildTooltip(node),
    shape: visuals.shape,
    image: visuals.iconDataUri,
    size: visuals.size,
    color: {
      border: visuals.borderColor,
      background: theme.offBlack,
      highlight: { border: theme.greenBright, background: theme.greenDarker },
      hover: { border: theme.greenBright, background: theme.greenDarker },
    },
    borderWidth: 0,
    borderWidthSelected: 0,
    font: {
      color: visuals.borderColor,
      face: 'JetBrains Mono, monospace',
      size: 14,
      vadjust: 8,
    },
    hoverImage: visuals.hoverIconDataUri,
    selectedImage: visuals.selectedIconDataUri,
    normalImage: visuals.iconDataUri,
  })
}
