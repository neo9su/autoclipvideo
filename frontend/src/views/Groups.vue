<template>
  <div>
    <div class="toolbar">
      <h2>分组管理</h2>
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
          </div>
          <div class="group-actions">
            <template v-if="g.merge_status === 2">
              <a :href="`${apiBase}/api/groups/${g.id}/download`" class="btn-action purple">
                下载合并视频
              </a>
              <!-- Publish content generation -->
              <button v-if="g.publish_status === 1" class="btn-action teal" @click="openPublishModal(g)">
                查看发布文案
              </button>
              <button v-else class="btn-action" @click="doPreparePublish(g)">
                生成发布文案
              </button>
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
                <th>文件名</th>
                <th>内容摘要</th>
                <th>标签</th>
                <th>剪辑</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in detail.recordings" :key="r.id">
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
              </tr>
              <tr v-if="detail.recordings.length === 0">
                <td colspan="4" class="empty">此分组暂无录像</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- Publish Modal -->
  <div v-if="publishModal" class="modal-backdrop" @click.self="publishModal = null">
    <div class="modal">
      <div class="modal-header">
        <span>审核发布内容</span>
        <button class="modal-close" @click="publishModal = null">✕</button>
      </div>
      <div v-if="publishModal.loading" class="modal-loading">生成中，请稍候…</div>
      <template v-else>
        <div class="modal-field">
          <label>标题</label>
          <div class="modal-text">{{ publishModal.title }}</div>
        </div>
        <div class="modal-field">
          <label>文案</label>
          <div class="modal-text">{{ publishModal.caption }}</div>
        </div>
        <div class="modal-field">
          <label>话题标签</label>
          <div class="modal-tags">
            <span v-for="tag in publishModal.hashtags" :key="tag" class="tag">#{{ tag }}</span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn-action" @click="publishModal = null">关闭</button>
          <button class="btn-action teal" @click="doPreparePublish({ id: publishModal.groupId })">重新生成</button>
          <button class="btn-action purple" @click="copyPublishText(publishModal)">复制文案</button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getGroups, getGroup, mergeGroup, preparePublish, createWS } from '../api.js'

const groups = ref([])
const openId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : ''
let ws = null

// Publish content modal state
const publishModal = ref(null)  // { groupId, title, caption, hashtags, loading }

async function load() {
  groups.value = await getGroups()
  // Refresh open detail if any
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
    await load()
  } catch (e) {
    alert(e.message || '合并失败')
  }
}

async function doPreparePublish(g) {
  publishModal.value = { groupId: g.id, title: '', caption: '', hashtags: [], loading: true }
  try {
    const data = await preparePublish(g.id)
    publishModal.value = {
      groupId: g.id,
      title: data.title || '',
      caption: data.caption || '',
      hashtagsText: (data.hashtags || []).join(', '),
      loading: false,
    }
    await load()
  } catch (e) {
    alert(e.message || '生成内容失败')
    publishModal.value = null
  }
}

function openPublishModal(g) {
  publishModal.value = {
    groupId: g.id,
    title: g.post_title || '',
    caption: g.post_caption || '',
    hashtags: g.post_hashtags ? JSON.parse(g.post_hashtags) : [],
    loading: false,
  }
}

function copyPublishText(m) {
  const tags = (m.hashtags || []).map(t => `#${t}`).join(' ')
  const text = `${m.title}\n\n${m.caption}\n\n${tags}`
  navigator.clipboard.writeText(text)
}

onMounted(() => {
  load()
  ws = createWS((msg) => {
    if (['transcribed', 'clipped', 'merged'].includes(msg.type)) load()
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
.modal-text { background: #111; border: 1px solid #2a2a2a; border-radius: 6px; padding: 10px 12px; font-size: 13px; color: #ccc; line-height: 1.6; white-space: pre-wrap; }
.modal-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
</style>
