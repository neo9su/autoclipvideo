<template>
  <div>
    <div class="toolbar">
      <h2>上传剪辑</h2>
    </div>

    <!-- Upload form -->
    <div class="upload-form">
      <div class="drop-row">
        <!-- Media drop zone (video or image) -->
        <div
          :class="['drop-zone', dragVideo && 'drag-over', videoFile && 'has-file']"
          @dragover.prevent="dragVideo = true"
          @dragleave="dragVideo = false"
          @drop.prevent="onDropVideo"
          @click="$refs.videoInput.click()"
        >
          <input ref="videoInput" type="file" accept="video/*,image/*" style="display:none" @change="onPickVideo" />
          <div v-if="videoFile" class="file-info">
            <span class="file-label">{{ isImage ? '图片' : '视频' }}</span>
            <span class="file-name">{{ videoFile.name }}</span>
            <span class="file-size">{{ formatBytes(videoFile.size) }}</span>
          </div>
          <div v-else class="drop-hint">
            <span class="drop-plus">+</span>
            <span class="drop-main">拖入或点击选择文件</span>
            <span class="drop-sub">视频（MP4/MOV/AVI）或图片（JPG/PNG）</span>
          </div>
        </div>

        <!-- SRT drop zone -->
        <div
          :class="['drop-zone', 'srt-zone', dragSrt && 'drag-over', srtFile && 'has-file', isImage && 'zone-disabled']"
          @dragover.prevent="!isImage && (dragSrt = true)"
          @dragleave="dragSrt = false"
          @drop.prevent="!isImage && onDropSrt($event)"
          @click="!isImage && $refs.srtInput.click()"
        >
          <input ref="srtInput" type="file" accept=".srt" style="display:none" @change="onPickSrt" />
          <div v-if="srtFile" class="file-info">
            <span class="file-label">字幕</span>
            <span class="file-name">{{ srtFile.name }}</span>
          </div>
          <div v-else class="drop-hint">
            <span class="srt-badge" :style="isImage ? 'color:#333' : ''">SRT</span>
            <span class="drop-main">字幕文件（可选）</span>
            <span class="drop-sub">{{ isImage ? '图片模式不需要字幕' : '有 SRT 立即剪辑，无则 GPU 转录后剪辑' }}</span>
          </div>
        </div>
      </div>

      <!-- Settings row -->
      <div class="settings-row">
        <select v-model="roomId" class="sel" :disabled="isImage">
          <option value="">选择房间</option>
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <div class="dur-wrap" :style="isImage ? 'opacity:.3;pointer-events:none' : ''">
          <input v-model.number="duration" type="number" min="10" max="1800" class="sel dur-input" />
          <span class="dur-unit">秒</span>
        </div>
        <div class="dur-wrap" :style="isImage ? 'opacity:.3;pointer-events:none' : ''">
          <input v-model.number="clipCount" type="number" min="1" max="5" class="sel count-input" />
          <span class="dur-unit">个视频</span>
        </div>
        <button
          class="btn-submit"
          :disabled="!videoFile || !roomId || uploading || isImage"
          :title="isImage ? '图片文件不支持上传剪辑' : ''"
          @click="submit"
        >{{ uploading ? '上传中…' : '上传并剪辑' }}</button>
        <button
          v-if="videoFile"
          class="btn-enhance"
          @click="openEnhanceModal"
        >✦ 画质增强</button>
        <button v-if="videoFile || srtFile" class="btn-clear" @click="clearFiles">清除</button>
      </div>

      <!-- Upload progress bar -->
      <div v-if="uploading" class="progress-wrap">
        <div class="progress-bar"><div class="progress-fill animate"></div></div>
        <span class="progress-label">上传中，请稍候…</span>
      </div>
    </div>

    <!-- Jobs list -->
    <div v-if="jobs.length" class="jobs-section">
      <h3 class="jobs-title">本次上传任务</h3>
      <table class="jobs-table">
        <thead>
          <tr>
            <th>文件名</th><th>房间</th><th>时长</th><th>字幕</th><th>剪辑状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td class="fname">{{ j.filename }}</td>
            <td>{{ j.roomName }}</td>
            <td>{{ j.duration }}s</td>
            <td><span :class="['badge', transcribeCls(j.transcribed)]">{{ transcribeLbl(j.transcribed) }}</span></td>
            <td><span :class="['badge', clipCls(j.clipped)]">{{ clipLbl(j.clipped) }}</span></td>
            <td>
              <div v-if="j.clipped === 2" class="action-col">
                <template v-if="j.clips && j.clips.length > 1">
                  <a v-for="c in j.clips" :key="c.id" :href="clipVariantDownloadUrl(c.id)" class="badge purple" download>V{{ c.variant_idx + 1 }}</a>
                </template>
                <a v-else :href="clipDownloadUrl(j.id)" class="badge purple" download>下载剪辑</a>
                <button class="badge dim btn-action" @click="doReveal(j.id)">打开文件夹</button>
              </div>
              <span v-else class="badge dim">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ══════════════ 画质增强弹窗 ══════════════ -->
    <div v-if="enhance.open" class="modal-overlay" @click.self="closeEnhanceModal">
      <div class="enhance-modal">

        <!-- Header -->
        <div class="em-header">
          <div class="em-title">
            ✦ 画质增强
            <span class="em-fname">{{ videoFile?.name }}</span>
          </div>
          <!-- Options -->
          <div class="em-options">
            <label class="em-opt-label">模型
              <select v-model="enhance.model" class="em-sel" :disabled="enhance.stage !== 'idle'">
                <option value="general">通用</option>
                <option value="portrait">人像</option>
                <option value="product">产品</option>
                <option value="anime">动漫</option>
              </select>
            </label>
            <label class="em-opt-label">目标清晰度
              <select v-model="enhance.targetRes" class="em-sel" :disabled="enhance.stage !== 'idle'">
                <option value="720p">高清 720P</option>
                <option value="1080p">超高清 1080P</option>
                <option value="4k">4K</option>
              </select>
            </label>
            <label class="em-opt-label">降噪
              <select v-model="enhance.denoise" class="em-sel" :disabled="enhance.stage !== 'idle'">
                <option value="low">低（保留细节）</option>
                <option value="medium">中（均衡）</option>
                <option value="high">高（强力去噪）</option>
              </select>
            </label>
          </div>
          <button class="em-close" @click="closeEnhanceModal">✕</button>
        </div>

        <!-- Preview area -->
        <div class="em-preview-area" ref="previewArea">

          <!-- idle / preview_processing: show original only -->
          <template v-if="enhance.stage === 'idle' || enhance.stage === 'preview_processing'">
            <div class="em-single-preview">
              <video v-if="!isImage" :src="enhance.originalSrc" autoplay loop muted playsinline class="em-media" />
              <img  v-else          :src="enhance.originalSrc" class="em-media em-img" />
              <div class="em-label-overlay left">原始</div>
            </div>
          </template>

          <!-- preview_done / full_processing / full_done: split comparison -->
          <template v-else>
            <div
              class="em-compare"
              ref="compareEl"
              @mousemove="onDividerDrag"
              @mouseup="stopDrag"
              @mouseleave="stopDrag"
              @touchmove.prevent="onDividerTouchMove"
              @touchend="stopDrag"
            >
              <!-- Original (left, full) -->
              <video v-if="!isImage" :src="enhance.originalSrc" ref="leftVid"
                autoplay loop muted playsinline class="em-compare-media" />
              <img  v-else          :src="enhance.originalSrc" class="em-compare-media" />

              <!-- Enhanced (right, clipped) -->
              <video v-if="!isImage" :src="enhance.enhancedSrc" ref="rightVid"
                autoplay loop muted playsinline class="em-compare-media em-compare-right"
                :style="{ clipPath: `inset(0 0 0 ${enhance.dividerPct}%)` }" />
              <img  v-else          :src="enhance.enhancedSrc"
                class="em-compare-media em-compare-right"
                :style="{ clipPath: `inset(0 0 0 ${enhance.dividerPct}%)` }" />

              <!-- Divider line + handle -->
              <div class="em-divider" :style="{ left: enhance.dividerPct + '%' }"
                @mousedown.stop="startDrag" @touchstart.stop="startDrag">
                <div class="em-divider-handle">⟺</div>
              </div>

              <!-- Labels -->
              <div class="em-label-overlay left">原始</div>
              <div class="em-label-overlay right">增强后</div>
            </div>
          </template>
        </div>

        <!-- Progress bar -->
        <div v-if="['preview_processing','full_processing'].includes(enhance.stage)" class="em-progress-wrap">
          <div class="em-progress-bar">
            <div class="em-progress-fill" :style="{ width: enhance.pct + '%' }"></div>
          </div>
          <span class="em-progress-msg">{{ enhance.msg || '处理中…' }} {{ enhance.pct > 0 ? enhance.pct + '%' : '' }}</span>
        </div>

        <!-- Action bar -->
        <div class="em-actions">
          <span v-if="enhance.stage === 'idle'" class="em-hint">
            {{ isImage ? '图片增强无需预览，直接点击「开始增强」' : '先预览 5 秒对比效果，满意后再完整增强' }}
          </span>
          <span v-if="enhance.stage === 'preview_done'" class="em-hint em-hint-ok">
            ✓ 预览完成 — 拖动中间分割线查看对比
          </span>
          <span v-if="enhance.stage === 'full_done'" class="em-hint em-hint-ok">
            ✓ 增强完成，可下载
          </span>
          <span v-if="enhance.error" class="em-hint em-hint-err">{{ enhance.error }}</span>

          <div class="em-btn-group">
            <!-- 预览效果（仅视频 + idle 时显示） -->
            <button
              v-if="!isImage && enhance.stage === 'idle'"
              class="btn-enhance-secondary"
              @click="submitPreview"
            >预览效果（5秒）</button>

            <!-- 开始增强 / 完整增强 -->
            <button
              v-if="['idle','preview_done'].includes(enhance.stage)"
              class="btn-enhance-primary"
              @click="submitFull"
            >{{ enhance.stage === 'preview_done' ? '完整增强' : '开始增强' }}</button>

            <!-- 下载结果 -->
            <a
              v-if="enhance.stage === 'full_done'"
              :href="enhance.downloadUrl"
              class="btn-enhance-primary"
              download
            >下载增强版</a>

            <!-- 下载预览 -->
            <a
              v-if="enhance.stage === 'preview_done' && !isImage"
              :href="enhance.previewDownloadUrl"
              class="btn-enhance-secondary"
              download
            >下载预览片段</a>
          </div>
        </div>

      </div>
    </div>
    <!-- ══════════════ end 画质增强弹窗 ══════════════ -->

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import {
  getRooms, uploadRecording, getRecording, getRecordingClips,
  recordingClipDownloadUrl, revealClip, formatBytes,
  createEnhanceJob, getEnhanceJob, enhanceJobDownloadUrl,
} from '../api.js'
import { useToast } from '../composables/toast.js'

const { show } = useToast()
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''

// ── Upload state ──────────────────────────────────────────────────────────────
const rooms     = ref([])
const roomId    = ref('')
const duration  = ref(60)
const clipCount = ref(1)
const videoFile = ref(null)
const srtFile   = ref(null)
const dragVideo = ref(false)
const dragSrt   = ref(false)
const uploading = ref(false)
const jobs      = ref([])
const videoInput = ref(null)
const srtInput   = ref(null)
let pollTimer = null
const STORAGE_KEY = 'upload_jobs'

const isImage = computed(() => {
  if (!videoFile.value) return false
  const t = videoFile.value.type
  const n = videoFile.value.name.toLowerCase()
  return t.startsWith('image/') || /\.(jpe?g|png|bmp|webp|tiff?)$/.test(n)
})

// ── Enhance modal state ───────────────────────────────────────────────────────
const compareEl  = ref(null)
const leftVid    = ref(null)
const rightVid   = ref(null)

const enhance = ref({
  open:         false,
  stage:        'idle',        // idle | preview_processing | preview_done | full_processing | full_done
  model:        'general',
  targetRes:    '1080p',
  denoise:      'medium',
  pct:          0,
  msg:          '',
  error:        '',
  originalSrc:  '',
  enhancedSrc:  '',
  dividerPct:   50,
  previewJobId: null,
  fullJobId:    null,
  previewDownloadUrl: '',
  downloadUrl:  '',
})
let _origObjUrl  = ''
let _enhObjUrl   = ''
let _enhPollTimer = null
let _dragging     = false

// ── File pick / drop ──────────────────────────────────────────────────────────
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
  srtFile.value   = null
}

// ── Upload & clip ─────────────────────────────────────────────────────────────
function saveJobs() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(jobs.value))
}

async function submit() {
  if (!videoFile.value || !roomId.value || uploading.value || isImage.value) return
  uploading.value = true
  try {
    const room   = rooms.value.find(r => r.id === Number(roomId.value))
    const result = await uploadRecording(roomId.value, videoFile.value, srtFile.value, duration.value, clipCount.value)
    jobs.value.unshift({
      id: result.id, filename: result.filename,
      roomName: room?.name || '—', duration: duration.value,
      transcribed: srtFile.value ? 2 : 0, clipped: 0, clips: [],
    })
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
  pollTimer = setInterval(pollJobs, 8000)
}

async function pollJobs() {
  const pending = jobs.value.filter(j => j.clipped !== 2 && j.clipped !== -1)
  if (!pending.length) { clearInterval(pollTimer); pollTimer = null; return }
  for (const j of pending) {
    try {
      const rec = await getRecording(j.id)
      j.transcribed = rec.transcribed
      j.clipped     = rec.clipped
      if (rec.clipped === 2) {
        show(`剪辑完成：${rec.filename}`, 'success')
        try { j.clips = await getRecordingClips(j.id) } catch {}
      }
    } catch {}
  }
  saveJobs()
}

// ── Enhance modal ─────────────────────────────────────────────────────────────
function openEnhanceModal() {
  if (!videoFile.value) return
  // Create object URL for original preview
  _origObjUrl = URL.createObjectURL(videoFile.value)
  Object.assign(enhance.value, {
    open: true, stage: 'idle', pct: 0, msg: '', error: '',
    originalSrc: _origObjUrl, enhancedSrc: '',
    dividerPct: 50, previewJobId: null, fullJobId: null,
    previewDownloadUrl: '', downloadUrl: '',
  })
}

function closeEnhanceModal() {
  clearInterval(_enhPollTimer)
  _enhPollTimer = null
  enhance.value.open = false
  if (_origObjUrl) { URL.revokeObjectURL(_origObjUrl); _origObjUrl = '' }
  if (_enhObjUrl)  { URL.revokeObjectURL(_enhObjUrl);  _enhObjUrl  = '' }
  enhance.value.enhancedSrc = ''
}

// ── Submit preview (5s) ───────────────────────────────────────────────────────
async function submitPreview() {
  enhance.value.stage = 'preview_processing'
  enhance.value.pct   = 0
  enhance.value.error = ''
  try {
    const { job_id } = await createEnhanceJob(videoFile.value, {
      model:       enhance.value.model,
      targetRes:   enhance.value.targetRes,
      denoise:     enhance.value.denoise,
      previewOnly: true,
    })
    enhance.value.previewJobId = job_id
    _pollEnhance(job_id, 'preview')
  } catch (e) {
    enhance.value.stage = 'idle'
    enhance.value.error = '提交失败: ' + (e.message || e)
  }
}

// ── Submit full job ───────────────────────────────────────────────────────────
async function submitFull() {
  enhance.value.stage = 'full_processing'
  enhance.value.pct   = 0
  enhance.value.error = ''
  try {
    const { job_id } = await createEnhanceJob(videoFile.value, {
      model:       enhance.value.model,
      targetRes:   enhance.value.targetRes,
      denoise:     enhance.value.denoise,
      previewOnly: false,
    })
    enhance.value.fullJobId = job_id
    _pollEnhance(job_id, 'full')
  } catch (e) {
    enhance.value.stage = enhance.value.previewJobId ? 'preview_done' : 'idle'
    enhance.value.error = '提交失败: ' + (e.message || e)
  }
}

function _pollEnhance(jobId, type) {
  clearInterval(_enhPollTimer)
  _enhPollTimer = setInterval(async () => {
    try {
      const data = await getEnhanceJob(jobId)
      enhance.value.pct = data.pct || 0
      enhance.value.msg = data.msg || ''
      if (data.status === 'done') {
        clearInterval(_enhPollTimer)
        _enhPollTimer = null
        const dlUrl = enhanceJobDownloadUrl(jobId)
        if (type === 'preview') {
          enhance.value.previewDownloadUrl = dlUrl
          // Fetch as blob to create object URL for in-page comparison
          const resp = await fetch(dlUrl)
          const blob = await resp.blob()
          if (_enhObjUrl) URL.revokeObjectURL(_enhObjUrl)
          _enhObjUrl = URL.createObjectURL(blob)
          enhance.value.enhancedSrc = _enhObjUrl
          enhance.value.stage = 'preview_done'
          await nextTick()
          syncVideos()
        } else {
          enhance.value.downloadUrl = dlUrl
          enhance.value.stage = 'full_done'
          show('画质增强完成，可下载', 'success')
        }
      } else if (data.status === 'error') {
        clearInterval(_enhPollTimer)
        _enhPollTimer = null
        enhance.value.stage = type === 'preview' ? 'idle' : (enhance.value.previewJobId ? 'preview_done' : 'idle')
        enhance.value.error = data.error || '处理失败'
      }
    } catch {}
  }, 2000)
}

// ── Video sync ────────────────────────────────────────────────────────────────
function syncVideos() {
  const l = leftVid.value
  const r = rightVid.value
  if (!l || !r) return
  l.ontimeupdate = () => {
    if (Math.abs(r.currentTime - l.currentTime) > 0.15) {
      r.currentTime = l.currentTime
    }
  }
}

// ── Divider drag ──────────────────────────────────────────────────────────────
function startDrag(e) {
  _dragging = true
  e.preventDefault()
}
function stopDrag() {
  _dragging = false
}
function onDividerDrag(e) {
  if (!_dragging || !compareEl.value) return
  const rect = compareEl.value.getBoundingClientRect()
  const x = e.clientX - rect.left
  enhance.value.dividerPct = Math.min(95, Math.max(5, (x / rect.width) * 100))
}
function onDividerTouchMove(e) {
  if (!compareEl.value) return
  const rect = compareEl.value.getBoundingClientRect()
  const x = e.touches[0].clientX - rect.left
  enhance.value.dividerPct = Math.min(95, Math.max(5, (x / rect.width) * 100))
}

// ── Download / reveal helpers ─────────────────────────────────────────────────
function clipDownloadUrl(id)         { return `${apiBase}/api/recordings/${id}/clip` }
function clipVariantDownloadUrl(cid) { return recordingClipDownloadUrl(cid) }
async function doReveal(id) {
  try { await revealClip(id) } catch { show('打开失败', 'error') }
}

// ── Badge helpers ─────────────────────────────────────────────────────────────
const transcribeCls = v => ({ 2:'green', 1:'yellow', '-1':'red' }[v] || 'dim')
const transcribeLbl = v => ({ 2:'已转录', 1:'转录中', '-1':'转录失败' }[v] || '待转录')
const clipCls       = v => ({ 2:'green', 1:'yellow', '-1':'red' }[v] || 'dim')
const clipLbl       = v => ({ 2:'剪辑完成', 1:'剪辑中…', '-1':'剪辑失败' }[v] || '等待中')

// ── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(async () => {
  rooms.value = await getRooms()
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    jobs.value = JSON.parse(saved)
    if (jobs.value.some(j => j.clipped !== 2 && j.clipped !== -1)) startPolling()
  }
})
onUnmounted(() => {
  clearInterval(pollTimer)
  clearInterval(_enhPollTimer)
  if (_origObjUrl) URL.revokeObjectURL(_origObjUrl)
  if (_enhObjUrl)  URL.revokeObjectURL(_enhObjUrl)
})
</script>

<style scoped>
/* ── Base ─────────────────────────────────────────────────────────────────── */
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
.drop-zone.zone-disabled { opacity: .35; cursor: default; }
.srt-zone { flex: 0 0 240px; }

.drop-hint { display: flex; flex-direction: column; align-items: center; gap: 6px; pointer-events: none; }
.drop-plus { font-size: 32px; color: #444; line-height: 1; }
.drop-main { font-size: 14px; color: #aaa; }
.drop-sub  { font-size: 12px; color: #555; text-align: center; }
.srt-badge { font-size: 20px; font-weight: 700; color: #666; letter-spacing: 2px; }

.file-info { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 12px; pointer-events: none; }
.file-label { font-size: 11px; color: #555; text-transform: uppercase; letter-spacing: 1px; }
.file-name  { font-size: 13px; color: #ddd; word-break: break-all; text-align: center; max-width: 200px; }
.file-size  { font-size: 12px; color: #666; }

/* ── Settings row ─────────────────────────────────────────────────────────── */
.settings-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sel { background: #1a1a1a; border: 1px solid #333; color: #ccc; padding: 8px 12px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.dur-wrap { display: flex; align-items: center; gap: 6px; }
.dur-input   { width: 80px; }
.count-input { width: 56px; }
.dur-unit { font-size: 13px; color: #666; }

.btn-submit {
  background: #fe2c55; color: #fff; border: none; padding: 8px 22px;
  border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500;
}
.btn-submit:hover:not(:disabled) { background: #e0254b; }
.btn-submit:disabled { opacity: .4; cursor: not-allowed; }

.btn-enhance {
  background: linear-gradient(135deg, #7c3aed, #4f46e5);
  color: #fff; border: none; padding: 8px 18px;
  border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500;
  transition: filter .2s;
}
.btn-enhance:hover { filter: brightness(1.15); }

.btn-clear { background: #2a2a2a; border: 1px solid #444; color: #888; padding: 8px 14px; border-radius: 6px; font-size: 13px; cursor: pointer; }
.btn-clear:hover { color: #ccc; }

/* ── Progress bar ─────────────────────────────────────────────────────────── */
.progress-wrap  { margin-top: 16px; display: flex; align-items: center; gap: 12px; }
.progress-bar   { flex: 1; height: 4px; background: #222; border-radius: 2px; overflow: hidden; }
.progress-fill  { height: 100%; background: #fe2c55; border-radius: 2px; }
.progress-fill.animate { width: 100%; animation: indeterminate 1.4s infinite ease-in-out; }
@keyframes indeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
.progress-label { font-size: 12px; color: #666; white-space: nowrap; }

/* ── Jobs table ───────────────────────────────────────────────────────────── */
.jobs-section { margin-top: 4px; }
.jobs-title   { font-size: 14px; font-weight: 500; color: #888; margin-bottom: 12px; }
.jobs-table   { width: 100%; border-collapse: collapse; font-size: 13px; }
.jobs-table th { text-align: left; padding: 10px 14px; color: #666; font-weight: 500; border-bottom: 1px solid #222; }
.jobs-table td { padding: 12px 14px; border-bottom: 1px solid #1a1a1a; }
.jobs-table tr:hover td { background: #141414; }
.fname { font-family: monospace; font-size: 12px; color: #aaa; }

.badge        { font-size: 11px; padding: 2px 8px; border-radius: 10px; text-decoration: none; display: inline-block; }
.badge.green  { background: rgba(34,197,94,0.15);  color: #22c55e; }
.badge.yellow { background: rgba(251,191,36,0.15); color: #fbbf24; }
.badge.red    { background: rgba(254,44,85,0.15);  color: #fe2c55; }
.badge.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge.dim    { background: #2a2a2a; color: #555; }
.badge.purple:hover { filter: brightness(1.3); }
.action-col { display: flex; flex-direction: column; gap: 4px; }
.btn-action { border: none; cursor: pointer; }

/* ══════════════════ 画质增强弹窗 ══════════════════ */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.75);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000; padding: 20px;
}

.enhance-modal {
  background: #141414; border: 1px solid #2a2a2a; border-radius: 14px;
  width: min(960px, 100%); max-height: 90vh;
  display: flex; flex-direction: column; overflow: hidden;
}

/* Header */
.em-header {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 16px 20px; border-bottom: 1px solid #222; flex-shrink: 0;
}
.em-title {
  font-size: 15px; font-weight: 600; color: #e5e7eb;
  display: flex; align-items: center; gap: 10px; white-space: nowrap;
}
.em-fname { font-size: 12px; color: #555; font-weight: 400; max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.em-options { display: flex; gap: 10px; flex: 1; flex-wrap: wrap; }
.em-opt-label { font-size: 11px; color: #666; display: flex; flex-direction: column; gap: 3px; }
.em-sel {
  background: #1e1e1e; border: 1px solid #333; color: #ccc;
  padding: 5px 8px; border-radius: 5px; font-size: 12px; cursor: pointer;
}
.em-sel:disabled { opacity: .5; cursor: default; }
.em-close {
  background: none; border: none; color: #555; font-size: 16px;
  cursor: pointer; padding: 4px 6px; border-radius: 4px; margin-left: auto;
}
.em-close:hover { color: #ccc; }

/* Preview area */
.em-preview-area {
  flex: 1; overflow: hidden; background: #0a0a0a;
  min-height: 300px; position: relative;
  display: flex; align-items: center; justify-content: center;
}

/* Single preview (before comparison) */
.em-single-preview {
  width: 100%; height: 100%; position: relative;
  display: flex; align-items: center; justify-content: center;
}
.em-media {
  max-width: 100%; max-height: 100%;
  width: 100%; height: 100%; object-fit: contain;
}
.em-img { object-fit: contain; }

/* Split comparison */
.em-compare {
  position: relative; width: 100%; height: 100%;
  overflow: hidden; user-select: none; cursor: col-resize;
}
.em-compare-media {
  position: absolute; inset: 0;
  width: 100%; height: 100%; object-fit: contain;
}
.em-compare-right {
  /* clip-path applied inline via :style */
}

/* Divider */
.em-divider {
  position: absolute; top: 0; bottom: 0; width: 3px;
  background: rgba(255,255,255,.85); transform: translateX(-50%);
  cursor: col-resize; z-index: 10;
  display: flex; align-items: center; justify-content: center;
}
.em-divider-handle {
  width: 32px; height: 32px; border-radius: 50%;
  background: #fff; color: #111;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700; box-shadow: 0 2px 8px rgba(0,0,0,.5);
  cursor: col-resize;
}

/* Label overlays */
.em-label-overlay {
  position: absolute; top: 12px; font-size: 11px; font-weight: 600;
  background: rgba(0,0,0,.55); color: #ddd;
  padding: 3px 10px; border-radius: 20px; z-index: 5; pointer-events: none;
}
.em-label-overlay.left  { left: 12px; }
.em-label-overlay.right { right: 12px; }

/* Progress */
.em-progress-wrap {
  padding: 12px 20px; border-top: 1px solid #1a1a1a;
  display: flex; align-items: center; gap: 12px; flex-shrink: 0;
}
.em-progress-bar  { flex: 1; height: 5px; background: #222; border-radius: 3px; overflow: hidden; }
.em-progress-fill { height: 100%; background: linear-gradient(90deg, #7c3aed, #4f46e5); border-radius: 3px; transition: width .4s; }
.em-progress-msg  { font-size: 12px; color: #888; white-space: nowrap; min-width: 120px; text-align: right; }

/* Action bar */
.em-actions {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; border-top: 1px solid #1a1a1a; flex-shrink: 0;
  flex-wrap: wrap; gap: 10px;
}
.em-hint        { font-size: 12px; color: #666; }
.em-hint-ok     { color: #34d399; }
.em-hint-err    { color: #fe2c55; }
.em-btn-group   { display: flex; gap: 8px; margin-left: auto; }

.btn-enhance-primary {
  background: linear-gradient(135deg, #7c3aed, #4f46e5);
  color: #fff; border: none; padding: 8px 22px;
  border-radius: 6px; font-size: 13px; cursor: pointer; font-weight: 500;
  text-decoration: none; display: inline-flex; align-items: center;
  transition: filter .2s;
}
.btn-enhance-primary:hover { filter: brightness(1.15); }

.btn-enhance-secondary {
  background: #1e1e1e; color: #a78bfa; border: 1px solid #4f46e5;
  padding: 8px 18px; border-radius: 6px; font-size: 13px; cursor: pointer;
  text-decoration: none; display: inline-flex; align-items: center;
  transition: background .2s;
}
.btn-enhance-secondary:hover { background: rgba(79,70,229,.15); }
</style>
