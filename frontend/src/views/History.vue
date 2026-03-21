<template>
  <div>
    <div class="toolbar">
      <h2>录像历史</h2>
      <div class="toolbar-right">
        <select v-model="filterRoom" class="room-filter">
          <option value="">全部房间</option>
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <button class="btn-cleanup" @click="doBulkCleanup" title="删除所有已处理文件的本地副本">
          批量清理
        </button>
      </div>
    </div>

    <table class="recordings-table">
      <thead>
        <tr>
          <th></th>
          <th>文件名</th>
          <th>房间</th>
          <th>开始时间</th>
          <th>时长</th>
          <th>大小</th>
          <th>同步</th>
          <th>字幕</th>
          <th>剪辑</th>
          <th>本地文件</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="rec in filtered" :key="rec.id">
          <td class="thumb-cell">
            <img v-if="rec.thumbnail"
                 :src="getThumbnailUrl(rec.id)"
                 class="thumb-img"
                 @error="e => e.target.style.display='none'" />
            <div v-else class="thumb-placeholder"></div>
          </td>
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
            <div v-if="rec.clipped === 2" class="clip-actions">
              <a :href="`${apiBase}/api/recordings/${rec.id}/clip`" class="badge purple">下载剪辑</a>
              <button class="badge dim btn-retry" @click="doRevealClip(rec)" title="在 Finder 中显示">打开位置</button>
            </div>
            <span v-else-if="rec.clipped === 1" class="badge yellow">剪辑中</span>
            <button v-else-if="rec.clipped === -1" class="badge red btn-retry" @click="doRetryClip(rec)">重试</button>
            <span v-else class="badge dim">—</span>
          </td>
          <td>
            <span v-if="rec.local_deleted" class="badge dim">已清理</span>
            <button v-else-if="canCleanup(rec)" class="badge red btn-retry" @click="doDeleteLocal(rec)">清理</button>
            <span v-else class="badge dim">—</span>
          </td>
        </tr>
        <tr v-if="filtered.length === 0">
          <td colspan="10" class="empty">暂无录像记录</td>
        </tr>
      </tbody>
    </table>

    <!-- Pagination -->
    <div v-if="totalPages > 1" class="pagination">
      <button class="page-btn" :disabled="page === 1" @click="goPage(page - 1)">‹</button>
      <button
        v-for="p in pageRange" :key="p"
        :class="['page-btn', p === page && 'active']"
        @click="goPage(p)">
        {{ p }}
      </button>
      <button class="page-btn" :disabled="page === totalPages" @click="goPage(page + 1)">›</button>
      <span class="page-info">共 {{ total }} 条</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getAllRecordings, getRooms, retryTranscribe, retryClip, revealClip,
         deleteLocalFile, bulkCleanup, formatBytes, formatDuration, createWS, getThumbnailUrl } from '../api.js'
import { useToast } from '../composables/toast.js'

const { show } = useToast()

const recordings = ref([])
const rooms = ref([])
const filterRoom = ref('')
const page = ref(1)
const total = ref(0)
const totalPages = ref(1)
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''
let ws = null

const filtered = computed(() =>
  filterRoom.value
    ? recordings.value.filter(r => r.room_id === Number(filterRoom.value))
    : recordings.value
)

const pageRange = computed(() => {
  const pages = []
  const start = Math.max(1, page.value - 2)
  const end = Math.min(totalPages.value, page.value + 2)
  for (let p = start; p <= end; p++) pages.push(p)
  return pages
})

const fmtTime = (s) => s ? new Date(s).toLocaleString('zh-CN') : '—'

const canCleanup = (rec) =>
  rec.synced === 1 &&
  !rec.local_deleted &&
  rec.transcribed !== 0 && rec.transcribed !== 1 &&
  rec.clipped !== 0 && rec.clipped !== 1

async function load() {
  const [data, r] = await Promise.all([getAllRecordings(page.value), getRooms()])
  recordings.value = data.items
  total.value = data.total
  totalPages.value = data.pages
  rooms.value = r
}

async function goPage(p) {
  page.value = p
  await load()
}

async function doRetryTranscribe(rec) {
  try {
    await retryTranscribe(rec.id)
    show('已重新提交转录任务', 'success')
    await load()
  } catch (e) {
    show(e.message || '重试失败', 'error')
  }
}

async function doRetryClip(rec) {
  try {
    await retryClip(rec.id)
    show('已重新提交剪辑任务', 'success')
    await load()
  } catch (e) {
    show(e.message || '重试失败', 'error')
  }
}

async function doRevealClip(rec) {
  try {
    await revealClip(rec.id)
  } catch (e) {
    show(e.message || '打开失败', 'error')
  }
}

async function doDeleteLocal(rec) {
  try {
    await deleteLocalFile(rec.id)
    show('本地文件已删除', 'success')
    await load()
  } catch (e) {
    show(e.message || '删除失败', 'error')
  }
}

async function doBulkCleanup() {
  try {
    const { deleted, total_eligible } = await bulkCleanup()
    show(`清理完成：删除 ${deleted} / ${total_eligible} 个文件`, 'success')
    await load()
  } catch (e) {
    show(e.message || '清理失败', 'error')
  }
}

onMounted(() => {
  load()
  ws = createWS((msg) => {
    if (msg.type === 'transcribed') {
      show('转录完成', 'success')
      load()
    } else if (msg.type === 'clipped') {
      show('剪辑完成', 'success')
      load()
    }
  })
})

onUnmounted(() => ws?.close())
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }
.toolbar-right { display: flex; gap: 10px; align-items: center; }
.room-filter { background: #1a1a1a; border: 1px solid #333; color: #ccc; padding: 7px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-cleanup { background: #2a2a2a; border: 1px solid #444; color: #888; padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-cleanup:hover { background: #333; color: #ccc; }
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
.clip-actions { display: flex; flex-direction: column; gap: 4px; }
.empty { text-align: center; color: #444; padding: 40px; }
.pagination { display: flex; align-items: center; gap: 6px; margin-top: 20px; justify-content: center; }
.page-btn { background: #2a2a2a; border: 1px solid #333; color: #888; padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; min-width: 36px; }
.page-btn:hover:not(:disabled) { background: #333; color: #ccc; }
.page-btn.active { background: #fe2c55; color: #fff; border-color: #fe2c55; }
.page-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.page-info { font-size: 12px; color: #555; margin-left: 8px; }
.thumb-cell { width: 88px; padding: 8px 14px; }
.thumb-img { width: 80px; height: 45px; object-fit: cover; border-radius: 4px; display: block; }
.thumb-placeholder { width: 80px; height: 45px; background: #1e1e1e; border-radius: 4px; }
</style>
