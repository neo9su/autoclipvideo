const BASE = (import.meta.env.VITE_API_BASE || 'http://10.190.0.203:8899').replace(/\/$/, '')
const FETCH_TIMEOUT_MS = 15000
const inFlightRequests = new Map()
const MAX_RETRIES = 2
const RETRYABLE_STATUS_MIN = 500

function notifyLoading(delta) {
  window.dispatchEvent(new CustomEvent('app:loading', { detail: delta }))
}

/** Wrapper that aborts fetch after timeout so an unreachable backend does not hang the UI. */
export function fetchWithTimeout(url, options = {}, timeout = FETCH_TIMEOUT_MS) {
  const method = (options.method || 'GET').toUpperCase()
  const key = method === 'GET' ? `${method}:${url}` : null
  if (key && inFlightRequests.has(key)) return inFlightRequests.get(key)

  const request = (async () => {
    notifyLoading(1)
    try {
      for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
        const controller = new AbortController()
        const timeoutId = timeout > 0 ? setTimeout(() => controller.abort(), timeout) : null
        try {
          const response = await fetch(url, { ...options, signal: controller.signal })
          if (response.ok || response.status < RETRYABLE_STATUS_MIN || attempt === MAX_RETRIES) return response
        } catch (error) {
          if (attempt === MAX_RETRIES) throw error
        } finally {
          if (timeoutId !== null) clearTimeout(timeoutId)
        }
        await new Promise(resolve => setTimeout(resolve, 300 * (attempt + 1)))
      }
      throw new Error('请求失败')
    } finally {
      notifyLoading(-1)
    }
  })()
  if (key) {
    inFlightRequests.set(key, request)
    request.then(
      () => inFlightRequests.delete(key),
      () => inFlightRequests.delete(key),
    )
  }
  return request
}

async function readErrorMessage(response, fallback = '请求失败') {
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    try {
      const payload = await response.json()
      if (typeof payload === 'string') return payload
      if (payload?.detail) return Array.isArray(payload.detail) ? payload.detail.map(item => item.msg || item).join('; ') : String(payload.detail)
      if (payload?.error) return String(payload.error)
      if (payload?.message) return String(payload.message)
    } catch {
      // Fall through to the text response for malformed JSON.
    }
  }
  try {
    const text = (await response.text()).trim()
    if (text) return text.slice(0, 500)
  } catch {
    // Use the fallback when the response body cannot be read.
  }
  return fallback
}

async function requestJson(url, options, fallback = '请求失败') {
  const response = await fetchWithTimeout(url, options)
  if (!response.ok) throw new Error(await readErrorMessage(response, fallback))
  try {
    return await response.json()
  } catch {
    throw new Error('服务器返回了无效数据')
  }
}

export async function getRooms() {
  return requestJson(`${BASE}/api/rooms`, undefined, '直播间加载失败')
}

export async function addRoom(name, url) {
  const res = await fetchWithTimeout(`${BASE}/api/rooms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, url }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteRoom(id) {
  await fetchWithTimeout(`${BASE}/api/rooms/${id}`, { method: 'DELETE' })
}

export async function toggleRoom(id) {
  const res = await fetchWithTimeout(`${BASE}/api/rooms/${id}/toggle`, { method: 'PATCH' })
  return res.json()
}

export async function getRecordings(roomId) {
  const res = await fetchWithTimeout(`${BASE}/api/rooms/${roomId}/recordings`)
  return res.json()
}

export async function getAllRecordings(page = 1, status = '', sort = 'start_time', order = 'desc') {
  const params = new URLSearchParams({ page, limit: 50, sort, order })
  if (status) params.set('status', status)
  const res = await fetchWithTimeout(`${BASE}/api/recordings?${params}`)
  return res.json()
}

export async function getRecordingClipsBulk(ids) {
  if (!ids.length) return {}
  const res = await fetchWithTimeout(`${BASE}/api/recording-clips/bulk?ids=${ids.join(',')}`)
  return res.json()
}

export async function getStatus() {
  const res = await fetchWithTimeout(`${BASE}/api/status`)
  return res.json()
}

export function createWS(onMessage) {
  const wsBase = (import.meta.env.VITE_WS_BASE || BASE.replace(/^http/, 'ws')).replace(/\/$/, '')
  let ws = null
  let reconnectTimer = null
  let closed = false
  let reconnectDelay = 2000  // start at 2s, exponential backoff to 30s max
  let reconnectAttempts = 0
  const MAX_RECONNECT_ATTEMPTS = 5

  function connect() {
    if (closed) return
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return
    reconnectAttempts += 1
    ws = new WebSocket(`${wsBase}/ws/events`)
    ws.onopen = () => {
      reconnectAttempts = 0
      reconnectDelay = 2000  // reset backoff on successful connection
    }
    ws.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)) } catch {}
    }
    ws.onclose = () => {
      if (closed || reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) return
      reconnectTimer = setTimeout(connect, reconnectDelay)
      reconnectDelay = Math.min(reconnectDelay * 2, 30000)
    }
    ws.onerror = () => {}  // onclose always fires after onerror; reconnect there
  }

  connect()
  return () => {
    closed = true
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    if (ws) { ws.onclose = null; ws.onerror = null; ws.close(); ws = null }
  }
}

export async function getGroups() {
  return requestJson(`${BASE}/api/groups`, undefined, '分组加载失败')
}

export async function getGroup(id) {
  return requestJson(`${BASE}/api/groups/${id}`, undefined, '分组详情加载失败')
}

export async function mergeGroup(id) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${id}/merge`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryModes(id) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${id}/retry-modes`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryStyles(id) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${id}/retry-styles`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryDirector(id) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${id}/retry-director`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryStyle(id, version) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${id}/retry-styles`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryQianchuan(id) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${id}/retry-qianchuan`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function uploadRecording(roomId, file, srtFile = null, durationSec = null, clipCount = 1) {
  const form = new FormData()
  form.append('file', file)
  if (srtFile) form.append('srt', srtFile)
  if (durationSec) form.append('duration_sec', String(durationSec))
  form.append('clip_count', String(clipCount))
  const res = await fetchWithTimeout(`${BASE}/api/rooms/${roomId}/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getRecordingClips(recordingId) {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/${recordingId}/clips`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function recordingClipDownloadUrl(clipId) {
  return `${BASE}/api/recording-clips/${clipId}/download`
}

export async function getRecording(id) {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/${id}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryTranscribe(id) {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/${id}/retry-transcribe`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryClip(id) {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/${id}/retry-clip`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getClips() {
  const res = await fetchWithTimeout(`${BASE}/api/clips`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function revealClip(id) {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/${id}/reveal-clip`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function createGroup(body) {
  const res = await fetchWithTimeout(`${BASE}/api/groups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateGroup(id, body) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function importGroupVideos(groupId, paths) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${groupId}/import-videos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteGroup(id) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function createCustomGroup(body) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/custom`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function uploadCustomGroupVideo(groupId, file, clipCount = 1) {
  const form = new FormData()
  form.append('file', file)
  form.append('clip_count', String(clipCount))
  const res = await fetchWithTimeout(`${BASE}/api/groups/${groupId}/upload-video`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function reassignRecording(recordingId, groupId) {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/${recordingId}/group`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_id: groupId ?? null }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteLocalFile(id) {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/${id}/local-file`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function reclip(roomName, date, durationSec, clipCount = 1) {
  const res = await fetchWithTimeout(`${BASE}/api/reclip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room_name: roomName, date, duration_sec: durationSec, clip_count: clipCount }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function clipMissing() {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/clip-missing`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function bulkCleanup() {
  const res = await fetchWithTimeout(`${BASE}/api/cleanup/local-files`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function getThumbnailUrl(recordingId) {
  return `${BASE}/api/recordings/${recordingId}/thumbnail`
}

export function formatBytes(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

// ── Products ─────────────────────────────────────────────────────────────────

export async function getProducts(keyword = '') {
  const q = keyword ? `?keyword=${encodeURIComponent(keyword)}` : ''
  const res = await fetchWithTimeout(`${BASE}/api/products${q}`)
  return res.json()
}

export async function createProduct(body) {
  const res = await fetchWithTimeout(`${BASE}/api/products`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function bulkCreateProducts(items) {
  const res = await fetchWithTimeout(`${BASE}/api/products/bulk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateProduct(id, body) {
  const res = await fetchWithTimeout(`${BASE}/api/products/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteProduct(id) {
  const res = await fetchWithTimeout(`${BASE}/api/products/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

// ── Publish Accounts ──────────────────────────────────────────────────────────

export async function getPublishAccounts() {
  const res = await fetchWithTimeout(`${BASE}/api/publish-accounts`)
  return res.json()
}

export async function createPublishAccount(body) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-accounts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deletePublishAccount(id) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-accounts/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function loginPublishAccount(id) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-accounts/${id}/login`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function checkAccountCookie(id) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-accounts/${id}/check-cookie`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Publish Tasks ─────────────────────────────────────────────────────────────

export async function getPublishTasks(status = null) {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks${q}`)
  return res.json()
}

export async function createPublishTask(body) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryPublishTask(id) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/${id}/retry`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function cancelPublishTask(id) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function regenPublishTaskMeta(id) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/${id}/regen-meta`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function bulkRegenPublishTaskMeta(task_ids) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/bulk-regen-meta`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_ids }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function reschedulePublishTask(id, scheduledAt) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scheduled_at: scheduledAt }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function bulkCancelPublishTasks(body) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/bulk-cancel`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getUnscheduledGroups(platform = 'douyin', roomId = null) {
  const q = new URLSearchParams({ platform })
  if (roomId) q.set('room_id', roomId)
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/unscheduled-groups?${q}`)
  return res.json()
}

export async function batchSchedulePublish(body) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/batch-schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function markManualPublish(taskId) {
  const res = await fetchWithTimeout(`${BASE}/api/publish-tasks/${taskId}/manual-publish`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Meta generation & product matching ────────────────────────────────────────

export async function generatePublishMeta(groupId) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${groupId}/generate-meta`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function matchGroupProduct(groupId) {
  const res = await fetchWithTimeout(`${BASE}/api/groups/${groupId}/match-product`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getStats() {
  const res = await fetchWithTimeout(`${BASE}/api/stats`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getProcessingProgress() {
  const res = await fetchWithTimeout(`${BASE}/api/recordings/processing-progress`)
  if (!res.ok) return {}
  return res.json()
}

export async function getClipJobs() {
  const res = await fetchWithTimeout(`${BASE}/api/clip-jobs`)
  if (!res.ok) return {}
  return res.json()
}

export async function getGpuStatus() {
  const res = await fetchWithTimeout(`${BASE}/api/gpu/status`)
  return res.json()
}

export async function reclipRecording(id, feedback) {
  return requestJson(`${BASE}/api/recordings/${id}/reclip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback: feedback || '' }),
  }, '重新剪辑失败')
}

export async function reclipGroupAll(groupId) {
  return requestJson(`${BASE}/api/groups/${groupId}/reclip-all`, { method: 'POST' }, '全部重剪失败')
}

// ── Qianchuan ────────────────────────────────────────────────────────────────

export async function generateQianchuanGroup(groupId) {
  return requestJson(`${BASE}/api/v2/qianchuan/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_id: groupId, generate_video: true }),
  }, '千川投流版生成失败')
}

export async function getQianchuanGroupResult(groupId) {
  return requestJson(`${BASE}/api/v2/qianchuan/group/${groupId}/result`, undefined, '千川投流版结果加载失败')
}

// ── Qianchuan Learning Upload ───────────────────────────────────────────────

export async function uploadQianchuanMaterials(mainFile, auxiliaryFiles = [], label = null, triggerAnalysis = true) {
  const form = new FormData()
  form.append('file', mainFile)
  for (const aux of auxiliaryFiles) {
    form.append('auxiliary', aux)
  }
  if (label) form.append('label', label)
  form.append('trigger_analysis', String(triggerAnalysis))
  const res = await fetchWithTimeout(`${BASE}/api/v2/qianchuan/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getQianchuanUploadJobStatus(jobId) {
  const res = await fetchWithTimeout(`${BASE}/api/v2/qianchuan/upload/${jobId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getQianchuanUploadServiceStatus() {
  const res = await fetchWithTimeout(`${BASE}/api/v2/qianchuan/upload-status`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── 画质增强 ──────────────────────────────────────────────────────────────────

export async function getEnhanceServiceStatus() {
  const res = await fetchWithTimeout(`${BASE}/api/enhance-service/status`)
  return res.json()
}

export async function createEnhanceJob(file, { model = 'general', targetRes = '1080p', denoise = 'medium', previewOnly = false } = {}) {
  const form = new FormData()
  form.append('file', file)
  form.append('model', model)
  form.append('target_res', targetRes)
  form.append('denoise', denoise)
  form.append('preview_only', String(previewOnly))
  const res = await fetchWithTimeout(`${BASE}/api/enhance-jobs`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getEnhanceJob(jobId) {
  const res = await fetchWithTimeout(`${BASE}/api/enhance-jobs/${jobId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function enhanceJobDownloadUrl(jobId) {
  return `${BASE}/api/enhance-jobs/${jobId}/download`
}

export async function cancelEnhanceJob(jobId) {
  await fetchWithTimeout(`${BASE}/api/enhance-jobs/${jobId}`, { method: 'DELETE' })
}

export function formatDuration(start, end) {
  if (!start) return '—'
  const s = new Date(start)
  const e = end ? new Date(end) : new Date()
  const sec = Math.floor((e - s) / 1000)
  const m = Math.floor(sec / 60)
  const h = Math.floor(m / 60)
  if (h > 0) return `${h}h ${m % 60}m`
  return `${m}m ${sec % 60}s`
}
