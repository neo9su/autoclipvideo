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

export function remoteUrl(path) {
  return `${REMOTE_API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

export function remoteFetch(path, options) {
  return fetch(remoteUrl(path), options)
}
