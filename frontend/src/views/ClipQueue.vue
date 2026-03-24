<template>
  <div>
    <div class="toolbar">
      <h2>剪辑作业队列</h2>
      <div class="toolbar-meta">
        <span class="meta-item">剪辑并发: {{ maxConcurrent }}</span>
        <span class="meta-sep">·</span>
        <span class="meta-item">剪辑运行: {{ queue.running.length }}</span>
        <span class="meta-sep">·</span>
        <span class="meta-item">剪辑等待: {{ queue.queued.length }}</span>
        <span class="meta-sep">·</span>
        <span class="meta-item">转录: {{ transcribeJobs.length }}</span>
        <button class="btn-refresh" @click="load" :disabled="loading">刷新</button>
      </div>
    </div>

    <!-- Transcription queue section -->
    <section v-if="transcribeJobs.length > 0" class="section">
      <div class="section-header">
        <span class="section-title">转录队列</span>
        <span class="section-badge" :class="transcribeJobs.some(j=>j.level==='running') ? 'running' : 'queued'">
          {{ transcribeJobs.length }}
        </span>
        <span class="section-hint">由 GPU 服务处理，优先级由提交顺序决定</span>
      </div>

      <!-- Overall progress bar -->
      <div v-if="transcribeMeta.total > 0" class="transcribe-overall">
        <div class="overall-stats">
          <span class="overall-done">已完成 {{ transcribeMeta.session_done }}</span>
          <span class="overall-sep">/</span>
          <span class="overall-total">共 {{ transcribeMeta.total }}</span>
          <span class="overall-pct">{{ overallPct }}%</span>
          <span v-if="transcribeMeta.eta_seconds" class="overall-eta">预计剩余 {{ formatEta(transcribeMeta.eta_seconds) }}</span>
        </div>
        <div class="overall-bar-wrap">
          <div class="overall-bar" :style="{ width: overallPct + '%' }"></div>
        </div>
      </div>

      <div class="job-list">
        <div v-for="job in transcribeJobs" :key="'t'+job.recording_id"
             class="job-card transcribe-card" :class="job.level">
          <!-- Left: icon -->
          <div class="queue-pos transcribe-icon" :class="job.level">
            <span v-if="job.level==='running'" class="t-spinner"></span>
            <span v-else>{{ job.queue_pos || '…' }}</span>
          </div>
          <!-- Center: info + progress -->
          <div class="job-info tc-info">
            <div class="tc-top">
              <span class="job-id">录像 #{{ job.recording_id }}</span>
              <span v-if="job.room_name" class="job-room">{{ job.room_name }}</span>
            </div>
            <div class="tc-mid">
              <span class="job-phase" :class="'lvl-'+job.level">{{ job.status }}</span>
              <span v-if="job.elapsed_s != null" class="tc-elapsed">已用 {{ formatEta(job.elapsed_s) }}</span>
            </div>
            <div v-if="job.level === 'running'" class="tc-bar-wrap">
              <div class="tc-bar" :style="{ width: (job.pct != null ? job.pct : 0) + '%' }"></div>
            </div>
          </div>
          <!-- Right: pct + time -->
          <div class="tc-right">
            <span v-if="job.pct != null" class="tc-pct">{{ job.pct }}%</span>
            <span v-else-if="job.queue_pos" class="tc-qpos">第 {{ job.queue_pos }} 位</span>
            <span class="transcribe-time">{{ job.start_time }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Empty state -->
    <div v-if="!loading && queue.running.length === 0 && queue.queued.length === 0 && transcribeJobs.length === 0" class="empty-state">
      <div class="empty-icon">✓</div>
      <div class="empty-text">暂无剪辑任务</div>
      <div class="empty-sub">所有剪辑作业已完成</div>
    </div>

    <!-- Running jobs -->
    <section v-if="queue.running.length > 0" class="section">
      <div class="section-header">
        <span class="section-title">运行中</span>
        <span class="section-badge running">{{ queue.running.length }}</span>
      </div>
      <div class="job-list">
        <div v-for="job in queue.running" :key="job.recording_id" class="job-card running">
          <div class="job-top">
            <div class="job-left">
              <span class="spinner"></span>
              <div class="job-info">
                <span class="job-id">录像 #{{ job.recording_id }}</span>
                <span class="job-phase">{{ job.msg || job.phase }}</span>
              </div>
            </div>
            <div class="job-right">
              <span v-if="job.eta_seconds != null" class="job-eta">剩余 {{ formatEta(job.eta_seconds) }}</span>
              <span class="job-pct">{{ job.pct }}%</span>
            </div>
          </div>
          <div class="progress-bar-wrap">
            <div class="progress-bar" :style="{ width: job.pct + '%' }"
                 :class="job.pct >= 99 ? 'done' : 'active'"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- Queued jobs -->
    <section v-if="queue.queued.length > 0" class="section">
      <div class="section-header">
        <span class="section-title">等待中</span>
        <span class="section-badge queued">{{ queue.queued.length }}</span>
        <span class="section-hint">优先级数字越小越先执行</span>
      </div>
      <div class="job-list">
        <div v-for="(job, idx) in queue.queued" :key="job.recording_id" class="job-card queued">
          <div class="queue-pos">{{ idx + 1 }}</div>
          <div class="job-info">
            <span class="job-id">录像 #{{ job.recording_id }}</span>
            <span v-if="job.room_name" class="job-room">{{ job.room_name }}</span>
            <span v-if="job.record_date" class="job-date">{{ job.record_date }}</span>
          </div>
          <div class="priority-ctrl">
            <label class="priority-label">优先级</label>
            <input
              type="number"
              min="1" max="99"
              :value="job.priority"
              class="priority-input"
              @change="setPriority(job.recording_id, $event.target.value)"
            />
            <button class="prio-btn up" @click="setPriority(job.recording_id, Math.max(1, job.priority - 10))" title="提高优先级">↑</button>
            <button class="prio-btn dn" @click="setPriority(job.recording_id, Math.min(99, job.priority + 10))" title="降低优先级">↓</button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useToast } from '../composables/toast.js'

const { showToast } = useToast()
const queue = ref({ running: [], queued: [] })
const transcribeJobs = ref([])
const transcribeMeta = ref({ total: 0, session_done: 0, avg_duration_s: 0, eta_seconds: null })
const loading = ref(false)
const maxConcurrent = ref(2)
let timer = null

const overallPct = computed(() => {
  const { total, session_done } = transcribeMeta.value
  if (!total) return 0
  return Math.min(100, Math.round(session_done / total * 100))
})

async function load() {
  loading.value = true
  try {
    const [clipRes, transcribeRes] = await Promise.all([
      fetch('/api/clip-queue'),
      fetch('/api/transcribe-queue'),
    ])
    if (clipRes.ok) queue.value = await clipRes.json()
    if (transcribeRes.ok) {
      const data = await transcribeRes.json()
      transcribeJobs.value = data.jobs || []
      transcribeMeta.value = {
        total: data.total || 0,
        session_done: data.session_done || 0,
        avg_duration_s: data.avg_duration_s || 0,
        eta_seconds: data.eta_seconds ?? null,
      }
    }
  } catch (e) {
    showToast('加载队列失败', 'error')
  } finally {
    loading.value = false
  }
}

async function setPriority(recordingId, rawValue) {
  const priority = Math.max(1, Math.min(99, parseInt(rawValue) || 50))
  try {
    const r = await fetch(`/api/clip-queue/${recordingId}/priority?priority=${priority}`, { method: 'POST' })
    if (r.ok) {
      showToast(`已更新优先级 → ${priority}`, 'success')
      await load()
    } else {
      const err = await r.json().catch(() => ({}))
      showToast(err.detail || '更新失败', 'error')
    }
  } catch (e) {
    showToast('请求失败', 'error')
  }
}

function formatEta(secs) {
  if (secs == null || secs < 0) return ''
  if (secs < 60) return `${secs}s`
  return `${Math.floor(secs / 60)}m${secs % 60}s`
}

onMounted(() => {
  load()
  timer = setInterval(load, 3000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.toolbar h2 { font-size: 18px; font-weight: 600; color: #fff; }
.toolbar-meta { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #666; }
.meta-sep { color: #333; }
.btn-refresh { background: #2a2a2a; border: 1px solid #333; color: #aaa; cursor: pointer; padding: 4px 12px; border-radius: 6px; font-size: 12px; }
.btn-refresh:hover { background: #333; color: #fff; }

.empty-state { text-align: center; padding: 80px 20px; color: #555; }
.empty-icon { font-size: 40px; color: #34d399; margin-bottom: 12px; }
.empty-text { font-size: 16px; color: #777; margin-bottom: 6px; }
.empty-sub { font-size: 13px; color: #444; }

.section { margin-bottom: 24px; }
.section-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.section-title { font-size: 14px; font-weight: 600; color: #ccc; }
.section-badge { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; }
.section-badge.running { background: rgba(251,191,36,0.2); color: #fbbf24; }
.section-badge.queued  { background: rgba(148,163,184,0.15); color: #94a3b8; }
.section-hint { font-size: 11px; color: #555; margin-left: auto; }

.job-list { display: flex; flex-direction: column; gap: 8px; }

.job-card {
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 8px;
  padding: 14px 16px;
}
.job-card.running { border-color: rgba(251,191,36,0.3); }
.job-card.queued  { display: flex; align-items: center; gap: 14px; }

.job-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.job-left { display: flex; align-items: center; gap: 10px; }
.job-right { display: flex; align-items: center; gap: 12px; }

.spinner {
  width: 14px; height: 14px; border-radius: 50%;
  border: 2px solid #333;
  border-top-color: #fbbf24;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

.job-info { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.job-id    { font-size: 13px; color: #ccc; font-weight: 500; }
.job-phase { font-size: 11px; color: #666; }
.job-room  { font-size: 11px; color: #888; }
.job-date  { font-size: 11px; color: #555; }
.job-eta   { font-size: 12px; color: #888; }
.job-pct   { font-size: 14px; font-weight: 600; color: #fbbf24; min-width: 36px; text-align: right; }

.progress-bar-wrap { height: 4px; background: #2a2a2a; border-radius: 2px; overflow: hidden; }
.progress-bar { height: 100%; border-radius: 2px; transition: width 0.4s; }
.progress-bar.active { background: #fbbf24; }
.progress-bar.done   { background: #34d399; }

.queue-pos {
  width: 28px; height: 28px; border-radius: 50%;
  background: #2a2a2a; border: 1px solid #333;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; color: #888; font-weight: 600; flex-shrink: 0;
}

.priority-ctrl { display: flex; align-items: center; gap: 6px; margin-left: auto; flex-shrink: 0; }
.priority-label { font-size: 11px; color: #555; }
.priority-input {
  width: 44px; background: #111; border: 1px solid #333; color: #ccc;
  padding: 3px 6px; border-radius: 4px; font-size: 13px; text-align: center;
}
.priority-input:focus { outline: none; border-color: #fe2c55; }
.prio-btn {
  background: #2a2a2a; border: 1px solid #333; color: #888;
  cursor: pointer; width: 24px; height: 24px; border-radius: 4px;
  font-size: 13px; display: flex; align-items: center; justify-content: center;
  transition: all 0.15s;
}
.prio-btn:hover { background: #333; color: #fff; }

/* ── Transcribe card ── */
.transcribe-card { display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px; }
.transcribe-card.running { border-color: rgba(96,165,250,0.3); }
.transcribe-card.queued  { border-color: #2a2a2a; }
.transcribe-card.pending { border-color: #222; opacity: 0.75; }

.transcribe-icon {
  width: 28px; height: 28px; border-radius: 50%;
  background: #1e2a3a; border: 1px solid #2a4060;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: #60a5fa; flex-shrink: 0; margin-top: 2px;
}
.transcribe-icon.running { background: rgba(96,165,250,0.15); border-color: rgba(96,165,250,0.4); }
.transcribe-icon.queued  { background: #1a1a1a; border-color: #333; color: #666; }
.transcribe-icon.pending { background: #111; border-color: #222; color: #444; }

.t-spinner {
  width: 10px; height: 10px; border-radius: 50%;
  border: 2px solid #1e3a5a;
  border-top-color: #60a5fa;
  animation: spin 0.9s linear infinite;
  display: block;
}

.tc-info { flex: 1; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.tc-top  { display: flex; align-items: center; gap: 8px; }
.tc-mid  { display: flex; align-items: center; gap: 8px; }
.tc-elapsed { font-size: 11px; color: #555; }
.tc-bar-wrap { height: 3px; background: #222; border-radius: 2px; overflow: hidden; margin-top: 2px; }
.tc-bar { height: 100%; background: #60a5fa; border-radius: 2px; transition: width 1s linear; }

.tc-right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex-shrink: 0; }
.tc-pct  { font-size: 14px; font-weight: 600; color: #60a5fa; }
.tc-qpos { font-size: 11px; color: #555; white-space: nowrap; }
.transcribe-time { font-size: 11px; color: #444; white-space: nowrap; }

.lvl-running { color: #60a5fa !important; }
.lvl-queued  { color: #888 !important; }
.lvl-pending { color: #555 !important; }

/* ── Overall progress ── */
.transcribe-overall { margin-bottom: 12px; padding: 10px 14px; background: #111; border-radius: 8px; border: 1px solid #222; }
.overall-stats { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 12px; }
.overall-done  { color: #34d399; font-weight: 600; }
.overall-sep   { color: #444; }
.overall-total { color: #666; }
.overall-pct   { color: #ccc; font-weight: 600; margin-left: 4px; }
.overall-eta   { margin-left: auto; color: #555; font-size: 11px; }
.overall-bar-wrap { height: 4px; background: #222; border-radius: 2px; overflow: hidden; }
.overall-bar { height: 100%; background: linear-gradient(90deg, #34d399, #60a5fa); border-radius: 2px; transition: width 0.8s; }
</style>
