<template>
  <div>
    <div class="toolbar">
      <h2>录像历史</h2>
      <select v-model="filterRoom" class="room-filter">
        <option value="">全部房间</option>
        <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
      </select>
    </div>

    <table class="recordings-table">
      <thead>
        <tr>
          <th>文件名</th>
          <th>房间</th>
          <th>开始时间</th>
          <th>时长</th>
          <th>大小</th>
          <th>同步</th>
          <th>字幕</th>
          <th>剪辑</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="rec in filtered" :key="rec.id">
          <td class="filename">{{ rec.filename }}</td>
          <td>{{ rec.room_name }}</td>
          <td>{{ fmtTime(rec.start_time) }}</td>
          <td>{{ formatDuration(rec.start_time, rec.end_time) }}</td>
          <td>{{ formatBytes(rec.size_bytes) }}</td>
          <td>
            <span :class="['badge', rec.synced ? 'green' : 'dim']">
              {{ rec.synced ? '已同步' : '待同步' }}
            </span>
          </td>
          <td>
            <a v-if="rec.transcribed === 2"
               :href="`${apiBase}/api/recordings/${rec.id}/srt`"
               class="badge blue" download>
              下载 SRT
            </a>
            <span v-else-if="rec.transcribed === 1" class="badge yellow">转录中</span>
            <button v-else-if="rec.transcribed === -1" class="badge red btn-retry" @click="doRetryTranscribe(rec)">重试</button>
            <span v-else class="badge dim">待转录</span>
          </td>
          <td>
            <a v-if="rec.clipped === 2"
               :href="`${apiBase}/api/recordings/${rec.id}/clip`"
               class="badge purple">
              下载剪辑
            </a>
            <span v-else-if="rec.clipped === 1" class="badge yellow">剪辑中</span>
            <button v-else-if="rec.clipped === -1" class="badge red btn-retry" @click="doRetryClip(rec)">重试</button>
            <span v-else class="badge dim">—</span>
          </td>
        </tr>
        <tr v-if="filtered.length === 0">
          <td colspan="8" class="empty">暂无录像记录</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getAllRecordings, getRooms, retryTranscribe, retryClip, formatBytes, formatDuration, createWS } from '../api.js'

const recordings = ref([])
const rooms = ref([])
const filterRoom = ref('')
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''
let ws = null

async function doRetryTranscribe(rec) {
  try {
    await retryTranscribe(rec.id)
    await load()
  } catch (e) {
    alert(e.message || '重试失败')
  }
}

async function doRetryClip(rec) {
  try {
    await retryClip(rec.id)
    await load()
  } catch (e) {
    alert(e.message || '重试失败')
  }
}

const filtered = computed(() =>
  filterRoom.value
    ? recordings.value.filter(r => r.room_id === Number(filterRoom.value))
    : recordings.value
)

const fmtTime = (s) => s ? new Date(s).toLocaleString('zh-CN') : '—'

async function load() {
  [recordings.value, rooms.value] = await Promise.all([getAllRecordings(), getRooms()])
}

onMounted(() => {
  load()
  ws = createWS((msg) => {
    if (msg.type === 'transcribed' || msg.type === 'clipped') load()
  })
})

onUnmounted(() => ws?.close())
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }
.room-filter { background: #1a1a1a; border: 1px solid #333; color: #ccc; padding: 7px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.recordings-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.recordings-table th { text-align: left; padding: 10px 14px; color: #666; font-weight: 500; border-bottom: 1px solid #222; }
.recordings-table td { padding: 12px 14px; border-bottom: 1px solid #1e1e1e; }
.recordings-table tr:hover td { background: #1a1a1a; }
.filename { font-family: monospace; font-size: 12px; color: #aaa; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; text-decoration: none; display: inline-block; }
.badge.green  { background: rgba(34,197,94,0.15);  color: #22c55e; }
.badge.blue   { background: rgba(99,102,241,0.15); color: #818cf8; }
.badge.yellow { background: rgba(251,191,36,0.15); color: #fbbf24; }
.badge.red    { background: rgba(254,44,85,0.15);  color: #fe2c55; }
.badge.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge.dim    { background: #2a2a2a; color: #555; }
.badge.blue:hover, .badge.purple:hover { filter: brightness(1.3); }
.btn-retry { cursor: pointer; border: none; font-family: inherit; }
.empty { text-align: center; color: #444; padding: 40px; }
</style>
