// SVG icon composition system (migrated from specularium)

import type { TopologyNode, NodeVisuals, BorderConfig, NodeTypeConfig } from '../types'
import { theme, statusColors, nodeTypes, ICON_CONSTANTS, BORDER_CONFIGS, meshStore } from '../state'

// Create tinted SVG data URI from icon path and color
export async function getTintedIcon(iconPath: string, color: string): Promise<string | null> {
  const cacheKey = `${iconPath}:${color}`
  if (meshStore.iconCache[cacheKey]) {
    return meshStore.iconCache[cacheKey]
  }

  try {
    const response = await fetch(iconPath)
    let svgText = await response.text()
    svgText = svgText.replace(/currentColor/g, color)
    const dataUri = 'data:image/svg+xml;base64,' + btoa(svgText)
    meshStore.iconCache[cacheKey] = dataUri
    return dataUri
  } catch (error) {
    console.error('Failed to load icon:', iconPath, error)
    return null
  }
}

// Brighten a hex color by a percentage (0-1)
export function brightenColor(hex: string, percent: number = ICON_CONSTANTS.HOVER_BRIGHTEN_AMOUNT): string {
  if (!/^#[0-9A-Fa-f]{6}$/.test(hex)) {
    return theme.greenBright
  }

  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)

  const newR = Math.min(255, Math.round(r + (255 - r) * percent))
  const newG = Math.min(255, Math.round(g + (255 - g) * percent))
  const newB = Math.min(255, Math.round(b + (255 - b) * percent))

  return '#' + [newR, newG, newB].map(x => x.toString(16).padStart(2, '0')).join('')
}

// Select border config based on node properties
export function selectBorderConfig(node: TopologyNode): BorderConfig {
  // Hub gets the nova border (self-node)
  return node.type === 'hub' ? BORDER_CONFIGS.nova : BORDER_CONFIGS.simple
}

// Composite two SVGs with different colors (border + base icon)
export async function getCompositeIcon(
  borderPath: string,
  borderColor: string,
  basePath: string,
  baseColor: string,
  borderScale: number = 1.0,
): Promise<string | null> {
  const cacheKey = `${borderPath}:${borderColor}+${basePath}:${baseColor}:${borderScale}`
  if (meshStore.iconCache[cacheKey]) {
    return meshStore.iconCache[cacheKey]
  }

  try {
    const [borderResponse, baseResponse] = await Promise.all([
      fetch(borderPath),
      fetch(basePath),
    ])

    let borderSvg = await borderResponse.text()
    let baseSvg = await baseResponse.text()

    borderSvg = borderSvg.replace(/currentColor/g, borderColor)
    baseSvg = baseSvg.replace(/currentColor/g, baseColor)

    const extractContent = (svg: string): string => {
      const match = svg.match(/<svg[^>]*>([\s\S]*)<\/svg>/)
      return match ? match[1] : ''
    }

    const borderContent = extractContent(borderSvg)
    const baseContent = extractContent(baseSvg)

    const borderTransform = borderScale !== 1.0
      ? `transform="translate(${ICON_CONSTANTS.SVG_CENTER}, ${ICON_CONSTANTS.SVG_CENTER}) scale(${borderScale}) translate(-${ICON_CONSTANTS.SVG_CENTER}, -${ICON_CONSTANTS.SVG_CENTER})"`
      : ''

    const viewBoxSize = ICON_CONSTANTS.SVG_BASE_SIZE * borderScale
    const viewBoxOffset = ICON_CONSTANTS.SVG_CENTER - ICON_CONSTANTS.SVG_CENTER * borderScale
    const viewBox = `${viewBoxOffset} ${viewBoxOffset} ${viewBoxSize} ${viewBoxSize}`

    const backgroundCircle = `<circle cx="${ICON_CONSTANTS.SVG_CENTER}" cy="${ICON_CONSTANTS.SVG_CENTER}" r="${ICON_CONSTANTS.BACKGROUND_CIRCLE_RADIUS}" fill="${ICON_CONSTANTS.BACKGROUND_FILL}" />`

    const compositeSvg = `<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="128" height="128" viewBox="${viewBox}" version="1.1" xmlns="http://www.w3.org/2000/svg">
  <g id="background-layer">${backgroundCircle}</g>
  <g id="border-layer" ${borderTransform}>${borderContent}</g>
  <g id="base-layer">${baseContent}</g>
</svg>`

    const dataUri = 'data:image/svg+xml;base64,' + btoa(compositeSvg)
    meshStore.iconCache[cacheKey] = dataUri
    return dataUri
  } catch (error) {
    console.error('Failed to composite icons:', borderPath, basePath, error)
    return null
  }
}

// Prepare node visuals (icons, labels, colors)
export async function prepareNodeVisuals(node: TopologyNode): Promise<NodeVisuals> {
  const typeConfig = nodeTypes[node.type] || nodeTypes.unknown
  const status = node.status || 'unknown'

  // Hub gets gold border, others get status-based color
  let borderColor: string
  if (node.type === 'hub') {
    borderColor = theme.gold
  } else {
    borderColor = statusColors[status] || statusColors.unknown
  }

  const iconColor = (status === 'active')
    ? typeConfig.color
    : theme.gray

  const borderConfig = selectBorderConfig(node)

  const iconDataUri = await getCompositeIcon(
    borderConfig.path, borderColor, typeConfig.icon, iconColor, borderConfig.scale,
  )

  const hoverIconDataUri = await getCompositeIcon(
    borderConfig.path, brightenColor(borderColor), typeConfig.icon, iconColor, borderConfig.scale,
  )

  const selectedIconDataUri = await getCompositeIcon(
    borderConfig.path, theme.greenBright, typeConfig.icon, iconColor, borderConfig.scale,
  )

  const label = (node.label || node.id).toUpperCase()

  return {
    borderColor,
    iconDataUri,
    hoverIconDataUri,
    selectedIconDataUri,
    label,
    shape: borderConfig.shape,
    size: typeConfig.size,
    typeConfig,
  }
}
