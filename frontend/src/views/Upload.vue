<template>
  <div>
    <div class="toolbar">
      <h2>上传剪辑</h2>
    </div>

    <!-- Upload form -->
    <div class="upload-form">
      <div class="drop-row">
        <!-- Video drop zone -->
        <div
          :class="['drop-zone', dragVideo && 'drag-over', videoFile && 'has-file']"
          @dragover.prevent="dragVideo = true"
          @dragleave="dragVideo = false"
          @drop.prevent="onDropVideo"
          @click="$refs.videoInput.click()"
        >
          <input ref="videoInput" type="file" accept="video/*" style="display:none" @change="onPickVideo" />
          <div v-if="videoFile" class="file-info">
            <span class="file-label">视频</span>
            <span class="file-name">{{ videoFile.name }}</span>
            <span class="file-size">{{ formatBytes(videoFile.size) }}</span>
          </div>
          <div v-else class="drop-hint">
            <span class="drop-plus">+</span>
            <span class="drop-main">拖入或点击选择视频</span>
            <span class="drop-sub">MP4 / MOV / AVI</span>
          </div>
        </div>

        <!-- SRT drop zone -->
        <div
          :class="['drop-zone', 'srt-zone', dragSrt && 'drag-over', srtFile && 'has-file']"
          @dragover.prevent="dragSrt = true"
          @dragleave="dragSrt = false"
          @drop.prevent="onDropSrt"
          @click="$refs.srtInput.click()"
        >
          <input ref="srtInput" type="file" accept=".srt" style="display:none" @change="onPickSrt" />
          <div v-if="srtFile" class="file-info">
            <span class="file-label">字幕</span>
            <span class="file-name">{{ srtFile.name }}</span>
          </div>
          <div v-else class="drop-hint">
            <span class="srt-badge">SRT</span>
            <span class="drop-main">字幕文件（可选）</span>
            <span class="drop-sub">有 SRT 立即剪辑，无则 GPU 转录后剪辑</span>
          </div>
        </div>
      </div>

      <!-- Settings row -->
      <div class="settings-row">
        <select v-model="roomId" class="sel">
          <option value="">选择房间</option>
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <div class="dur-wrap">
          <input v-model.number="duration" type="number" min="10" max="1800" class="sel dur-input" />
          <span class="dur-unit">秒</span>
        </div>
        <button
          class="btn-submit"
          :disabled="!videoFile || !roomId || uploading"
          @click="submit"
        >
          {{ uploading ? '上传中…' : '上传并剪辑' }}
        </button>
        <button v-if="videoFile || srtFile" class="btn-clear" @click="clearFiles">清除</button>
      </div>

      <!-- Upload progress bar -->
      <div v-if="uploading" class="progress-wrap">
        <div class="progress-bar">
          <div class="progress-fill animate"></div>
        </div>
        <span class="progress-label">上传中，请稍候…</span>
      </div>
    </div>

    <!-- Jobs list -->
    <div v-if="jobs.length" class="jobs-section">
      <h3 class="jobs-title">本次上传任务</h3>
      <table class="jobs-table">
        <thead>
          <tr>
            <th>文件名</th>
            <th>房间</th>
            <th>时长</th>
            <th>字幕</th>
            <th>剪辑状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td class="fname">{{ j.filename }}</td>
            <td>{{ j.roomName }}</td>
            <td>{{ j.duration }}s</td>
            <td>
              <span :class="['badge', transcribeCls(j.transcribed)]">{{ transcribeLbl(j.transcribed) }}</span>
            </td>
            <td>
              <span :class="['badge', clipCls(j.clipped)]">{{ clipLbl(j.clipped) }}</span>
            </td>
            <td>
              <div v-if="j.clipped === 2" class="action-col">
                <a :href="clipDownloadUrl(j.id)" class="badge purple" download>下载剪辑</a>
                <button class="badge dim btn-action" @click="doReveal(j.id)">打开文件夹</button>
              </div>
              <span v-else class="badge dim">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getRooms, uploadRecording, getRecording, revealClip, formatBytes } from '../api.js'
import { useToast } from '../composables/toast.js'

const { show } = useToast()
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''

const rooms = ref([])
const roomId = ref('')
const duration = ref(60)
const videoFile = ref(null)
const srtFile = ref(null)
const dragVideo = ref(false)
const dragSrt = ref(false)
const uploading = ref(false)
const jobs = ref([])

const videoInput = ref(null)
const srtInput = ref(null)

let pollTimer = null

const STORAGE_KEY = 'upload_jobs'

function saveJobs() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs.value))
}

onMounted(async () => {
  rooms.value = await getRooms()
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    jobs.value = JSON.parse(saved)
    if (jobs.value.some(j => j.clipped !== 2 && j.clipped !== -1)) {
      startPolling()
    }
  }
})

onUnmounted(() => {
  clearInterval(pollTimer)
})

function onDropVideo(e) {
  dragVideo.value = false
  const f = e.dataTransfer.files[0]
  if (f) videoFile.value = f
}

function onPickVideo(e) {
  videoFile.value = e.target.files[0] || null
  e.target.value = ''
}

function onDropSrt(e) {
  dragSrt.value = false
  const f = e.dataTransfer.files[0]
  if (f) srtFile.value = f
}

function onPickSrt(e) {
  srtFile.value = e.target.files[0] || null
  e.target.value = ''
}

function clearFiles() {
  videoFile.value = null
  srtFile.value = null
}

async function submit() {
  if (!videoFile.value || !roomId.value || uploading.value) return
  uploading.value = true
  try {
    const room = rooms.value.find(r => r.id === Number(roomId.value))
    const result = await uploadRecording(roomId.value, videoFile.value, srtFile.value, duration.value)
    const job = {
      id: result.id,
      filename: result.filename,
      roomName: room?.name || '—',
      duration: duration.value,
      transcribed: srtFile.value ? 2 : 0,
      clipped: 0,
    }
    jobs.value.unshift(job)
    saveJobs()
    show('上传成功，剪辑任务已提交', 'success')
    clearFiles()
    startPolling()
  } catch (e) {
    show(e.message || '上传失败', 'error')
  } finally {
    uploading.value = false
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(pollJobs, 3000)
}

async function pollJobs() {
  const pending = jobs.value.filter(j => j.clipped !== 2 && j.clipped !== -1)
  if (!pending.length) {
    clearInterval(pollTimer)
    pollTimer = null
    return
  }
  for (const j of pending) {
    try {
      const rec = await getRecording(j.id)
      j.transcribed = rec.transcribed
      j.clipped = rec.clipped
      if (rec.clipped === 2) show(`剪辑完成：${rec.filename}`, 'success')
    } catch {}
  }
  saveJobs()
}

function clipDownloadUrl(id) {
  return `${apiBase}/api/recordings/${id}/clip`
}

async function doReveal(id) {
  try { await revealClip(id) } catch (e) { show('打开失败', 'error') }
}

function transcribeCls(v) {
  if (v === 2) return 'green'
  if (v === 1) return 'yellow'
  if (v === -1) return 'red'
  return 'dim'
}

function transcribeLbl(v) {
  if (v === 2) return '已转录'
  if (v === 1) return '转录中'
  if (v === -1) return '转录失败'
  return '待转录'
}

function clipCls(v) {
  if (v === 2) return 'green'
  if (v === 1) return 'yellow'
  if (v === -1) return 'red'
  return 'dim'
}

function clipLbl(v) {
  if (v === 2) return '剪辑完成'
  if (v === 1) return '剪辑中…'
  if (v === -1) return '剪辑失败'
  return '等待中'
}
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }

.upload-form { background: #141414; border: 1px solid #2a2a2a; border-radius: 10px; padding: 24px; margin-bottom: 28px; }

.drop-row { display: flex; gap: 16px; margin-bottom: 16px; }

.drop-zone {
  flex: 1; min-height: 130px; border: 2px dashed #333; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: border-color 0.2s, background 0.2s;
}
.drop-zone:hover, .drop-zone.drag-over { border-color: #fe2c55; background: rgba(254,44,85,0.05); }
.drop-zone.has-file { border-style: solid; border-color: #444; }
.srt-zone { flex: 0 0 240px; }

.drop-hint { display: flex; flex-direction: column; align-items: center; gap: 6px; pointer-events: none; }
.drop-plus { font-size: 32px; color: #444; line-height: 1; }
.drop-main { font-size: 14px; color: #aaa; }
.drop-sub { font-size: 12px; color: #555; }
.srt-badge { font-size: 20px; font-weight: 700; color: #666; letter-spacing: 2px; }

.file-info { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 12px; pointer-events: none; }
.file-label { font-size: 11px; color: #555; text-transform: uppercase; letter-spacing: 1px; }
.file-name { font-size: 13px; color: #ddd; word-break: break-all; text-align: center; max-width: 200px; }
.file-size { font-size: 12px; color: #666; }

.settings-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sel { background: #1a1a1a; border: 1px solid #333; color: #ccc; padding: 8px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.dur-wrap { display: flex; align-items: center; gap: 6px; }
.dur-input { width: 80px; }
.dur-unit { font-size: 13px; color: #666; }

.btn-submit {
  background: #fe2c55; color: #fff; border: none; padding: 8px 22px;
  border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500;
}
.btn-submit:hover:not(:disabled) { background: #e0254b; }
.btn-submit:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-clear { background: #2a2a2a; border: 1px solid #444; color: #888; padding: 8px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-clear:hover { color: #ccc; }

.progress-wrap { margin-top: 16px; display: flex; align-items: center; gap: 12px; }
.progress-bar { flex: 1; height: 4px; background: #222; border-radius: 2px; overflow: hidden; }
.progress-fill { height: 100%; background: #fe2c55; border-radius: 2px; }
.progress-fill.animate { width: 100%; animation: indeterminate 1.4s infinite ease-in-out; }
@keyframes indeterminate {
  0%   { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
.progress-label { font-size: 12px; color: #666; white-space: nowrap; }

.jobs-section { margin-top: 4px; }
.jobs-title { font-size: 14px; font-weight: 500; color: #888; margin-bottom: 12px; }
.jobs-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.jobs-table th { text-align: left; padding: 10px 14px; color: #666; font-weight: 500; border-bottom: 1px solid #222; }
.jobs-table td { padding: 12px 14px; border-bottom: 1px solid #1a1a1a; }
.jobs-table tr:hover td { background: #141414; }
.fname { font-family: monospace; font-size: 12px; color: #aaa; }

.badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; text-decoration: none; display: inline-block; }
.badge.green  { background: rgba(34,197,94,0.15);  color: #22c55e; }
.badge.yellow { background: rgba(251,191,36,0.15); color: #fbbf24; }
.badge.red    { background: rgba(254,44,85,0.15);  color: #fe2c55; }
.badge.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge.dim    { background: #2a2a2a; color: #555; }
.badge.purple:hover { filter: brightness(1.3); }
.action-col { display: flex; flex-direction: column; gap: 4px; }
.btn-action { border: none; cursor: pointer; }
</style>
