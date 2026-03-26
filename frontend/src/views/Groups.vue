<template>
  <div>
    <div class="toolbar">
      <h2>分组管理</h2>
      <div class="toolbar-actions">
        <button class="btn-primary" @click="openCreateGroupModal">+ 新建分组</button>
        <button class="btn-custom" @click="openCustomGroupModal">+ 自定义分组</button>
      </div>
    </div>

    <div v-if="groups.length === 0" class="empty-tip">
      暂无分组。录像完成转录和剪辑后，系统会自动按款式/颜色分组。
    </div>

    <div class="groups-list">
      <div v-for="g in groups" :key="g.id" :class="['group-card', g.is_custom && 'group-card-custom']">
        <!-- Group header -->
        <div class="group-header">
          <div class="group-meta">
            <div class="group-label">{{ g.label }}</div>
            <div class="group-sub">
              <span v-if="!g.is_custom" class="tag">{{ g.room_name }}</span>
              <span v-else class="tag" style="background:rgba(251,146,60,0.15);color:#c2540a;">自定义</span>
              <span class="tag" v-if="g.wig_model">{{ g.wig_model }}</span>
              <span class="tag color" v-if="g.wig_color">{{ g.wig_color }}</span>
              <span v-if="g.published_count > 0" class="tag published-tag">已发布 {{ g.published_count }} 次</span>
            </div>
          </div>
          <div class="group-stats">
            <span class="stat-item">{{ g.ready_count }} / {{ g.clip_count }} 条剪辑</span>
            <button class="btn-edit" @click="openEditGroupModal(g)" title="编辑分组">✎</button>
            <button class="btn-del" @click="doDeleteGroup(g)" title="删除分组">✕</button>
          </div>
          <div class="group-actions">
            <template v-if="g.merge_status === 2">
              <a :href="`${apiBase}/api/groups/${g.id}/download`" class="btn-action purple">
                下载合并视频
              </a>
            </template>
            <button
              v-else-if="g.merge_status === 1"
              class="btn-action yellow" disabled>
              合并中…
            </button>
            <button
              v-else-if="g.merge_status === -1"
              class="btn-action red"
              @click="doMerge(g)">
              ↺ 重新合并
            </button>
            <button
              v-else
              class="btn-action"
              :disabled="g.ready_count === 0"
              @click="doMerge(g)">
              合并剪辑
            </button>
            <button class="btn-sm" @click="toggleDetail(g.id)">
              {{ openId === g.id ? '收起' : '查看详情' }}
            </button>
          </div>
        </div>

        <!-- Custom group upload -->
        <div v-if="g.is_custom" class="custom-upload-row">
          <label :for="`upload-${g.id}`" class="btn-upload-label">+ 上传视频</label>
          <input :id="`upload-${g.id}`" type="file" accept="video/mp4,video/*" class="hidden-file-input"
                 @change="e => doUploadVideo(g.id, e)" />
          <span v-if="uploadingId === g.id" class="uploading-hint">上传中…</span>
        </div>

        <!-- Merge status -->
        <div v-if="g.merge_status === -1" class="merge-error">
          上次合并失败
          <button v-if="g.merge_error" class="btn-error-detail" @click.stop="showMergeError(g)">查看原因</button>
        </div>

        <!-- Quality issue warning -->
        <div v-if="g.quality_issue" class="quality-issue-bar">
          <span class="quality-issue-icon">⚠️</span>
          <span class="quality-issue-text">发布质量检测不通过：{{ g.quality_issue }}</span>
          <button class="btn-action red btn-sm" style="margin-left:auto" @click="doMerge(g)">↺ 重新剪辑后合并</button>
        </div>

        <!-- Detail: recordings in group -->
        <div v-if="openId === g.id && detail">
          <div class="detail-loading" v-if="detailLoading">加载中…</div>
          <table v-else class="detail-table">
            <thead>
              <tr>
                <th></th>
                <th>文件名</th>
                <th>内容摘要</th>
                <th>标签</th>
                <th>处理状态</th>
                <th>移至分组</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in detail.recordings" :key="r.id">
                <td class="thumb-cell">
                  <img v-if="r.clipped === 2"
                       :src="getThumbnailUrl(r.id)"
                       class="thumb-img"
                       @error="e => e.target.style.display='none'" />
                  <div v-else class="thumb-placeholder"></div>
                </td>
                <td class="filename">{{ r.filename }}</td>
                <td>{{ r.session_label || '—' }}</td>
                <td>
                  <span v-if="r.has_tryon" class="tag">试戴</span>
                  <span v-if="r.has_promotion" class="tag promo">促销</span>
                </td>
                <td class="status-cell">
                  <!-- failed states -->
                  <span v-if="r.transcribed === -1" class="badge red" :title="r.transcribe_error || ''">转录失败</span>
                  <span v-else-if="r.clipped === -1" class="badge red">剪辑失败</span>
                  <!-- done -->
                  <span v-else-if="r.clipped === 2" class="clip-done-row">
                    <button class="badge-btn purple" @click="openPreview(r)">▶ 预览</button>
                    <a :href="`${apiBase}/api/recordings/${r.id}/clip`" class="badge purple">↓</a>
                    <button class="badge-btn orange" @click="openReclip(r)">↺ 重剪</button>
                  </span>
                  <!-- pending (no active progress) -->
                  <span v-else-if="r.transcribed === 0 && !progressMap[r.id]" class="badge dim">待转录</span>
                  <span v-else-if="r.transcribed === 2 && r.clipped === 0 && !progressMap[r.id]" class="badge dim">待剪辑</span>
                  <!-- in-progress with progress bar -->
                  <div v-else-if="progressMap[r.id]" class="progress-wrap">
                    <div class="progress-label">
                      <span class="progress-msg">{{ progressMap[r.id].msg }}</span>
                      <span class="progress-pct">{{ progressMap[r.id].pct }}%</span>
                    </div>
                    <div class="progress-bar-bg">
                      <div class="progress-bar-fill" :style="{ width: progressMap[r.id].pct + '%' }"></div>
                    </div>
                    <div v-if="progressMap[r.id].eta_seconds != null" class="progress-eta">
                      {{ formatEta(progressMap[r.id].eta_seconds) }}
                    </div>
                  </div>
                  <!-- fallback in-progress without data yet -->
                  <span v-else-if="r.transcribed === 1" class="badge yellow">转录中…</span>
                  <span v-else-if="r.clipped === 1" class="badge yellow">剪辑中…</span>
                </td>
                <td>
                  <select class="reassign-select"
                          :value="r.group_id"
                          @change="doReassign(r.id, $event.target.value)">
                    <option value="">— 不分组 —</option>
                    <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.label }}</option>
                  </select>
                </td>
              </tr>
              <tr v-if="detail.recordings.length === 0">
                <td colspan="6" class="empty">此分组暂无录像</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- Group Create / Edit Modal -->
  <div v-if="groupModal" class="modal-backdrop" @click.self="groupModal = null">
    <div class="modal">
      <div class="modal-header">
        <span>{{ groupModal.mode === 'create' ? '新建分组' : '编辑分组' }}</span>
        <button class="modal-close" @click="groupModal = null">✕</button>
      </div>
      <div class="modal-field" v-if="groupModal.mode === 'create'">
        <label>直播间</label>
        <select v-model="groupModal.room_id" class="modal-input">
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
      </div>
      <div class="modal-field">
        <label>分组标签</label>
        <input v-model="groupModal.label" class="modal-input" placeholder="例：大波浪 自然黑" />
      </div>
      <div class="modal-field">
        <label>款式 <span class="field-hint">可留空</span></label>
        <input v-model="groupModal.wig_model" class="modal-input" placeholder="例：大波浪卷发" />
      </div>
      <div class="modal-field">
        <label>颜色 <span class="field-hint">可留空</span></label>
        <input v-model="groupModal.wig_color" class="modal-input" placeholder="例：自然黑" />
      </div>
      <div class="modal-field">
        <label>批量导入视频 <span class="field-hint">可选 — 每行一个 .mp4 文件路径</span></label>
        <textarea
          v-model="groupModal.importPaths"
          class="modal-input"
          rows="4"
          placeholder="/Users/claw/work/douyin-recorder/recordings/video1.mp4&#10;/Users/claw/work/douyin-recorder/recordings/video2.mp4"
        ></textarea>
        <div v-if="importPreviewCount > 0" class="import-preview">已填入 {{ importPreviewCount }} 个路径</div>
      </div>
      <div class="modal-footer">
        <button class="btn-action" @click="groupModal = null">取消</button>
        <button class="btn-action purple" :disabled="groupModalSaving || !groupModal.label.trim()" @click="saveGroupModal">
          {{ groupModalSaving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>

  <!-- Video Preview Modal -->
  <div v-if="previewRec" class="modal-backdrop" @click.self="closePreview">
    <div class="preview-modal">
      <div class="preview-header">
        <span class="preview-title">{{ previewRec.filename }}</span>
        <button class="modal-close" @click="closePreview">✕</button>
      </div>
      <video
        :src="`${apiBase}/api/recordings/${previewRec.id}/clip`"
        controls
        autoplay
        class="preview-video"
        @error="previewError = true"
      ></video>
      <div v-if="previewError" class="preview-err">视频加载失败</div>
      <div class="preview-footer">
        <a :href="`${apiBase}/api/recordings/${previewRec.id}/clip`" class="btn-action purple" download>下载</a>
      </div>
    </div>
  </div>

  <!-- Re-clip Feedback Modal -->
  <div v-if="reclipModal" class="modal-backdrop" @click.self="!reclipSaving && (reclipModal = null)">
    <div class="modal">
      <!-- Success state -->
      <template v-if="reclipModal.submitted">
        <div class="reclip-success">
          <div class="reclip-success-icon">✓</div>
          <div class="reclip-success-title">视频重剪已加入队列</div>
          <div class="reclip-success-sub">
            {{ reclipModal.feedback.trim() ? 'AI 正在分析你的反馈，将优化片段选取策略' : '将使用不同片段组合重新生成' }}
          </div>
        </div>
        <div class="modal-footer" style="justify-content:center">
          <button class="btn-action purple" @click="reclipModal = null">知道了</button>
        </div>
      </template>
      <!-- Input state -->
      <template v-else>
        <div class="modal-header">
          <span>↺ 重新剪辑</span>
          <button class="modal-close" @click="reclipModal = null">✕</button>
        </div>
        <div class="modal-field">
          <label>不满意的原因 <span class="field-hint">可留空，填写后 AI 会针对性优化</span></label>
          <textarea
            v-model="reclipModal.feedback"
            class="modal-input"
            rows="4"
            placeholder="例：选的片段太短，没有突出促销信息；或：视频内容跳跃太厉害，希望更连贯…"
          ></textarea>
        </div>
        <div class="reclip-hint">
          <span v-if="reclipModal.feedback.trim()">✦ AI 将根据你的反馈调整片段选取策略</span>
          <span v-else>留空则直接重新生成（使用不同的片段组合）</span>
        </div>
        <div class="modal-footer">
          <button class="btn-action" @click="reclipModal = null">取消</button>
          <button class="btn-action purple" :disabled="reclipSaving" @click="doReclip">
            {{ reclipSaving ? '提交中…' : '确认重新剪辑' }}
          </button>
        </div>
      </template>
    </div>
  </div>

  <!-- Custom Group Create Modal -->
  <div v-if="customModal" class="modal-backdrop" @click.self="customModal = null">
    <div class="modal modal-custom">
      <div class="modal-header">
        <span>新建自定义分组</span>
        <button class="modal-close" @click="customModal = null">✕</button>
      </div>
      <div class="modal-field">
        <label>分组标签 *</label>
        <input v-model="customModal.label" class="modal-input" placeholder="例：大波浪 自然黑" />
      </div>
      <div class="modal-field">
        <label>款式 <span class="field-hint">可留空</span></label>
        <input v-model="customModal.wig_model" class="modal-input" placeholder="例：大波浪卷发" />
      </div>
      <div class="modal-field">
        <label>颜色 <span class="field-hint">可留空</span></label>
        <input v-model="customModal.wig_color" class="modal-input" placeholder="例：自然黑" />
      </div>
      <div class="modal-footer">
        <button class="btn-action" @click="customModal = null">取消</button>
        <button class="btn-action orange" :disabled="customModalSaving || !customModal.label.trim()" @click="saveCustomModal">
          {{ customModalSaving ? '创建中…' : '创建' }}
        </button>
      </div>
    </div>
  </div>

  <!-- Merge error detail modal -->
  <div v-if="mergeErrorGroup" class="modal-overlay" @click.self="mergeErrorGroup = null">
    <div class="modal-box">
      <div class="modal-title">合并失败原因 — {{ mergeErrorGroup.label }}</div>
      <pre class="error-pre">{{ mergeErrorGroup.merge_error || '无详细信息' }}</pre>
      <button class="btn-action" style="margin-top:12px" @click="mergeErrorGroup = null">关闭</button>
    </div>
  </div>

</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getGroups, getGroup, getRooms, mergeGroup, createGroup, updateGroup, reassignRecording, importGroupVideos, createWS, getThumbnailUrl, createCustomGroup, uploadCustomGroupVideo, deleteGroup, getProcessingProgress, reclipRecording } from '../api.js'
import { useToast } from '../composables/toast.js'

const groups = ref([])
const rooms = ref([])
const openId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''
let ws = null

const { show } = useToast()

// Group create/edit modal: { mode: 'create'|'edit', id?, room_id, label, wig_model, wig_color, importPaths }
const groupModal = ref(null)
const groupModalSaving = ref(false)

// Custom group modal
const customModal = ref(null)
const customModalSaving = ref(false)
const uploadingId = ref(null)

// Processing progress: { [recording_id]: { pct, msg, eta_seconds, phase } }
const progressMap = ref({})
let progressTimer = null

// Merge error detail
const mergeErrorGroup = ref(null)
function showMergeError(g) { mergeErrorGroup.value = g }

// Video preview
const previewRec = ref(null)
const previewError = ref(false)
function openPreview(r) { previewRec.value = r; previewError.value = false }
function closePreview() { previewRec.value = null }

// Re-clip
const reclipModal = ref(null)
const reclipSaving = ref(false)
function openReclip(r) { reclipModal.value = { rec: r, feedback: '' } }
async function doReclip() {
  if (!reclipModal.value) return
  reclipSaving.value = true
  const { rec, feedback } = reclipModal.value
  try {
    await reclipRecording(rec.id, feedback)
    reclipModal.value.submitted = true  // switch to success state
    if (openId.value) getGroup(openId.value).then(d => { detail.value = d })
  } catch (e) {
    show(e.message || '操作失败', 'error')
  } finally {
    reclipSaving.value = false
  }
}

const importPreviewCount = computed(() => {
  const txt = groupModal.value?.importPaths || ''
  return txt.split('\n').map(p => p.trim()).filter(p => p.endsWith('.mp4')).length
})

async function load() {
  ;[groups.value, rooms.value] = await Promise.all([getGroups(), getRooms()])
  if (openId.value) {
    detail.value = await getGroup(openId.value)
  }
}

async function toggleDetail(id) {
  if (openId.value === id) {
    openId.value = null
    detail.value = null
    stopProgressPolling()
    return
  }
  openId.value = id
  detailLoading.value = true
  detail.value = null
  detail.value = await getGroup(id)
  detailLoading.value = false
  startProgressPolling()
}

function startProgressPolling() {
  stopProgressPolling()
  const poll = async () => {
    progressMap.value = await getProcessingProgress()
  }
  poll()
  progressTimer = setInterval(poll, 3000)
}

function stopProgressPolling() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
}

function formatEta(seconds) {
  if (seconds == null || seconds < 0) return ''
  if (seconds < 60) return `约 ${seconds}秒`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `约 ${m}分${s > 0 ? s + '秒' : ''}`
}

async function doMerge(g) {
  try {
    await mergeGroup(g.id)
    show('合并任务已提交', 'info')
    await load()
  } catch (e) {
    show(e.message || '合并失败', 'error')
  }
}

function openCreateGroupModal() {
  groupModal.value = {
    mode: 'create',
    room_id: rooms.value[0]?.id ?? '',
    label: '',
    wig_model: '',
    wig_color: '',
    importPaths: '',
  }
}

function openEditGroupModal(g) {
  groupModal.value = {
    mode: 'edit',
    id: g.id,
    room_id: g.room_id,
    label: g.label,
    wig_model: g.wig_model || '',
    wig_color: g.wig_color || '',
    importPaths: '',
  }
}

async function saveGroupModal() {
  const m = groupModal.value
  if (!m || !m.label.trim()) return
  groupModalSaving.value = true
  try {
    const body = { label: m.label.trim(), wig_model: m.wig_model.trim() || null, wig_color: m.wig_color.trim() || null }
    let groupId
    if (m.mode === 'create') {
      const created = await createGroup({ ...body, room_id: Number(m.room_id) })
      groupId = created.id
    } else {
      await updateGroup(m.id, body)
      groupId = m.id
    }
    if (m.importPaths?.trim()) {
      const paths = m.importPaths.split('\n').map(p => p.trim()).filter(Boolean)
      const result = await importGroupVideos(groupId, paths)
      show(`已导入 ${result.imported} 个视频${result.skipped.length ? `，${result.skipped.length} 个跳过` : ''}`, 'success')
    }
    groupModal.value = null
    await load()
  } catch (e) {
    show(e.message || '保存失败', 'error')
  } finally {
    groupModalSaving.value = false
  }
}

async function doDeleteGroup(g) {
  if (!confirm(`删除分组「${g.label}」？录像文件不会被删除，仅解除关联。`)) return
  try {
    await deleteGroup(g.id)
    if (openId.value === g.id) { openId.value = null; detail.value = null }
    await load()
    show('分组已删除', 'info')
  } catch (e) {
    show(e.message || '删除失败', 'error')
  }
}

function openCustomGroupModal() {
  customModal.value = { label: '', wig_model: '', wig_color: '' }
}

async function saveCustomModal() {
  const m = customModal.value
  if (!m || !m.label.trim()) return
  customModalSaving.value = true
  try {
    await createCustomGroup({ label: m.label.trim(), wig_model: m.wig_model.trim() || null, wig_color: m.wig_color.trim() || null })
    customModal.value = null
    show('自定义分组已创建', 'success')
    await load()
  } catch (e) {
    show(e.message || '创建失败', 'error')
  } finally {
    customModalSaving.value = false
  }
}

async function doUploadVideo(groupId, event) {
  const file = event.target.files?.[0]
  if (!file) return
  uploadingId.value = groupId
  try {
    await uploadCustomGroupVideo(groupId, file)
    show(`已上传 ${file.name}，正在处理…`, 'success')
    await load()
  } catch (e) {
    show(e.message || '上传失败', 'error')
  } finally {
    uploadingId.value = null
    event.target.value = ''
  }
}

async function doReassign(recordingId, newGroupId) {
  try {
    await reassignRecording(recordingId, newGroupId ? Number(newGroupId) : null)
    await load()
  } catch (e) {
    alert(e.message || '移动失败')
  }
}

onMounted(() => {
  load()
  ws = createWS((msg) => {
    if (msg.type === 'merged') {
      show('视频合并完成', 'success')
      load()
    } else if (['transcribed', 'clipped'].includes(msg.type)) {
      load()
      if (openId.value) getProcessingProgress().then(p => { progressMap.value = p })
    } else if (msg.type === 'clip_progress' && msg.recording_id != null) {
      progressMap.value = {
        ...progressMap.value,
        [msg.recording_id]: { pct: msg.pct, msg: msg.msg, eta_seconds: msg.eta_seconds, phase: msg.phase ?? '' }
      }
    }
  })
  // Poll every 15s for merge status updates
  const t = setInterval(load, 15000)
  onUnmounted(() => clearInterval(t))
})

onUnmounted(() => { ws?.close(); stopProgressPolling() })
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }
.toolbar-actions { display: flex; gap: 8px; }
.btn-primary { background: #fe2c55; color: #fff; border: none; padding: 7px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-primary:hover { background: #e0203d; }
.btn-custom { background: rgba(251,146,60,0.15); color: #fb923c; border: 1px solid rgba(251,146,60,0.4); padding: 7px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-custom:hover { background: rgba(251,146,60,0.25); }
.btn-edit { background: none; border: none; color: #555; cursor: pointer; font-size: 15px; padding: 0 4px; margin-left: 8px; }
.btn-edit:hover { color: #ccc; }
.btn-del { background: none; border: none; color: #555; cursor: pointer; font-size: 13px; padding: 0 4px; margin-left: 2px; }
.btn-del:hover { color: #fe2c55; }
.group-card-custom .btn-del { color: #aaa; }
.group-card-custom .btn-del:hover { color: #c0392b; }
.empty-tip { color: #444; text-align: center; padding: 60px; }
.groups-list { display: flex; flex-direction: column; gap: 12px; }
.group-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 18px; }
.group-card-custom { background: #f5f3ef; border: 2px solid #fb923c; color: #1a1a1a; }
.group-card-custom .group-label { color: #111; }
.group-card-custom .group-stats { color: #555; }
.group-card-custom .tag { background: #e8e4dc; color: #555; }
.group-card-custom .btn-sm { background: #e8e4dc; border-color: #ccc; color: #333; }
.group-card-custom .btn-sm:hover { background: #ddd; }
.group-card-custom .merge-error { color: #c0392b; }
.group-card-custom .detail-table th { color: #777; }
.group-card-custom .detail-table td { border-color: #e0dbd0; }
.group-card-custom .filename { color: #666; }
.group-card-custom .reassign-select { background: #f0ece4; border-color: #ccc; color: #333; }
.custom-upload-row { display: flex; align-items: center; gap: 8px; padding: 8px 0 0; }
.btn-upload-label { background: rgba(251,146,60,0.12); color: #c2540a; border: 1px solid rgba(251,146,60,0.4); padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.btn-upload-label:hover { background: rgba(251,146,60,0.22); }
.hidden-file-input { display: none; }
.uploading-hint { font-size: 12px; color: #fb923c; }
.group-header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.group-meta { flex: 1; }
.group-label { font-size: 16px; font-weight: 600; margin-bottom: 6px; }
.group-sub { display: flex; gap: 6px; flex-wrap: wrap; }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #2a2a2a; color: #999; }
.tag.color { background: rgba(251,191,36,0.12); color: #fbbf24; }
.tag.promo { background: rgba(254,44,85,0.12); color: #fe2c55; }
.group-stats { font-size: 13px; color: #666; white-space: nowrap; }
.stat-item { margin-right: 12px; }
.group-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.btn-action { background: #2a2a2a; border: 1px solid #444; color: #ccc; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; text-decoration: none; display: inline-block; }
.btn-action:hover:not(:disabled) { background: #333; color: #fff; }
.btn-action:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-action.purple { background: rgba(168,85,247,0.15); color: #c084fc; border-color: rgba(168,85,247,0.3); }
.btn-action.yellow { background: rgba(251,191,36,0.12); color: #fbbf24; border-color: transparent; }
.btn-action.teal { background: rgba(45,212,191,0.12); color: #2dd4bf; border-color: rgba(45,212,191,0.3); }
.btn-action.red { background: rgba(254,44,85,0.12); color: #fe2c55; border-color: rgba(254,44,85,0.3); }
.btn-action.orange { background: rgba(251,146,60,0.15); color: #c2540a; border-color: rgba(251,146,60,0.4); }
.btn-sm { background: #222; border: 1px solid #333; color: #888; padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.btn-sm:hover { background: #2a2a2a; color: #ccc; }
.merge-error { font-size: 12px; color: #fe2c55; margin-top: 8px; display: flex; align-items: center; gap: 8px; }
.btn-error-detail { background: none; border: 1px solid rgba(254,44,85,0.4); color: #fe2c55; border-radius: 4px; padding: 1px 7px; font-size: 11px; cursor: pointer; }
.btn-error-detail:hover { background: rgba(254,44,85,0.1); }
.modal-box { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 20px; max-width: 560px; width: 90%; }
.modal-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: #fe2c55; }
.error-pre { background: #111; border: 1px solid #2a2a2a; border-radius: 6px; padding: 12px; font-size: 11px; color: #f87171; white-space: pre-wrap; word-break: break-all; max-height: 300px; overflow-y: auto; margin: 0; }
.quality-issue-bar { display: flex; align-items: center; gap: 8px; margin-top: 10px; background: rgba(251,146,60,0.08); border: 1px solid rgba(251,146,60,0.3); border-radius: 8px; padding: 8px 12px; }
.quality-issue-icon { font-size: 14px; flex-shrink: 0; }
.quality-issue-text { font-size: 12px; color: #fb923c; flex: 1; line-height: 1.4; }
.detail-loading { text-align: center; color: #555; padding: 20px; }
.detail-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 16px; }
.detail-table th { text-align: left; padding: 8px 12px; color: #555; border-bottom: 1px solid #222; }
.detail-table td { padding: 10px 12px; border-bottom: 1px solid #1e1e1e; }
.filename { font-family: monospace; color: #888; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; text-decoration: none; display: inline-block; }
.badge.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge.yellow { background: rgba(251,191,36,0.12); color: #fbbf24; }
.badge.dim { background: #2a2a2a; color: #555; }
.badge.red { background: rgba(254,44,85,0.15); color: #fe2c55; }
.status-cell { min-width: 140px; }
.progress-wrap { display: flex; flex-direction: column; gap: 3px; }
.progress-label { display: flex; justify-content: space-between; font-size: 11px; }
.progress-msg { color: #aaa; }
.progress-pct { color: #ccc; font-weight: 600; }
.progress-bar-bg { height: 5px; background: #2a2a2a; border-radius: 3px; overflow: hidden; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #a855f7, #7c3aed); border-radius: 3px; transition: width 0.4s ease; }
.progress-eta { font-size: 10px; color: #666; }
.group-card-custom .progress-bar-bg { background: #ddd; }
.group-card-custom .progress-msg { color: #666; }
.group-card-custom .progress-pct { color: #333; }
.group-card-custom .progress-eta { color: #999; }
.empty { text-align: center; color: #444; padding: 20px; }
.reassign-select { background: #1a1a1a; border: 1px solid #333; color: #888; padding: 3px 6px; border-radius: 4px; font-size: 11px; cursor: pointer; max-width: 130px; }
.reassign-select:focus { outline: none; border-color: #555; }
.thumb-cell { width: 70px; padding: 6px 12px; }
.thumb-img { width: 60px; height: 34px; object-fit: cover; border-radius: 4px; display: block; }
.thumb-placeholder { width: 60px; height: 34px; background: #111; border-radius: 4px; }
/* Publish Modal */
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
.modal { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 24px; width: 480px; max-width: 92vw; }
.modal-header { display: flex; justify-content: space-between; align-items: center; font-size: 15px; font-weight: 600; margin-bottom: 20px; }
.modal-close { background: none; border: none; color: #666; font-size: 16px; cursor: pointer; padding: 0; }
.modal-close:hover { color: #ccc; }
.modal-loading { text-align: center; color: #666; padding: 30px 0; }
.modal-field { margin-bottom: 16px; }
.modal-field label { display: block; font-size: 12px; color: #888; margin-bottom: 6px; }
.field-hint { color: #555; margin-left: 4px; }
.modal-input { width: 100%; background: #111; border: 1px solid #333; color: #ccc; border-radius: 6px; padding: 8px 10px; font-size: 13px; box-sizing: border-box; resize: vertical; font-family: inherit; }
.modal-input:focus { outline: none; border-color: #555; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.import-preview { font-size: 11px; color: #34d399; margin-top: 4px; }
.modal-custom { background: #f5f3ef; border-color: #fb923c; color: #1a1a1a; }
.modal-custom .modal-header { color: #1a1a1a; }
.modal-custom .modal-field label { color: #555; }
.modal-custom .modal-input { background: #fff; border-color: #ccc; color: #1a1a1a; }
.modal-custom .modal-input:focus { border-color: #fb923c; }
.modal-custom .modal-close { color: #888; }
.published-tag { background: rgba(52,211,153,0.12); color: #34d399; }
.clip-done-row { display: inline-flex; align-items: center; gap: 4px; }
.badge-btn { font-size: 11px; padding: 2px 8px; border-radius: 10px; cursor: pointer; border: none; background: rgba(168,85,247,0.15); color: #c084fc; }
.badge-btn:hover { background: rgba(168,85,247,0.28); }
.badge-btn.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge-btn.orange { background: rgba(251,146,60,0.15); color: #fb923c; }
.badge-btn.orange:hover { background: rgba(251,146,60,0.28); }
.reclip-hint { font-size: 11px; color: #666; margin: -8px 0 12px; padding: 0 2px; }
.reclip-success { text-align: center; padding: 28px 16px 20px; }
.reclip-success-icon { font-size: 36px; color: #34d399; margin-bottom: 12px; }
.reclip-success-title { font-size: 16px; font-weight: 600; color: #ccc; margin-bottom: 8px; }
.reclip-success-sub { font-size: 13px; color: #666; line-height: 1.6; }
.preview-modal { background: #111; border: 1px solid #333; border-radius: 12px; width: min(860px, 94vw); max-height: 90vh; display: flex; flex-direction: column; overflow: hidden; }
.preview-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid #222; font-size: 13px; color: #aaa; gap: 12px; }
.preview-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: monospace; font-size: 12px; }
.preview-video { width: 100%; max-height: 70vh; background: #000; display: block; }
.preview-err { text-align: center; color: #fe2c55; padding: 20px; }
.preview-footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid #222; }
</style>
