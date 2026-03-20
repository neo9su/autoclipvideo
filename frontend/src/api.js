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

export async function getAllRecordings(page = 1) {
  const res = await fetch(`${BASE}/api/recordings?page=${page}&limit=50`)
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

export async function bulkCleanup() {
  const res = await fetch(`${BASE}/api/cleanup/local-files`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export function formatBytes(bytes) {
  if (!bytes) return '—'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
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
