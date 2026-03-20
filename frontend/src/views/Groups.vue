<template>
  <div>
    <div class="toolbar">
      <h2>分组管理</h2>
      <button class="btn-primary" @click="openCreateGroupModal">+ 新建分组</button>
    </div>

    <div v-if="groups.length === 0" class="empty-tip">
      暂无分组。录像完成转录和剪辑后，系统会自动按款式/颜色分组。
    </div>

    <div class="groups-list">
      <div v-for="g in groups" :key="g.id" class="group-card">
        <!-- Group header -->
        <div class="group-header">
          <div class="group-meta">
            <div class="group-label">{{ g.label }}</div>
            <div class="group-sub">
              <span class="tag">{{ g.room_name }}</span>
              <span class="tag" v-if="g.wig_model">{{ g.wig_model }}</span>
              <span class="tag color" v-if="g.wig_color">{{ g.wig_color }}</span>
            </div>
          </div>
          <div class="group-stats">
            <span class="stat-item">{{ g.ready_count }} / {{ g.clip_count }} 条剪辑</span>
            <button class="btn-edit" @click="openEditGroupModal(g)" title="编辑分组">✎</button>
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

        <!-- Merge status -->
        <div v-if="g.merge_status === -1" class="merge-error">合并失败，请重试</div>

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
                <th>剪辑</th>
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
                <td>
                  <a v-if="r.clipped === 2"
                     :href="`${apiBase}/api/recordings/${r.id}/clip`"
                     class="badge purple">剪辑</a>
                  <span v-else-if="r.clipped === 1" class="badge yellow">剪辑中</span>
                  <span v-else class="badge dim">—</span>
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
      <div class="modal-footer">
        <button class="btn-action" @click="groupModal = null">取消</button>
        <button class="btn-action purple" :disabled="groupModalSaving || !groupModal.label.trim()" @click="saveGroupModal">
          {{ groupModalSaving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>

</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getGroups, getGroup, getRooms, mergeGroup, createGroup, updateGroup, reassignRecording, createWS, getThumbnailUrl } from '../api.js'
import { useToast } from '../composables/toast.js'

const groups = ref([])
const rooms = ref([])
const openId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''
let ws = null

const { show } = useToast()

// Group create/edit modal: { mode: 'create'|'edit', id?, room_id, label, wig_model, wig_color }
const groupModal = ref(null)
const groupModalSaving = ref(false)

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
    return
  }
  openId.value = id
  detailLoading.value = true
  detail.value = null
  detail.value = await getGroup(id)
  detailLoading.value = false
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
  }
}

async function saveGroupModal() {
  const m = groupModal.value
  if (!m || !m.label.trim()) return
  groupModalSaving.value = true
  try {
    const body = { label: m.label.trim(), wig_model: m.wig_model.trim() || null, wig_color: m.wig_color.trim() || null }
    if (m.mode === 'create') {
      await createGroup({ ...body, room_id: Number(m.room_id) })
    } else {
      await updateGroup(m.id, body)
    }
    groupModal.value = null
    await load()
  } catch (e) {
    show(e.message || '保存失败', 'error')
  } finally {
    groupModalSaving.value = false
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
    }
  })
  // Poll every 15s for merge status updates
  const t = setInterval(load, 15000)
  onUnmounted(() => clearInterval(t))
})

onUnmounted(() => ws?.close())
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }
.btn-primary { background: #fe2c55; color: #fff; border: none; padding: 7px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn-primary:hover { background: #e0203d; }
.btn-edit { background: none; border: none; color: #555; cursor: pointer; font-size: 15px; padding: 0 4px; margin-left: 8px; }
.btn-edit:hover { color: #ccc; }
.empty-tip { color: #444; text-align: center; padding: 60px; }
.groups-list { display: flex; flex-direction: column; gap: 12px; }
.group-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 18px; }
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
.btn-sm { background: #222; border: 1px solid #333; color: #888; padding: 5px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.btn-sm:hover { background: #2a2a2a; color: #ccc; }
.merge-error { font-size: 12px; color: #fe2c55; margin-top: 8px; }
.detail-loading { text-align: center; color: #555; padding: 20px; }
.detail-table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 16px; }
.detail-table th { text-align: left; padding: 8px 12px; color: #555; border-bottom: 1px solid #222; }
.detail-table td { padding: 10px 12px; border-bottom: 1px solid #1e1e1e; }
.filename { font-family: monospace; color: #888; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; text-decoration: none; display: inline-block; }
.badge.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge.yellow { background: rgba(251,191,36,0.12); color: #fbbf24; }
.badge.dim { background: #2a2a2a; color: #555; }
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
</style>
