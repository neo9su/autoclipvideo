<template>
  <div>
    <div class="toolbar">
      <h2>录像历史</h2>
      <div class="toolbar-right">
        <select v-model="filterRoom" class="room-filter">
          <option value="">全部房间</option>
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
      </div>
    </div>

    <!-- Stats panel -->
    <div class="stats-panel">
      <div class="stats-group">
        <span class="stats-label">转录</span>
        <button :class="['stats-item','yellow', filterStatus==='transcribe_running' && 'active']" v-if="stats.transcribe_running" @click="toggleFilter('transcribe_running')">进行中 {{ stats.transcribe_running }}</button>
        <button :class="['stats-item','dim',    filterStatus==='transcribe_pending' && 'active']" v-if="stats.transcribe_pending" @click="toggleFilter('transcribe_pending')">等待中 {{ stats.transcribe_pending }}</button>
        <button :class="['stats-item','red',    filterStatus==='transcribe_failed'  && 'active']" v-if="stats.transcribe_failed"  @click="toggleFilter('transcribe_failed')">失败 {{ stats.transcribe_failed }}</button>
        <span class="stats-item dim" v-if="!stats.transcribe_running && !stats.transcribe_pending && !stats.transcribe_failed">空闲</span>
      </div>
      <div class="stats-divider"></div>
      <div class="stats-group">
        <span class="stats-label">剪辑</span>
        <button :class="['stats-item','yellow', filterStatus==='clip_running'  && 'active']" v-if="stats.clip_running"  @click="toggleFilter('clip_running')">进行中 {{ stats.clip_running }}</button>
        <button :class="['stats-item','dim',    filterStatus==='clip_pending'  && 'active']" v-if="stats.clip_pending"  @click="toggleFilter('clip_pending')">等待中 {{ stats.clip_pending }}</button>
        <button :class="['stats-item','red',    filterStatus==='clip_failed'   && 'active']" v-if="stats.clip_failed"   @click="toggleFilter('clip_failed')">失败 {{ stats.clip_failed }}</button>
        <span class="stats-item dim" v-if="!stats.clip_running && !stats.clip_pending && !stats.clip_failed">空闲</span>
      </div>
      <div class="stats-divider"></div>
      <button :class="['stats-busy', filterStatus==='running' && 'active-busy']" @click="isBusy && toggleFilter('running')" :style="isBusy ? 'cursor:pointer' : ''">
        <span :class="['busy-dot', isBusy ? 'busy' : 'idle']"></span>
        <span class="stats-label">{{ isBusy ? '处理中' : '空闲' }}</span>
      </button>
      <div class="stats-divider"></div>
      <button class="btn-cleanup btn-clip-missing" @click="doClipMissing">补发剪辑</button>
    </div>

    <!-- Filter + Sort bar -->
    <div class="filter-sort-bar">
      <div class="filter-btns">
        <button :class="['filter-btn', filterStatus==='' && 'active']"       @click="toggleFilter('')">全部</button>
        <button :class="['filter-btn','green',  filterStatus==='success' && 'active']" @click="toggleFilter('success')">成功</button>
        <button :class="['filter-btn','yellow', filterStatus==='active'  && 'active']" @click="toggleFilter('active')">进行中</button>
        <button :class="['filter-btn','red',    filterStatus==='failed'  && 'active']" @click="toggleFilter('failed')">失败</button>
      </div>
      <div class="sort-btns">
        <button class="sort-btn" @click="cycleSort('start_time')">
          时间 <span class="sort-arrow">{{ sortField==='start_time' ? (sortOrder==='desc' ? '↓' : '↑') : '↕' }}</span>
        </button>
        <button class="sort-btn" @click="cycleSort('filename')">
          文件名 <span class="sort-arrow">{{ sortField==='filename' ? (sortOrder==='desc' ? '↓' : '↑') : '↕' }}</span>
        </button>
      </div>
    </div>

    <!-- Batch action bar (shown when items are selected) -->
    <div v-if="selectedIds.size > 0" class="batch-bar">
      <span class="batch-count">已选 {{ selectedIds.size }} 条</span>
      <button class="batch-btn clip" @click="doBatchRetryClip" :disabled="batchClipCount === 0">
        重试剪辑 ({{ batchClipCount }})
      </button>
      <button class="batch-btn transcribe" @click="doBatchRetryTranscribe" :disabled="batchTranscribeCount === 0">
        重试转录 ({{ batchTranscribeCount }})
      </button>
      <button class="batch-btn cancel" @click="selectedIds.clear()">取消选择</button>
    </div>

    <!-- Custom reclip form -->
    <div class="reclip-bar">
      <select v-model="reclipRoom" class="room-filter">
        <option value="">选择房间</option>
        <option v-for="r in rooms" :key="r.id" :value="r.name">{{ r.name }}</option>
      </select>
      <input type="date" v-model="reclipDate" class="room-filter" />
      <input type="number" v-model.number="reclipDuration" min="10" max="1800" placeholder="时长" class="room-filter duration-input" />
      <span class="duration-unit">秒</span>
      <input type="number" v-model.number="reclipCount" min="1" max="5" placeholder="数量" class="room-filter count-input" />
      <span class="duration-unit">个</span>
      <button class="btn-cleanup btn-reclip" @click="doReclip" :disabled="!reclipRoom || !reclipDate || !reclipDuration">
        重新剪辑
      </button>
    </div>

    <table class="recordings-table">
      <thead>
        <tr>
          <th class="check-col">
            <input type="checkbox" :checked="allSelected" :indeterminate="someSelected" @change="toggleSelectAll" class="row-check" />
          </th>
          <th></th>
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
        <tr v-for="rec in filtered" :key="rec.id" :class="{ selected: selectedIds.has(rec.id) }">
          <td class="check-col">
            <input type="checkbox" :checked="selectedIds.has(rec.id)" @change="toggleSelect(rec.id)" class="row-check" />
          </td>
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
            <span v-else-if="rec.transcribed === -1" class="transcribe-fail-cell">
              <button class="badge red btn-retry" @click="doRetryTranscribe(rec)">重试</button>
              <span v-if="rec.transcribe_error" class="error-tip" :title="rec.transcribe_error">{{ shortError(rec.transcribe_error) }}</span>
            </span>
            <span v-else class="badge dim">待转录</span>
          </td>
          <td>
            <div v-if="rec.clipped === 2" class="clip-actions">
              <template v-if="clipVariants[rec.id]?.length > 1">
                <a v-for="v in clipVariants[rec.id]" :key="v.id"
                   :href="`${apiBase}/api/recording-clips/${v.id}/download`"
                   class="badge purple" style="display:block">
                  下载 V{{ v.variant_idx + 1 }}
                </a>
              </template>
              <a v-else :href="`${apiBase}/api/recordings/${rec.id}/clip`" class="badge purple">下载剪辑</a>
              <button class="badge dim btn-retry" @click="doRevealClip(rec)" title="在 Finder 中显示">打开位置</button>
            </div>
            <div v-else-if="rec.clipped === 1" class="clip-progress-cell">
              <div class="clip-progress-bar-wrap">
                <div class="clip-progress-bar" :style="{ width: (clipJobs[rec.id]?.pct ?? 0) + '%' }"></div>
              </div>
              <span class="clip-progress-label">
                {{ clipJobs[rec.id]?.msg || '剪辑中' }}
                {{ clipJobs[rec.id]?.pct != null ? clipJobs[rec.id].pct + '%' : '' }}
              </span>
              <span v-if="clipJobs[rec.id]?.eta_seconds != null" class="clip-eta">
                约剩 {{ fmtEta(clipJobs[rec.id].eta_seconds) }}
              </span>
            </div>
            <span v-else-if="rec.clipped === -1 && rec.skip_reason" class="badge dim skip-reason" :title="rec.skip_reason">⚠ 已跳过</span>
            <button v-else-if="rec.clipped === -1" class="badge red btn-retry" @click="doRetryClip(rec)">重试</button>
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
import { ref, computed, reactive, onMounted, onUnmounted } from 'vue'
import { getAllRecordings, getRooms, retryTranscribe, retryClip, revealClip,
         reclip, formatBytes, formatDuration, createWS, getThumbnailUrl, getStats, clipMissing, getClipJobs,
         getRecordingClipsBulk } from '../api.js'
import { useToast } from '../composables/toast.js'

const { show } = useToast()
const selectedIds = reactive(new Set())

const recordings = ref([])
const rooms = ref([])
const filterRoom = ref('')
const filterStatus = ref('')
const reclipRoom = ref('')
const reclipDate = ref('')
const reclipDuration = ref(60)
const reclipCount = ref(1)
const page = ref(1)
const total = ref(0)
const totalPages = ref(1)
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''
const stats = ref({ transcribe_pending: 0, transcribe_running: 0, transcribe_failed: 0,
                    clip_pending: 0, clip_running: 0, clip_failed: 0 })
const clipJobs = ref({})        // { recording_id: { pct, msg } }
const clipVariants = ref({})    // { recording_id: [clips] }
const sortField = ref('start_time')
const sortOrder = ref('desc')
let ws = null

const shortError = (msg) => msg && msg.length > 40 ? msg.slice(0, 40) + '…' : msg

// ── Multi-select ──────────────────────────────────────────────────────────────
const allSelected = computed(() => filtered.value.length > 0 && filtered.value.every(r => selectedIds.has(r.id)))
const someSelected = computed(() => filtered.value.some(r => selectedIds.has(r.id)) && !allSelected.value)

const batchClipCount = computed(() =>
  [...selectedIds].filter(id => {
    const r = filtered.value.find(r => r.id === id)
    return r && r.clipped === -1
  }).length
)
const batchTranscribeCount = computed(() =>
  [...selectedIds].filter(id => {
    const r = filtered.value.find(r => r.id === id)
    return r && r.transcribed === -1
  }).length
)

function toggleSelect(id) {
  if (selectedIds.has(id)) selectedIds.delete(id)
  else selectedIds.add(id)
}

function toggleSelectAll() {
  if (allSelected.value) {
    filtered.value.forEach(r => selectedIds.delete(r.id))
  } else {
    filtered.value.forEach(r => selectedIds.add(r.id))
  }
}

async function doBatchRetryClip() {
  const ids = [...selectedIds].filter(id => {
    const r = filtered.value.find(r => r.id === id)
    return r && r.clipped === -1
  })
  if (!ids.length) return
  let ok = 0
  for (const id of ids) {
    try { await retryClip(id); ok++ } catch {}
  }
  show(`已重新提交 ${ok} 个剪辑任务`, 'success')
  selectedIds.clear()
  await load()
}

async function doBatchRetryTranscribe() {
  const ids = [...selectedIds].filter(id => {
    const r = filtered.value.find(r => r.id === id)
    return r && r.transcribed === -1
  })
  if (!ids.length) return
  let ok = 0
  for (const id of ids) {
    try { await retryTranscribe(id); ok++ } catch {}
  }
  show(`已重新提交 ${ok} 个转录任务`, 'success')
  selectedIds.clear()
  await load()
}

function fmtEta(sec) {
  if (sec == null || sec < 0) return ''
  if (sec < 60) return `${sec}秒`
  const m = Math.floor(sec / 60), s = sec % 60
  return s > 0 ? `${m}分${s}秒` : `${m}分钟`
}

const isBusy = computed(() =>
  stats.value.transcribe_running > 0 || stats.value.clip_running > 0
)

async function loadStats() {
  try { stats.value = await getStats() } catch {}
}

async function loadClipJobs() {
  try { clipJobs.value = await getClipJobs() } catch {}
}

function toggleFilter(val) {
  filterStatus.value = filterStatus.value === val ? '' : val
  page.value = 1
  selectedIds.clear()
  load()
}

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


async function load() {
  const [data, r] = await Promise.all([
    getAllRecordings(page.value, filterStatus.value, sortField.value, sortOrder.value),
    getRooms(),
  ])
  recordings.value = data.items
  total.value = data.total
  totalPages.value = data.pages
  rooms.value = r
  await Promise.all([loadStats(), loadClipJobs()])
  // Fetch clip variants for all completed recordings on this page
  const doneIds = data.items.filter(r => r.clipped === 2).map(r => r.id)
  if (doneIds.length) {
    try {
      const variants = await getRecordingClipsBulk(doneIds)
      clipVariants.value = { ...clipVariants.value, ...variants }
    } catch {}
  }
}

function cycleSort(field) {
  if (sortField.value === field) {
    sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortField.value = field
    sortOrder.value = 'desc'
  }
  page.value = 1
  load()
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

async function doReclip() {
  try {
    const { queued } = await reclip(reclipRoom.value, reclipDate.value, reclipDuration.value, reclipCount.value)
    show(`已提交 ${queued.length} 个剪辑任务`, 'success')
    await load()
  } catch (e) {
    show(e.message || '提交失败', 'error')
  }
}

async function doClipMissing() {
  try {
    const { queued, skipped } = await clipMissing()
    show(`已发起 ${queued.length} 个剪辑任务${skipped.length ? `，${skipped.length} 个文件缺失跳过` : ''}`, 'success')
    await load()
  } catch (e) {
    show(e.message || '操作失败', 'error')
  }
}

onMounted(async () => {
  // Auto-activate "进行中" filter if there are active jobs
  try {
    const jobs = await getClipJobs()
    if (Object.keys(jobs).length > 0) filterStatus.value = 'active'
  } catch {}
  load()
  ws = createWS((msg) => {
    if (msg.type === 'transcribed') {
      show('转录完成', 'success')
      load()
      loadStats()
    } else if (msg.type === 'clipped') {
      show('剪辑完成', 'success')
      load()
      loadStats()
    } else if (msg.type === 'gpu_online' || msg.type === 'gpu_offline') {
      loadStats()
    } else if (msg.type === 'clip_progress') {
      clipJobs.value = {
        ...clipJobs.value,
        [msg.recording_id]: { pct: msg.pct, msg: msg.msg, eta_seconds: msg.eta_seconds ?? null },
      }
    }
  })
})

onUnmounted(() => ws?.close())
</script>

<style scoped>
.transcribe-fail-cell { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.error-tip { font-size: 11px; color: #e07060; background: rgba(200,60,30,0.12); border: 1px solid rgba(200,60,30,0.25); border-radius: 4px; padding: 2px 6px; cursor: help; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }
.toolbar-right { display: flex; gap: 10px; align-items: center; }
.room-filter { background: #1a1a1a; border: 1px solid #333; color: #ccc; padding: 7px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-cleanup { background: #2a2a2a; border: 1px solid #444; color: #888; padding: 7px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-cleanup:hover { background: #333; color: #ccc; }
.reclip-bar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
.duration-input { width: 80px; }
.count-input { width: 60px; }
.duration-unit { color: #888; font-size: 13px; margin-left: -6px; }
.btn-reclip { background: rgba(254,44,85,0.15); color: #fe2c55; border-color: rgba(254,44,85,0.3); }
.btn-reclip:hover:not(:disabled) { background: rgba(254,44,85,0.25); color: #fe2c55; }
.btn-reclip:disabled { opacity: 0.4; cursor: not-allowed; }
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
.skip-reason  { color: #f59e0b; background: rgba(245,158,11,0.1); cursor: help; }
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
.stats-panel { display:flex; align-items:center; gap:16px; padding:10px 14px; background:#111; border:1px solid #222; border-radius:8px; margin-bottom:14px; flex-wrap:wrap; }
.stats-group { display:flex; align-items:center; gap:8px; }
.stats-label { font-size:12px; color:#555; }
.stats-item { font-size:12px; padding:2px 8px; border-radius:10px; border:none; cursor:pointer; font-family:inherit; }
.stats-item.yellow { background:rgba(251,191,36,.15); color:#fbbf24; }
.stats-item.red    { background:rgba(254,44,85,.15);  color:#fe2c55; }
.stats-item.dim    { background:#1e1e1e; color:#555; cursor:default; }
.stats-item.yellow:hover { background:rgba(251,191,36,.28); }
.stats-item.red:hover    { background:rgba(254,44,85,.28); }
.stats-item.active.yellow { background:rgba(251,191,36,.35); outline:1px solid rgba(251,191,36,.6); }
.stats-item.active.red    { background:rgba(254,44,85,.3);   outline:1px solid rgba(254,44,85,.6); }
.stats-item.active.dim    { background:#2a2a2a; outline:1px solid #444; color:#888; }
.stats-divider { width:1px; height:20px; background:#222; }
.stats-busy { display:flex; align-items:center; gap:6px; background:none; border:none; padding:0; border-radius:6px; }
.stats-busy.active-busy { outline:1px solid rgba(251,191,36,.5); border-radius:6px; padding:2px 6px; }
.busy-dot { width:8px; height:8px; border-radius:50%; }
.busy-dot.busy { background:#fbbf24; box-shadow:0 0 6px rgba(251,191,36,.6); animation:pulse 1.2s infinite; }
.busy-dot.idle { background:#333; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.btn-clip-missing { background: rgba(99,102,241,.15); color: #818cf8; border-color: rgba(99,102,241,.3); padding: 4px 12px; border-radius: 6px; font-size: 12px; cursor: pointer; border: 1px solid; }
.btn-clip-missing:hover { background: rgba(99,102,241,.25); }
.filter-sort-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; gap:12px; flex-wrap:wrap; }
.filter-btns { display:flex; gap:6px; }
.filter-btn { background:#1e1e1e; border:1px solid #333; color:#666; padding:4px 14px; border-radius:16px; font-size:12px; cursor:pointer; font-family:inherit; transition:all .15s; }
.filter-btn:hover { border-color:#555; color:#aaa; }
.filter-btn.active { color:#fff; border-color:#555; background:#2a2a2a; }
.filter-btn.green.active  { background:rgba(34,197,94,.2);  border-color:rgba(34,197,94,.5);  color:#22c55e; }
.filter-btn.yellow.active { background:rgba(251,191,36,.2); border-color:rgba(251,191,36,.5); color:#fbbf24; }
.filter-btn.red.active    { background:rgba(254,44,85,.2);  border-color:rgba(254,44,85,.5);  color:#fe2c55; }
.sort-btns { display:flex; gap:6px; }
.sort-btn { background:#1e1e1e; border:1px solid #333; color:#666; padding:4px 12px; border-radius:6px; font-size:12px; cursor:pointer; font-family:inherit; display:flex; align-items:center; gap:4px; }
.sort-btn:hover { border-color:#555; color:#aaa; }
.sort-arrow { font-size:11px; opacity:.7; }
.clip-progress-cell { display: flex; flex-direction: column; gap: 4px; min-width: 120px; }
.clip-progress-bar-wrap { height: 4px; background: #222; border-radius: 2px; overflow: hidden; }
.clip-progress-bar { height: 100%; background: #fbbf24; border-radius: 2px; transition: width 0.4s ease; }
.clip-progress-label { font-size: 11px; color: #fbbf24; white-space: nowrap; }
.clip-eta { font-size: 11px; color: #888; white-space: nowrap; }
.check-col { width: 36px; padding-left: 14px; }
.row-check { width: 15px; height: 15px; accent-color: #fe2c55; cursor: pointer; }
tr.selected td { background: rgba(254,44,85,0.05); }
.batch-bar { display: flex; align-items: center; gap: 10px; padding: 8px 14px; background: rgba(254,44,85,0.08); border: 1px solid rgba(254,44,85,0.2); border-radius: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.batch-count { font-size: 13px; color: #fe2c55; font-weight: 500; margin-right: 4px; }
.batch-btn { padding: 4px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; border: 1px solid; font-family: inherit; transition: all 0.15s; }
.batch-btn.clip      { background: rgba(168,85,247,0.15); color: #c084fc; border-color: rgba(168,85,247,0.3); }
.batch-btn.clip:hover:not(:disabled) { background: rgba(168,85,247,0.28); }
.batch-btn.transcribe { background: rgba(59,130,246,0.15); color: #60a5fa; border-color: rgba(59,130,246,0.3); }
.batch-btn.transcribe:hover:not(:disabled) { background: rgba(59,130,246,0.28); }
.batch-btn.cancel    { background: #2a2a2a; color: #888; border-color: #333; }
.batch-btn.cancel:hover { background: #333; color: #ccc; }
.batch-btn:disabled { opacity: 0.35; cursor: not-allowed; }
</style>
