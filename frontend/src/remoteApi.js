/**
 * The browser UI is intentionally a thin client. All API and websocket
 * traffic goes to the GPU host; the Mac must not run a local API fallback.
 */
export const REMOTE_API_BASE = (
  import.meta.env.VITE_API_BASE || 'http://10.190.0.203:8899'
).replace(/\/$/, '')

export const REMOTE_WS_BASE = (
  import.meta.env.VITE_WS_BASE || REMOTE_API_BASE.replace(/^http/, 'ws')
).replace(/\/$/, '')

const REMOTE_FETCH_TIMEOUT_MS = 15000
const inFlightRequests = new Map()

export function remoteUrl(path) {
  return `${REMOTE_API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

/**
 * Fetch with automatic timeout (default 15 s) so unreachable backends never
 * hang the UI.  Pass `timeout: 0` to disable the timeout for one call.
 */
export function remoteFetch(path, options = {}, timeout = REMOTE_FETCH_TIMEOUT_MS) {
  const url = remoteUrl(path)
  const method = (options.method || 'GET').toUpperCase()
  const key = method === 'GET' ? `${method}:${url}` : null
  if (key && inFlightRequests.has(key)) return inFlightRequests.get(key)
  const request = (async () => {
    window.dispatchEvent(new CustomEvent('app:loading', { detail: 1 }))
    try {
      const controller = new AbortController()
      const timeoutId = timeout > 0 ? setTimeout(() => controller.abort(), timeout) : null
      try { return await fetch(url, { ...options, signal: controller.signal }) }
      finally { if (timeoutId !== null) clearTimeout(timeoutId) }
    } finally { window.dispatchEvent(new CustomEvent('app:loading', { detail: -1 })) }
  })()
  if (key) {
    inFlightRequests.set(key, request)
    request.finally(() => inFlightRequests.delete(key))
  }
  return request
}
