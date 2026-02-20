// Hash-based panel routing for styrened web UI

type RouteHandler = (params: Record<string, string>) => void

interface Route {
  pattern: RegExp
  handler: RouteHandler
}

const routes: Route[] = []
let currentRoute = ''

export function addRoute(pattern: string, handler: RouteHandler): void {
  // Convert path pattern to regex: {param} -> named capture group
  const regexStr = '^' + pattern.replace(/\{(\w+)\}/g, '(?<$1>[^/]+)') + '$'
  routes.push({ pattern: new RegExp(regexStr), handler })
}

export function navigate(hash: string): void {
  if (!hash.startsWith('#/')) hash = '#/' + hash
  window.location.hash = hash
}

export function getCurrentRoute(): string {
  return currentRoute
}

function matchRoute(path: string): void {
  currentRoute = path
  for (const route of routes) {
    const match = path.match(route.pattern)
    if (match) {
      route.handler(match.groups || {})
      return
    }
  }
  // Default: topology
  if (routes.length > 0) {
    routes[0].handler({})
  }
}

export function startRouter(): void {
  const handleHash = () => {
    const hash = window.location.hash.slice(1) || '/topology'
    matchRoute(hash)
  }

  window.addEventListener('hashchange', handleHash)
  handleHash()
}
