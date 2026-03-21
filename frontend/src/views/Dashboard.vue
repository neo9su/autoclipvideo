<template>
  <div>
    <!-- Stats Bar -->
    <div class="stats-bar">
      <div class="stat">
        <span class="stat-num">{{ status.enabled_rooms ?? '—' }}</span>
        <span class="stat-label">监控房间</span>
      </div>
      <div class="stat">
        <span class="stat-num live">{{ status.active_recordings ?? '—' }}</span>
        <span class="stat-label">录制中</span>
      </div>
      <div class="stat">
        <span class="stat-num">{{ status.total_recordings ?? '—' }}</span>
        <span class="stat-label">总录像数</span>
      </div>
      <div class="stat">
        <span class="stat-num">{{ formatBytes(status.total_bytes) }}</span>
        <span class="stat-label">总存储</span>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <h2>直播间列表</h2>
      <button class="btn-primary" @click="showAdd = true">+ 添加房间</button>
    </div>

    <!-- Room Cards -->
    <div class="rooms-grid">
      <div v-for="room in rooms" :key="room.id" class="room-card">
        <div class="room-header">
          <div>
            <div class="room-name">{{ room.name }}</div>
            <div class="room-url">{{ room.url }}</div>
          </div>
          <div :class="['status-badge', room.live_status]">
            {{ statusLabel(room.live_status) }}
          </div>
        </div>

        <div class="room-info" v-if="room.recording">
          <div class="recording-indicator">
            <span class="dot"></span> 录制中
          </div>
          <div class="segment-name">{{ room.current_segment }}</div>
          <div class="segment-dur">已录 {{ formatDuration(room.session_start, null) }}</div>
        </div>
        <div class="room-info" v-else>
          <div class="offline-info">未在录制</div>
        </div>

        <div class="room-actions">
          <button class="btn-sm" @click="toggle(room)">
            {{ room.enabled ? '停用监控' : '启用监控' }}
          </button>
          <label class="btn-sm upload-btn" :class="{ uploading: uploadingRooms.has(room.id) }">
            {{ uploadingRooms.has(room.id) ? '上传中…' : '上传视频' }}
            <input type="file" accept="video/*" style="display:none" @change="e => pickVideo(room, e)" :disabled="uploadingRooms.has(room.id)" />
          </label>
          <input :ref="el => srtInputs[room.id] = el" type="file" accept=".srt" style="display:none" @change="e => onSrtPicked(e)" />
          <button class="btn-sm danger" @click="remove(room)">删除</button>
        </div>
      </div>

      <div v-if="rooms.length === 0" class="empty">
        暂无房间，点击「添加房间」开始监控
      </div>
    </div>

    <!-- Add Room Modal -->
    <div v-if="showAdd" class="modal-overlay" @click.self="showAdd = false">
      <div class="modal">
        <h3>添加直播间</h3>
        <label>房间名称</label>
        <input v-model="newName" placeholder="例：张三的直播间" />
        <label>抖音直播间 URL</label>
        <input v-model="newUrl" placeholder="https://live.douyin.com/..." />
        <div class="modal-actions">
          <button class="btn-sm" @click="showAdd = false">取消</button>
          <button class="btn-primary" @click="submit" :disabled="!newName || !newUrl">确认添加</button>
        </div>
        <div v-if="addError" class="error-msg">{{ addError }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getRooms, addRoom, deleteRoom, toggleRoom, getStatus, createWS, formatBytes, formatDuration, uploadRecording } from '../api.js'

const rooms = ref([])
const status = ref({})
const showAdd = ref(false)
const newName = ref('')
const newUrl = ref('')
const addError = ref('')
const uploadingRooms = ref(new Set())
const srtInputs = ref({})
let pendingUpload = null  // { room, file }
let ws = null
let timer = null

const statusLabel = (s) => ({ live: '直播中', offline: '离线', unknown: '检测中' }[s] || '未知')

async function load() {
  [rooms.value, status.value] = await Promise.all([getRooms(), getStatus()])
}

async function submit() {
  addError.value = ''
  try {
    await addRoom(newName.value.trim(), newUrl.value.trim())
    newName.value = ''
    newUrl.value = ''
    showAdd.value = false
    await load()
  } catch (e) {
    addError.value = e.message || '添加失败'
  }
}

async function toggle(room) {
  await toggleRoom(room.id)
  await load()
}

function pickVideo(room, event) {
  const file = event.target.files[0]
  if (!file) return
  event.target.value = ''
  pendingUpload = { room, file }
  if (confirm('是否同时上传 SRT 字幕文件？\n（有字幕则跳过 GPU 转录，直接开始剪辑）')) {
    srtInputs.value[room.id]?.click()
  } else {
    doUpload(room, file, null)
  }
}

function onSrtPicked(event) {
  const srtFile = event.target.files[0] || null
  event.target.value = ''
  if (!pendingUpload) return
  const { room, file } = pendingUpload
  pendingUpload = null
  doUpload(room, file, srtFile)
}

async function doUpload(room, file, srtFile) {
  uploadingRooms.value = new Set([...uploadingRooms.value, room.id])
  try {
    await uploadRecording(room.id, file, srtFile)
    await load()
  } catch (e) {
    alert(`上传失败: ${e.message}`)
  } finally {
    uploadingRooms.value = new Set([...uploadingRooms.value].filter(id => id !== room.id))
  }
}

async function remove(room) {
  if (!confirm(`确认删除「${room.name}」？`)) return
  await deleteRoom(room.id)
  await load()
}

onMounted(() => {
  load()
  ws = createWS(() => load())
  timer = setInterval(load, 10000)
})

onUnmounted(() => {
  ws?.close()
  clearInterval(timer)
})
</script>

<style scoped>
.stats-bar { display: flex; gap: 16px; margin-bottom: 24px; }
.stat { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px; padding: 16px 24px; flex: 1; }
.stat-num { display: block; font-size: 28px; font-weight: 700; color: #fff; }
.stat-num.live { color: #fe2c55; }
.stat-label { font-size: 12px; color: #666; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }
.btn-primary { background: #fe2c55; color: #fff; border: none; padding: 8px 18px; border-radius: 6px; cursor: pointer; font-size: 14px; }
.btn-primary:hover { background: #e0203d; }
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
.rooms-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.room-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 18px; }
.room-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.room-name { font-weight: 600; font-size: 15px; margin-bottom: 4px; }
.room-url { font-size: 11px; color: #555; word-break: break-all; max-width: 200px; }
.status-badge { font-size: 12px; padding: 3px 10px; border-radius: 20px; white-space: nowrap; }
.status-badge.live { background: rgba(254,44,85,0.15); color: #fe2c55; }
.status-badge.offline { background: #2a2a2a; color: #666; }
.status-badge.unknown { background: #2a2a2a; color: #888; }
.room-info { min-height: 52px; margin-bottom: 14px; }
.recording-indicator { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #fe2c55; margin-bottom: 4px; }
.dot { width: 8px; height: 8px; background: #fe2c55; border-radius: 50%; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity:1 } 50% { opacity:0.3 } }
.segment-name { font-size: 12px; color: #888; margin-bottom: 2px; }
.segment-dur { font-size: 12px; color: #666; }
.offline-info { font-size: 13px; color: #444; padding-top: 6px; }
.room-actions { display: flex; gap: 8px; }
.btn-sm { background: #2a2a2a; border: 1px solid #333; color: #ccc; padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.btn-sm:hover { background: #333; }
.btn-sm.danger:hover { background: rgba(254,44,85,0.2); color: #fe2c55; border-color: #fe2c55; }
.upload-btn { cursor: pointer; }
.upload-btn.uploading { opacity: 0.5; cursor: not-allowed; }
.empty { color: #444; text-align: center; padding: 60px; grid-column: 1/-1; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #1e1e1e; border: 1px solid #333; border-radius: 14px; padding: 28px; width: 440px; }
.modal h3 { margin-bottom: 20px; font-size: 16px; }
.modal label { display: block; font-size: 12px; color: #888; margin-bottom: 6px; margin-top: 14px; }
.modal input { width: 100%; background: #111; border: 1px solid #333; color: #e0e0e0; padding: 9px 12px; border-radius: 8px; font-size: 14px; outline: none; }
.modal input:focus { border-color: #fe2c55; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 22px; }
.error-msg { color: #fe2c55; font-size: 13px; margin-top: 10px; }
</style>
