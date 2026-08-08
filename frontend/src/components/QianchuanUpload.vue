<template>
  <div class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal qianchuan-upload-modal">
      <div class="modal-header">
        <h3>千川学习 · 素材上传</h3>
        <button class="btn-close" @click="$emit('close')">✕</button>
      </div>

      <div class="modal-body">
        <!-- Drag & Drop Zone -->
        <div
          :class="['upload-dropzone', { 'upload-dropzone-dragover': dragOver, 'upload-dropzone-disabled': uploading }]"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="onDrop"
          @click="triggerFileInput"
        >
          <input
            ref="fileInput"
            type="file"
            multiple
            :accept="acceptedExtensions"
            style="display:none"
            @change="onFileSelect"
          />
          <div class="dropzone-content">
            <div class="dropzone-icon">📁</div>
            <div class="dropzone-text">
              <template v-if="!uploading">拖拽文件到此处，或点击选择文件</template>
              <template v-else>上传中，请稍候…</template>
            </div>
            <div class="dropzone-hint">
              支持 MP4、MOV、WebM 参考视频 + JPG/PNG/WAV/SRT 辅助素材<br />
              视频最大 500 MiB，辅助文件最大 50 MiB，最多 10 个文件
            </div>
          </div>
        </div>

        <!-- File List -->
        <div v-if="files.length > 0" class="file-list">
          <div
            v-for="(f, idx) in files"
            :key="idx"
            :class="['file-item', { 'file-item-error': f.error }]"
          >
            <span :class="['file-icon', f.type === 'video' ? 'file-icon-video' : 'file-icon-aux']">
              {{ f.type === 'video' ? '🎬' : f.type === 'image' ? '🖼' : f.type === 'audio' ? '🎵' : '📄' }}
            </span>
            <span class="file-name">{{ f.name }}</span>
            <span class="file-size">{{ formatBytes(f.size) }}</span>
            <span v-if="f.error" class="file-error-text">{{ f.error }}</span>
            <button
              v-if="!uploading && !uploadResult"
              class="file-remove"
              @click="removeFile(idx)"
              title="移除文件"
            >✕</button>
          </div>
        </div>

        <!-- Label Input -->
        <div v-if="!uploading && !uploadResult" class="form-group">
          <label class="form-label">素材标签（可选）</label>
          <input
            v-model="label"
            type="text"
            class="form-input"
            placeholder="例如：618保湿面膜参考"
            maxlength="200"
          />
        </div>

        <!-- Upload Progress -->
        <div v-if="uploading" class="upload-progress">
          <div class="progress-bar-container">
            <div class="progress-bar" :style="{ width: uploadProgress + '%' }"></div>
          </div>
          <div class="progress-text">
            {{ uploadProgress < 100 ? `上传中 ${uploadProgress}%…` : '处理中，请稍候…' }}
          </div>
        </div>

        <!-- Upload Error -->
        <div v-if="uploadError" class="upload-error">
          ⚠ {{ uploadError }}
        </div>

        <!-- Upload Result / Job Status -->
        <div v-if="uploadResult" class="upload-result">
          <div v-if="uploadResult.status === 'queued' || uploadResult.status === 'running'" class="result-status status-running">
            <span class="status-icon">⏳</span>
            <span>任务 {{ uploadResult.job_id }} — {{ uploadResult.status === 'queued' ? '排队中' : '分析中' }}</span>
          </div>
          <div v-else-if="uploadResult.status === 'succeeded'" class="result-status status-success">
            <span class="status-icon">✅</span>
            <span>任务 {{ uploadResult.job_id }} — 分析完成</span>
          </div>
          <div v-else-if="uploadResult.status === 'failed'" class="result-status status-error">
            <span class="status-icon">❌</span>
            <span>任务 {{ uploadResult.job_id }} — 分析失败</span>
            <div class="result-error-detail" v-if="uploadResult.error">{{ uploadResult.error }}</div>
          </div>

          <!-- Job Detail: Quality Scores -->
          <div v-if="uploadResult.result" class="job-detail">
            <div class="job-detail-header">参考视频质量评分</div>
            <div class="score-grid">
              <div class="score-item">
                <div class="score-label">综合</div>
                <div class="score-value score-overall">{{ uploadResult.result.quality.overall.toFixed(1) }}</div>
              </div>
              <div class="score-item">
                <div class="score-label">视觉</div>
                <div class="score-value">{{ uploadResult.result.quality.dimensions.visual.toFixed(1) }}</div>
              </div>
              <div class="score-item">
                <div class="score-label">音频</div>
                <div class="score-value">{{ uploadResult.result.quality.dimensions.audio.toFixed(1) }}</div>
              </div>
              <div class="score-item">
                <div class="score-label">语义</div>
                <div class="score-value">{{ uploadResult.result.quality.dimensions.semantic.toFixed(1) }}</div>
              </div>
              <div class="score-item">
                <div class="score-label">结构</div>
                <div class="score-value">{{ uploadResult.result.quality.dimensions.structural.toFixed(1) }}</div>
              </div>
              <div class="score-item">
                <div class="score-label">转化</div>
                <div class="score-value">{{ uploadResult.result.quality.dimensions.conversion.toFixed(1) }}</div>
              </div>
            </div>
            <div v-if="uploadResult.result.quality.suggestions.length > 0" class="job-suggestions">
              <div class="suggestions-header">改进建议</div>
              <ul>
                <li v-for="(s, i) in uploadResult.result.quality.suggestions" :key="i">{{ s }}</li>
              </ul>
            </div>
          </div>

          <!-- Polling Controls -->
          <div v-if="uploadResult.status === 'queued' || uploadResult.status === 'running'" class="poll-status">
            自动轮询中… <button class="btn-sm" @click="refreshJobStatus">手动刷新</button>
          </div>
        </div>
      </div>

      <div class="modal-footer">
        <button
          v-if="!uploadResult"
          class="btn-primary"
          :disabled="!canUpload || uploading"
          @click="startUpload"
        >
          {{ uploading ? '上传中…' : '开始上传' }}
        </button>
        <button
          v-if="uploadResult && (uploadResult.status === 'running' || uploadResult.status === 'queued')"
          class="btn-primary"
          @click="refreshJobStatus"
        >
          🔄 刷新状态
        </button>
        <button class="btn-secondary" @click="$emit('close')">
          {{ uploadResult && uploadResult.status === 'succeeded' ? '完成' : '关闭' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onUnmounted, watch } from 'vue'
import {
  uploadQianchuanMaterials,
  getQianchuanUploadJobStatus,
  formatBytes,
} from '../api.js'

const emit = defineEmits(['close'])

// ── State ──────────────────────────────────────────────────────────────────

const fileInput = ref(null)
const dragOver = ref(false)
const files = ref([])
const label = ref('')
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadResult = ref(null)
const uploadError = ref(null)
let pollTimer = null

const acceptedExtensions = '.mp4,.mov,.webm,.mkv,.avi,.jpg,.jpeg,.png,.bmp,.webp,.mp3,.wav,.aac,.ogg,.flac,.srt,.vtt,.json'

const ALLOWED_VIDEO = new Set(['.mp4', '.mov', '.webm', '.mkv', '.avi'])
const ALLOWED_IMAGE = new Set(['.jpg', '.jpeg', '.png', '.bmp', '.webp'])
const ALLOWED_AUDIO = new Set(['.mp3', '.wav', '.aac', '.ogg', '.flac'])
const ALLOWED_TEXT = new Set(['.srt', '.vtt', '.json'])
const ALLOWED_ALL = new Set([...ALLOWED_VIDEO, ...ALLOWED_IMAGE, ...ALLOWED_AUDIO, ...ALLOWED_TEXT])

const MAX_VIDEO = 500 * 1024 * 1024
const MAX_AUX = 50 * 1024 * 1024
const MAX_FILES = 10

// ── Computed ───────────────────────────────────────────────────────────────

const canUpload = computed(() => {
  return files.value.length > 0 && !uploading.value && files.value.every(f => !f.error)
})

// ── Methods ────────────────────────────────────────────────────────────────

function classifyFile(name) {
  const ext = '.' + (name.split('.').pop() || '').toLowerCase()
  if (ALLOWED_VIDEO.has(ext)) return 'video'
  if (ALLOWED_IMAGE.has(ext)) return 'image'
  if (ALLOWED_AUDIO.has(ext)) return 'audio'
  if (ALLOWED_TEXT.has(ext)) return 'text'
  return 'other'
}

function validateFile(file) {
  const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
  if (!ALLOWED_ALL.has(ext)) {
    return `不支持的文件格式 .${ext.replace('.', '')}`
  }
  const type = classifyFile(file.name)
  if (type === 'video' && file.size > MAX_VIDEO) {
    return `视频文件超过 500 MiB 限制`
  }
  if (type !== 'video' && file.size > MAX_AUX) {
    return `辅助文件超过 50 MiB 限制`
  }
  return null
}

function addFiles(fileList) {
  for (const f of fileList) {
    if (files.value.length >= MAX_FILES) {
      return
    }
    // Check for duplicate names
    if (files.value.some(existing => existing.name === f.name && existing.size === f.size)) {
      continue
    }
    const error = validateFile(f)
    files.value.push({
      name: f.name,
      size: f.size,
      type: classifyFile(f.name),
      error,
      file: f,
    })
  }
}

function triggerFileInput() {
  if (!uploading.value && !uploadResult.value) {
    fileInput.value?.click()
  }
}

function onFileSelect(e) {
  addFiles(e.target.files || [])
  e.target.value = ''
}

function onDrop(e) {
  dragOver.value = false
  if (uploading.value || uploadResult.value) return
  addFiles(e.dataTransfer.files || [])
}

function removeFile(idx) {
  files.value.splice(idx, 1)
}

async function startUpload() {
  if (!canUpload.value) return

  uploadError.value = null
  uploading.value = true
  uploadProgress.value = 0

  try {
    const mainVideo = files.value.find(f => f.type === 'video')
    const auxFiles = files.value.filter(f => f.type !== 'video')

    if (!mainVideo) {
      throw new Error('必须包含一个视频文件')
    }

    // Simulate progress via timeout since we're reading the file
    const progressSim = setInterval(() => {
      if (uploadProgress.value < 90) {
        uploadProgress.value += 5
      }
    }, 200)

    const result = await uploadQianchuanMaterials(
      mainVideo.file,
      auxFiles.map(f => f.file),
      label.value || null,
      true,
    )

    clearInterval(progressSim)
    uploadProgress.value = 100

    uploadResult.value = {
      job_id: result.job_id,
      status: result.status,
      uploads: result.uploads,
      result: null,
      error: null,
    }

    // Start polling if analysis was triggered
    if (result.status === 'queued') {
      startPolling(result.job_id)
    }
  } catch (err) {
    uploadError.value = err.message || '上传失败，请重试'
  } finally {
    uploading.value = false
    uploadProgress.value = 0
  }
}

function startPolling(jobId) {
  stopPolling()
  pollTimer = setInterval(() => {
    pollJobStatus(jobId)
  }, 2000)
  // Do an immediate poll
  pollJobStatus(jobId)
}

async function pollJobStatus(jobId) {
  try {
    const status = await getQianchuanUploadJobStatus(jobId)
    uploadResult.value = {
      ...uploadResult.value,
      status: status.status,
      result: status.result,
      error: status.error,
    }

    if (status.status === 'succeeded' || status.status === 'failed') {
      stopPolling()
    }
  } catch {
    // Polling will continue; if the backend is truly down it'll fail on refresh
  }
}

async function refreshJobStatus() {
  if (uploadResult.value?.job_id) {
    await pollJobStatus(uploadResult.value.job_id)
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// ── Cleanup ────────────────────────────────────────────────────────────────

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
/* Inherits base modal styles — keep self-contained with scoped overrides */

.qianchuan-upload-modal {
  max-width: 620px;
  width: 90vw;
}

.upload-dropzone {
  border: 2px dashed var(--border-color, #475569);
  border-radius: 12px;
  padding: 36px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
  background: var(--card-bg, rgba(30,41,59,0.5));
}

.upload-dropzone:hover,
.upload-dropzone-dragover {
  border-color: var(--accent, #38bdf8);
  background: rgba(56, 189, 248, 0.06);
}

.upload-dropzone-disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.dropzone-icon {
  font-size: 42px;
  margin-bottom: 8px;
}

.dropzone-text {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  margin-bottom: 4px;
}

.dropzone-hint {
  font-size: 12px;
  color: var(--text-muted, #94a3b8);
  line-height: 1.5;
}

.file-list {
  margin-top: 14px;
  max-height: 200px;
  overflow-y: auto;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--card-bg, rgba(30,41,59,0.35));
  margin-bottom: 4px;
  font-size: 13px;
}

.file-item-error {
  border: 1px solid #ef4444;
}

.file-icon { font-size: 16px; flex-shrink: 0; }
.file-icon-video { color: #38bdf8; }
.file-icon-aux { color: #a78bfa; }

.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary, #f1f5f9);
}

.file-size {
  color: var(--text-muted, #94a3b8);
  font-size: 12px;
  flex-shrink: 0;
}

.file-error-text {
  color: #ef4444;
  font-size: 12px;
  flex-shrink: 0;
}

.file-remove {
  background: none;
  border: none;
  color: #ef4444;
  cursor: pointer;
  font-size: 14px;
  padding: 2px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}

.file-remove:hover {
  background: rgba(239, 68, 68, 0.15);
}

.form-group {
  margin-top: 14px;
}

.form-label {
  display: block;
  font-size: 13px;
  color: var(--text-muted, #94a3b8);
  margin-bottom: 4px;
}

.form-input {
  width: 100%;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid var(--border-color, #475569);
  background: var(--input-bg, rgba(15,23,42,0.6));
  color: var(--text-primary, #f1f5f9);
  font-size: 14px;
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  border-color: var(--accent, #38bdf8);
}

.upload-progress {
  margin-top: 14px;
}

.progress-bar-container {
  height: 6px;
  background: var(--border-color, #475569);
  border-radius: 3px;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: var(--accent, #38bdf8);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 12px;
  color: var(--text-muted, #94a3b8);
  margin-top: 6px;
  text-align: center;
}

.upload-error {
  margin-top: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
  font-size: 13px;
}

.upload-result {
  margin-top: 14px;
}

.result-status {
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.status-running {
  background: rgba(251, 191, 36, 0.12);
  color: #fbbf24;
}

.status-success {
  background: rgba(34, 197, 94, 0.12);
  color: #22c55e;
}

.status-error {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.result-error-detail {
  width: 100%;
  margin-top: 6px;
  font-size: 12px;
  color: #fca5a5;
  word-break: break-all;
}

.job-detail {
  margin-top: 14px;
  padding: 14px;
  border-radius: 8px;
  background: var(--card-bg, rgba(30,41,59,0.35));
}

.job-detail-header {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  margin-bottom: 10px;
}

.score-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.score-item {
  text-align: center;
  padding: 8px 4px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.4);
}

.score-label {
  font-size: 11px;
  color: var(--text-muted, #94a3b8);
  margin-bottom: 2px;
}

.score-value {
  font-size: 20px;
  font-weight: 700;
  color: #38bdf8;
}

.score-overall {
  color: #fbbf24;
  font-size: 26px;
}

.job-suggestions {
  margin-top: 12px;
}

.suggestions-header {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
  margin-bottom: 6px;
}

.job-suggestions ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--text-muted, #cbd5e1);
  line-height: 1.6;
}

.poll-status {
  margin-top: 10px;
  font-size: 12px;
  color: var(--text-muted, #94a3b8);
  text-align: center;
}

.modal-footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding-top: 14px;
  border-top: 1px solid var(--border-color, #334155);
  margin-top: 14px;
}
</style>
