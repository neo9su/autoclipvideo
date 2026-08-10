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
const MAX_RETRIES = 2

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
  if (key && inFlightRequests.has(key)) return inFlightRequests.get(key).then(response => response.clone())
  const request = (async () => {
    window.dispatchEvent(new CustomEvent('app:loading', { detail: 1 }))
    try {
      for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
        const controller = new AbortController()
        const timeoutId = timeout > 0 ? setTimeout(() => controller.abort(), timeout) : null
        try {
          const response = await fetch(url, { ...options, signal: controller.signal })
          if (response.ok || response.status < 500 || attempt === MAX_RETRIES) return response
        } catch (error) {
          if (attempt === MAX_RETRIES) throw error
        } finally {
          if (timeoutId !== null) clearTimeout(timeoutId)
        }
        await new Promise(resolve => setTimeout(resolve, 300 * (attempt + 1)))
      }
      throw new Error('请求失败')
    } finally { window.dispatchEvent(new CustomEvent('app:loading', { detail: -1 })) }
  })()
  if (key) {
    inFlightRequests.set(key, request)
    request.finally(() => inFlightRequests.delete(key)).catch(() => {})
  }
  return request.then(response => response.clone())
}
