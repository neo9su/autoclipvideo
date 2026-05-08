<template>
  <!-- Maintenance mode warning bar -->
  <div v-if="status.maintenance" class="maintenance-bar">
    <span class="maint-icon">🔧</span>
    <span class="maint-text">GPU服务器维护中 — 所有GPU流水线已暂停，新分组仅生成经典版</span>
    <button class="maint-resume-btn" :disabled="maintBusy" @click="toggleMaintenance">
      {{ maintBusy ? '处理中…' : '✅ 恢复服务' }}
    </button>
  </div>
  <div class="gpu-banner" :class="{ offline: !status.reachable && !status.comfyui?.reachable, maintenance: status.maintenance }">
    <!-- Left: status indicators -->
    <div class="banner-left">
      <span class="dot" :class="status.reachable ? 'online' : 'offline'"></span>
      <span class="label">GPU服务</span>
      <span class="sep">|</span>
      <span class="dot" :class="status.comfyui?.reachable ? 'online' : 'offline'"></span>
      <span class="label">ComfyUI</span>
    </div>

    <!-- Center: metrics -->
    <div class="banner-metrics" v-if="status.comfyui?.reachable">
      <!-- GPU utilization bars (nvidia-smi dmon) -->
      <div class="metric" v-if="gpu3dPct !== null">
        <span class="metric-label">3D</span>
        <div class="bar-wrap">
          <div class="bar" :class="gpu3dPct > 85 ? 'danger' : gpu3dPct > 60 ? 'warn' : 'ok'"
               :style="{ width: gpu3dPct + '%' }"></div>
        </div>
        <span class="metric-val">{{ gpu3dPct }}%</span>
      </div>
      <div class="metric" v-if="gpuEncPct !== null">
        <span class="metric-label">Enc</span>
        <div class="bar-wrap">
          <div class="bar" :class="gpuEncPct > 85 ? 'danger' : gpuEncPct > 40 ? 'warn' : 'ok'"
               :style="{ width: Math.max(gpuEncPct, gpuEncPct > 0 ? 4 : 0) + '%' }"></div>
        </div>
        <span class="metric-val">{{ gpuEncPct }}%</span>
      </div>
      <div class="metric" v-if="vramTotal > 0">
        <span class="metric-label">专用显存</span>
        <div class="bar-wrap">
          <div class="bar" :class="vramPct > 85 ? 'danger' : vramPct > 60 ? 'warn' : 'ok'"
               :style="{ width: vramPct + '%' }"></div>
        </div>
        <span class="metric-val">{{ vramUsedGB }}GB / {{ vramTotalGB }}GB</span>
      </div>
      <div class="metric">
        <span class="metric-label">内存</span>
        <div class="bar-wrap">
          <div class="bar" :class="ramPct > 85 ? 'danger' : ramPct > 60 ? 'warn' : 'ok'"
               :style="{ width: ramPct + '%' }"></div>
        </div>
        <span class="metric-val">{{ ramUsedGB }}GB / {{ ramTotalGB }}GB</span>
      </div>
      <div class="metric jobs">
        <span class="metric-label">转录队列</span>
        <span class="metric-val badge" :class="status.pending_transcribe > 0 ? 'active' : ''">
          {{ status.pending_transcribe ?? 0 }}
        </span>
      </div>
      <div class="metric poll-info" v-if="pollState">
        <span class="metric-label">上次轮询</span>
        <span class="metric-val" :class="lastPollAgo > 90 ? 'text-warn' : ''">{{ fmtAgo(lastPollAgo) }}</span>
        <span v-if="pollState.active_job_id" class="active-job">GPU处理中</span>
        <span v-if="pollState.blocked_count > 0" class="blocked-hint">{{ pollState.blocked_count }}个等待合并</span>
      </div>
      <div v-if="isQueueStuck" class="metric stuck-warn">
        <span class="stuck-icon">⚠</span>
        <span class="stuck-text">队列可能卡住</span>
        <button class="flush-btn" :disabled="flushing" @click="doFlush">{{ flushing ? '处理中…' : '强制处理' }}</button>
      </div>
      <div class="metric jobs">
        <span class="metric-label">生图队列</span>
        <span class="metric-val badge" :class="(status.comfyui.queue_running + status.comfyui.queue_pending) > 0 ? 'active' : ''">
          {{ status.comfyui.queue_running + status.comfyui.queue_pending }}
        </span>
      </div>
    </div>
    <div class="banner-metrics" v-else>
      <span v-if="!status.gpu_online" class="offline-text">
        GPU转录服务离线{{ offlineLabel }}
        <span v-if="status.pending_transcribe > 0" class="pending-badge">{{ status.pending_transcribe }} 个作业等待中</span>
      </span>
      <template v-else>
        <div class="metric jobs">
          <span class="metric-label">转录队列</span>
          <span class="metric-val badge" :class="status.pending_transcribe > 0 ? 'active' : ''">{{ status.pending_transcribe ?? 0 }}</span>
        </div>
        <span class="comfyui-offline-hint">ComfyUI 未运行</span>
      </template>
      <!-- Watchdog service controls -->
      <div v-if="watchdogServices.length" class="watchdog-panel">
        <template v-for="svc in watchdogServices" :key="svc.key">
          <span class="svc-dot" :class="svc.healthy ? 'online' : svc.running ? 'warn' : 'offline'"></span>
          <span class="svc-name">{{ svc.name }}</span>
          <button v-if="!svc.running" class="wd-btn start" @click="wdStart(svc.key)" :disabled="wdBusy[svc.key]">启动</button>
          <button v-else class="wd-btn stop"  @click="wdStop(svc.key)"  :disabled="wdBusy[svc.key]">停止</button>
          <button class="wd-btn restart" @click="wdRestart(svc.key)" :disabled="wdBusy[svc.key]">重启</button>
          <span v-if="svc.running && svc.uptime_s" class="svc-uptime">{{ fmtUptime(svc.uptime_s) }}</span>
          <span class="svc-sep">·</span>
        </template>
      </div>
      <div v-else-if="!status.gpu_online" class="watchdog-unavail">
        看门狗离线 · <span class="watchdog-hint">请在 GPU 服务器上运行 watchdog_agent.py</span>
      </div>
    </div>

    <!-- Right: logs + maintenance -->
    <div class="banner-right">
      <span class="version-tag">{{ appVersion }}</span>
      <button
        class="maint-btn"
        :class="{ active: status.maintenance }"
        :disabled="maintBusy"
        @click="toggleMaintenance"
        :title="status.maintenance ? '点击恢复GPU服务' : '暂停GPU服务（停机维护用）'"
      >
        {{ status.maintenance ? '✅ 恢复GPU' : '❇️ 维护GPU' }}
      </button>
      <button v-if="!logsVisible" class="log-btn" @click="loadLogs">查看日志</button>
      <button v-else class="log-btn active" @click="logsVisible = false; stopLogPoll()">隐藏日志</button>
      <div v-if="logsVisible && logs.length" class="marquee-wrap">
        <div class="marquee" :style="{ animationDuration: marqueeSpeed + 's' }">
          <span v-for="(log, i) in logs.slice(0, 2)" :key="log.id" class="log-entry" :class="log.level">
            <span class="log-time">{{ log.time }}</span>
            <span class="log-room">{{ log.room }}</span>
            <span class="log-status">{{ log.status }}</span>
            <span v-if="i < logs.slice(0,2).length - 1" class="log-sep">　·　</span>
          </span>
          <!-- duplicate for seamless loop -->
          <span v-for="(log, i) in logs.slice(0, 2)" :key="'d' + log.id" class="log-entry" :class="log.level">
            <span class="log-time">{{ log.time }}</span>
            <span class="log-room">{{ log.room }}</span>
            <span class="log-status">{{ log.status }}</span>
            <span v-if="i < logs.slice(0,2).length - 1" class="log-sep">　·　</span>
          </span>
        </div>
      </div>
      <span v-if="logsVisible && !logs.length" class="no-logs">暂无日志</span>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'

const status = ref({ reachable: false, health: {}, comfyui: { reachable: false }, pending_transcribe: 0 })
const logs = ref([])
const logsVisible = ref(false)
const appVersion = ref('')
let pollTimer = null
let logTimer = null

const vramTotal = computed(() => status.value.comfyui?.vram_total || 0)
const vramFree  = computed(() => status.value.comfyui?.vram_free  || 0)
const vramPct   = computed(() => vramTotal.value ? Math.round((1 - vramFree.value / vramTotal.value) * 100) : 0)
const vramUsedGB  = computed(() => ((vramTotal.value - vramFree.value) / 1e9).toFixed(1))
const vramTotalGB = computed(() => (vramTotal.value / 1e9).toFixed(0))

// GPU utilization from nvidia-smi dmon (via gpu_service /health)
const gpu3dPct  = computed(() => status.value.health?.gpu_3d_pct  ?? null)
const gpuEncPct = computed(() => status.value.health?.gpu_enc_pct ?? null)
const gpuMemPct = computed(() => status.value.health?.gpu_mem_pct ?? null)

const ramTotal = computed(() => status.value.comfyui?.ram_total || 0)
const ramFree  = computed(() => status.value.comfyui?.ram_free  || 0)
const ramPct   = computed(() => ramTotal.value ? Math.round((1 - ramFree.value / ramTotal.value) * 100) : 0)
const ramUsedGB  = computed(() => ((ramTotal.value - ramFree.value) / 1e9).toFixed(1))
const ramTotalGB = computed(() => (ramTotal.value / 1e9).toFixed(0))

const watchdogServices = computed(() => {
  const svcs = status.value.watchdog?.services || {}
  return Object.entries(svcs).map(([key, s]) => ({ key, ...s }))
})

const wdBusy = ref({})
const maintBusy = ref(false)
const flushing = ref(false)
const now = ref(Date.now())
let nowTimer = null

const pollState = computed(() => status.value.poll_state || null)
const lastPollAgo = computed(() => {
  if (!pollState.value?.last_poll_at) return 9999
  return Math.round((now.value - new Date(pollState.value.last_poll_at).getTime()) / 1000)
})
const isQueueStuck = computed(() => {
  const q = status.value.pending_transcribe || 0
  if (q === 0) return false
  const ps = pollState.value
  if (!ps) return false
  const staleNoActivity = lastPollAgo.value > 120
  const allBlocked = ps.blocked_count > 0 && ps.blocked_count >= q && !ps.active_job_id
  return staleNoActivity || allBlocked
})

function fmtAgo(s) {
  if (s >= 9999) return '未知'
  if (s < 60) return `${s}秒前`
  if (s < 3600) return `${Math.floor(s/60)}分前`
  return `${Math.floor(s/3600)}小时前`
}

async function doFlush() {
  flushing.value = true
  try { await fetch('/api/transcribe/flush', { method: 'POST' }) } catch {}
  setTimeout(() => { flushing.value = false; fetchStatus() }, 2000)
}

async function toggleMaintenance() {
  maintBusy.value = true
  try {
    const enabling = !status.value.maintenance
    const method = enabling ? 'POST' : 'DELETE'
    await fetch('/api/gpu/maintenance', { method })
    await fetchStatus()
  } catch (e) {
    console.error('maintenance toggle failed', e)
  } finally {
    maintBusy.value = false
  }
}

async function wdStart(svc) {
  wdBusy.value[svc] = true
  try { await fetch(`/api/watchdog/start/${svc}`, { method: 'POST' }) } catch {}
  setTimeout(() => { wdBusy.value[svc] = false; fetchStatus() }, 3000)
}
async function wdStop(svc) {
  wdBusy.value[svc] = true
  try { await fetch(`/api/watchdog/stop/${svc}`, { method: 'POST' }) } catch {}
  setTimeout(() => { wdBusy.value[svc] = false; fetchStatus() }, 3000)
}
async function wdRestart(svc) {
  wdBusy.value[svc] = true
  try { await fetch(`/api/watchdog/restart/${svc}`, { method: 'POST' }) } catch {}
  setTimeout(() => { wdBusy.value[svc] = false; fetchStatus() }, 5000)
}

function fmtUptime(s) {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s/60)}m`
  return `${Math.floor(s/3600)}h${Math.floor((s%3600)/60)}m`
}

const offlineLabel = computed(() => {
  const s = status.value.gpu_offline_seconds
  if (!s) return ''
  if (s < 60) return ` (${s}秒)`
  if (s < 3600) return ` (${Math.floor(s/60)}分钟)`
  return ` (${Math.floor(s/3600)}小时${Math.floor((s%3600)/60)}分)`
})

const marqueeSpeed = computed(() => Math.max(8, logs.value.slice(0, 2).reduce((a, l) => a + l.status.length, 0) * 0.15))

async function fetchStatus() {
  try {
    const r = await fetch('/api/gpu/status')
    if (r.ok) status.value = await r.json()
  } catch {}
}

async function loadLogs() {
  logsVisible.value = true
  await fetchLogs()
  logTimer = setInterval(fetchLogs, 10000)
}

async function fetchLogs() {
  try {
    const r = await fetch('/api/gpu/logs')
    if (r.ok) logs.value = await r.json()
  } catch {}
}

function stopLogPoll() {
  clearInterval(logTimer)
  logTimer = null
}

onMounted(async () => {
  fetchStatus()
  pollTimer = setInterval(fetchStatus, 8000)
  nowTimer = setInterval(() => { now.value = Date.now() }, 5000)
  try {
    const r = await fetch('/api/version')
    if (r.ok) { const d = await r.json(); appVersion.value = d.version || '' }
  } catch {}
})

onUnmounted(() => {
  clearInterval(pollTimer)
  clearInterval(nowTimer)
  stopLogPoll()
})
</script>

<style scoped>
.gpu-banner {
  background: #141414;
  border-bottom: 1px solid #2a2a2a;
  padding: 0 24px;
  height: 36px;
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 12px;
  color: #888;
  overflow: hidden;
}
.gpu-banner.offline { border-bottom-color: rgba(254,44,85,0.3); }

.banner-left { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot.online  { background: #34d399; box-shadow: 0 0 5px #34d399; animation: pulse 2s infinite; }
.dot.offline { background: #fe2c55; }
.label { color: #aaa; }
.sep { color: #333; }

.banner-metrics { display: flex; align-items: center; gap: 16px; flex: 1; }
.metric { display: flex; align-items: center; gap: 6px; }
.metric-label { color: #666; white-space: nowrap; }
.metric-val { color: #ccc; white-space: nowrap; }
.bar-wrap { width: 60px; height: 5px; background: #2a2a2a; border-radius: 3px; overflow: hidden; }
.bar { height: 100%; border-radius: 3px; transition: width 0.5s; }
.bar.ok     { background: #34d399; }
.bar.warn   { background: #fbbf24; }
.bar.danger { background: #fe2c55; }
.badge { background: #2a2a2a; border-radius: 10px; padding: 1px 8px; font-weight: 600; }
.badge.active { background: rgba(254,44,85,0.2); color: #fe2c55; }
.offline-text { color: #fe2c55; display: flex; align-items: center; gap: 8px; }
.watchdog-panel { display: flex; align-items: center; gap: 5px; margin-left: 12px; }
.watchdog-unavail { color: #555; margin-left: 12px; font-size: 11px; }
.comfyui-offline-hint { font-size: 11px; color: #555; margin-left: 4px; }
.watchdog-hint { color: #444; }
.svc-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.svc-dot.online  { background: #34d399; }
.svc-dot.warn    { background: #fbbf24; }
.svc-dot.offline { background: #555; }
.svc-name { color: #999; font-size: 11px; }
.svc-uptime { color: #555; font-size: 10px; }
.svc-sep { color: #333; margin: 0 2px; }
.wd-btn { font-size: 10px; padding: 1px 7px; border-radius: 3px; cursor: pointer; border: 1px solid #333; background: #222; color: #aaa; transition: all 0.15s; }
.wd-btn:hover:not(:disabled) { background: #333; color: #fff; }
.wd-btn:disabled { opacity: 0.4; cursor: default; }
.wd-btn.start   { border-color: rgba(52,211,153,0.4);  color: #34d399; }
.wd-btn.stop    { border-color: rgba(254,44,85,0.4);   color: #fe2c55; }
.wd-btn.restart { border-color: rgba(251,191,36,0.4);  color: #fbbf24; }
.pending-badge { background: rgba(251,191,36,0.15); color: #fbbf24; border-radius: 10px; padding: 1px 8px; font-size: 11px; }
.poll-info { gap: 5px; }
.text-warn { color: #fbbf24 !important; }
.active-job { background: rgba(96,165,250,0.15); color: #60a5fa; border-radius: 8px; padding: 1px 6px; font-size: 10px; }
.blocked-hint { color: #555; font-size: 10px; }
.stuck-warn { gap: 5px; background: rgba(254,44,85,0.08); border: 1px solid rgba(254,44,85,0.25); border-radius: 6px; padding: 2px 8px; }
.stuck-icon { color: #fbbf24; font-size: 11px; }
.stuck-text { color: #fe2c55; font-size: 11px; }
.flush-btn { font-size: 10px; padding: 1px 8px; border-radius: 3px; cursor: pointer; border: 1px solid rgba(254,44,85,0.5); background: rgba(254,44,85,0.15); color: #fe2c55; transition: all 0.15s; }
.flush-btn:hover:not(:disabled) { background: rgba(254,44,85,0.3); }
.flush-btn:disabled { opacity: 0.5; cursor: default; }

.banner-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; max-width: 400px; overflow: hidden; }
.version-tag { font-size: 10px; color: #3a3a3a; white-space: nowrap; user-select: none; }
.log-btn { background: #2a2a2a; border: 1px solid #333; color: #888; cursor: pointer; padding: 2px 10px; border-radius: 4px; font-size: 11px; transition: all 0.2s; white-space: nowrap; }
.log-btn:hover, .log-btn.active { background: #333; color: #fff; border-color: #555; }

.marquee-wrap { overflow: hidden; width: 320px; }
.marquee { display: flex; white-space: nowrap; animation: scroll-left linear infinite; }
.log-entry { display: inline-flex; align-items: center; gap: 5px; padding-right: 24px; }
.log-entry.success .log-status { color: #34d399; }
.log-entry.error   .log-status { color: #fe2c55; }
.log-entry.info    .log-status { color: #60a5fa; }
.log-entry.pending .log-status { color: #888; }
.log-time  { color: #555; }
.log-room  { color: #aaa; font-weight: 600; }
.log-status { max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.log-sep { color: #444; }
.no-logs { color: #555; font-size: 11px; }

@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.5; } }
@keyframes scroll-left { from { transform: translateX(0); } to { transform: translateX(-50%); } }

/* Maintenance mode */
.maintenance-bar {
  background: rgba(251,191,36,0.12);
  border-bottom: 1px solid rgba(251,191,36,0.4);
  padding: 5px 24px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #fbbf24;
}
.maint-icon { font-size: 14px; }
.maint-text { flex: 1; }
.maint-resume-btn {
  background: rgba(52,211,153,0.15);
  border: 1px solid rgba(52,211,153,0.5);
  color: #34d399;
  padding: 3px 14px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}
.maint-resume-btn:hover:not(:disabled) { background: rgba(52,211,153,0.3); }
.maint-resume-btn:disabled { opacity: 0.5; cursor: default; }

.gpu-banner.maintenance { border-bottom-color: rgba(251,191,36,0.25); }

.maint-btn {
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid rgba(251,191,36,0.35);
  background: rgba(251,191,36,0.08);
  color: #fbbf24;
  transition: all 0.2s;
  white-space: nowrap;
  flex-shrink: 0;
}
.maint-btn:hover:not(:disabled) { background: rgba(251,191,36,0.2); border-color: rgba(251,191,36,0.6); }
.maint-btn.active {
  border-color: rgba(52,211,153,0.5);
  background: rgba(52,211,153,0.1);
  color: #34d399;
}
.maint-btn.active:hover:not(:disabled) { background: rgba(52,211,153,0.25); }
.maint-btn:disabled { opacity: 0.5; cursor: default; }
</style>
