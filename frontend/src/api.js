const BASE = import.meta.env.DEV ? 'http://localhost:8899' : ''

export async function getRooms() {
  const res = await fetch(`${BASE}/api/rooms`)
  return res.json()
}

export async function addRoom(name, url) {
  const res = await fetch(`${BASE}/api/rooms`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, url }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteRoom(id) {
  await fetch(`${BASE}/api/rooms/${id}`, { method: 'DELETE' })
}

export async function toggleRoom(id) {
  const res = await fetch(`${BASE}/api/rooms/${id}/toggle`, { method: 'PATCH' })
  return res.json()
}

export async function getRecordings(roomId) {
  const res = await fetch(`${BASE}/api/rooms/${roomId}/recordings`)
  return res.json()
}

export async function getAllRecordings(page = 1, status = '', sort = 'start_time', order = 'desc') {
  const params = new URLSearchParams({ page, limit: 50, sort, order })
  if (status) params.set('status', status)
  const res = await fetch(`${BASE}/api/recordings?${params}`)
  return res.json()
}

export async function getRecordingClipsBulk(ids) {
  if (!ids.length) return {}
  const res = await fetch(`${BASE}/api/recording-clips/bulk?ids=${ids.join(',')}`)
  return res.json()
}

export async function getStatus() {
  const res = await fetch(`${BASE}/api/status`)
  return res.json()
}

export function createWS(onMessage) {
  const wsBase = import.meta.env.DEV ? 'ws://localhost:8899' : `ws://${location.host}`
  const ws = new WebSocket(`${wsBase}/ws/events`)
  ws.onmessage = (e) => onMessage(JSON.parse(e.data))
  ws.onclose = () => setTimeout(() => createWS(onMessage), 3000)
  return ws
}

export async function getGroups() {
  const res = await fetch(`${BASE}/api/groups`)
  return res.json()
}

export async function getGroup(id) {
  const res = await fetch(`${BASE}/api/groups/${id}`)
  return res.json()
}

export async function mergeGroup(id) {
  const res = await fetch(`${BASE}/api/groups/${id}/merge`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryModes(id) {
  const res = await fetch(`${BASE}/api/groups/${id}/retry-modes`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function uploadRecording(roomId, file, srtFile = null, durationSec = null, clipCount = 1) {
  const form = new FormData()
  form.append('file', file)
  if (srtFile) form.append('srt', srtFile)
  if (durationSec) form.append('duration_sec', String(durationSec))
  form.append('clip_count', String(clipCount))
  const res = await fetch(`${BASE}/api/rooms/${roomId}/upload`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getRecordingClips(recordingId) {
  const res = await fetch(`${BASE}/api/recordings/${recordingId}/clips`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function recordingClipDownloadUrl(clipId) {
  return `${BASE}/api/recording-clips/${clipId}/download`
}

export async function getRecording(id) {
  const res = await fetch(`${BASE}/api/recordings/${id}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryTranscribe(id) {
  const res = await fetch(`${BASE}/api/recordings/${id}/retry-transcribe`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryClip(id) {
  const res = await fetch(`${BASE}/api/recordings/${id}/retry-clip`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getClips() {
  const res = await fetch(`${BASE}/api/clips`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function revealClip(id) {
  const res = await fetch(`${BASE}/api/recordings/${id}/reveal-clip`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function createGroup(body) {
  const res = await fetch(`${BASE}/api/groups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateGroup(id, body) {
  const res = await fetch(`${BASE}/api/groups/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function importGroupVideos(groupId, paths) {
  const res = await fetch(`${BASE}/api/groups/${groupId}/import-videos`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paths }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteGroup(id) {
  const res = await fetch(`${BASE}/api/groups/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function createCustomGroup(body) {
  const res = await fetch(`${BASE}/api/groups/custom`, {
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
  const res = await fetch(`${BASE}/api/groups/${groupId}/upload-video`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function reassignRecording(recordingId, groupId) {
  const res = await fetch(`${BASE}/api/recordings/${recordingId}/group`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_id: groupId ?? null }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteLocalFile(id) {
  const res = await fetch(`${BASE}/api/recordings/${id}/local-file`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function reclip(roomName, date, durationSec, clipCount = 1) {
  const res = await fetch(`${BASE}/api/reclip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ room_name: roomName, date, duration_sec: durationSec, clip_count: clipCount }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function clipMissing() {
  const res = await fetch(`${BASE}/api/recordings/clip-missing`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function bulkCleanup() {
  const res = await fetch(`${BASE}/api/cleanup/local-files`, { method: 'POST' })
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
  const res = await fetch(`${BASE}/api/products${q}`)
  return res.json()
}

export async function createProduct(body) {
  const res = await fetch(`${BASE}/api/products`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function bulkCreateProducts(items) {
  const res = await fetch(`${BASE}/api/products/bulk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(items),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateProduct(id, body) {
  const res = await fetch(`${BASE}/api/products/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteProduct(id) {
  const res = await fetch(`${BASE}/api/products/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

// ── Publish Accounts ──────────────────────────────────────────────────────────

export async function getPublishAccounts() {
  const res = await fetch(`${BASE}/api/publish-accounts`)
  return res.json()
}

export async function createPublishAccount(body) {
  const res = await fetch(`${BASE}/api/publish-accounts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deletePublishAccount(id) {
  const res = await fetch(`${BASE}/api/publish-accounts/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function loginPublishAccount(id) {
  const res = await fetch(`${BASE}/api/publish-accounts/${id}/login`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Publish Tasks ─────────────────────────────────────────────────────────────

export async function getPublishTasks(status = null) {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await fetch(`${BASE}/api/publish-tasks${q}`)
  return res.json()
}

export async function createPublishTask(body) {
  const res = await fetch(`${BASE}/api/publish-tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function retryPublishTask(id) {
  const res = await fetch(`${BASE}/api/publish-tasks/${id}/retry`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function cancelPublishTask(id) {
  const res = await fetch(`${BASE}/api/publish-tasks/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function regenPublishTaskMeta(id) {
  const res = await fetch(`${BASE}/api/publish-tasks/${id}/regen-meta`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function reschedulePublishTask(id, scheduledAt) {
  const res = await fetch(`${BASE}/api/publish-tasks/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scheduled_at: scheduledAt }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function bulkCancelPublishTasks(body) {
  const res = await fetch(`${BASE}/api/publish-tasks/bulk-cancel`, {
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
  const res = await fetch(`${BASE}/api/publish-tasks/unscheduled-groups?${q}`)
  return res.json()
}

export async function batchSchedulePublish(body) {
  const res = await fetch(`${BASE}/api/publish-tasks/batch-schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Meta generation & product matching ────────────────────────────────────────

export async function generatePublishMeta(groupId) {
  const res = await fetch(`${BASE}/api/groups/${groupId}/generate-meta`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function matchGroupProduct(groupId) {
  const res = await fetch(`${BASE}/api/groups/${groupId}/match-product`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getStats() {
  const res = await fetch(`${BASE}/api/stats`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getProcessingProgress() {
  const res = await fetch(`${BASE}/api/recordings/processing-progress`)
  if (!res.ok) return {}
  return res.json()
}

export async function getClipJobs() {
  const res = await fetch(`${BASE}/api/clip-jobs`)
  if (!res.ok) return {}
  return res.json()
}

export async function getGpuStatus() {
  const res = await fetch(`${BASE}/api/gpu/status`)
  return res.json()
}

export async function reclipRecording(id, feedback) {
  const res = await fetch(`${BASE}/api/recordings/${id}/reclip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback: feedback || '' }),
  })
  if (!res.ok) throw new Error((await res.json()).detail || '重新剪辑失败')
  return res.json()
}

export async function reclipGroupAll(groupId) {
  const res = await fetch(`${BASE}/api/groups/${groupId}/reclip-all`, { method: 'POST' })
  if (!res.ok) throw new Error((await res.json()).detail || '全部重剪失败')
  return res.json()
}

// ── 画质增强 ──────────────────────────────────────────────────────────────────

export async function getEnhanceServiceStatus() {
  const res = await fetch(`${BASE}/api/enhance-service/status`)
  return res.json()
}

export async function createEnhanceJob(file, { model = 'general', targetRes = '1080p', denoise = 'medium', previewOnly = false } = {}) {
  const form = new FormData()
  form.append('file', file)
  form.append('model', model)
  form.append('target_res', targetRes)
  form.append('denoise', denoise)
  form.append('preview_only', String(previewOnly))
  const res = await fetch(`${BASE}/api/enhance-jobs`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getEnhanceJob(jobId) {
  const res = await fetch(`${BASE}/api/enhance-jobs/${jobId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function enhanceJobDownloadUrl(jobId) {
  return `${BASE}/api/enhance-jobs/${jobId}/download`
}

export async function cancelEnhanceJob(jobId) {
  await fetch(`${BASE}/api/enhance-jobs/${jobId}`, { method: 'DELETE' })
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
