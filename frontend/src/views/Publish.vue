<template>
  <div class="publish-layout">
    <!-- Left: task list -->
    <div class="task-list-panel">
      <div class="panel-header">
        <h3>发布任务</h3>
        <button class="btn-primary" @click="showCreateModal = true">+ 创建任务</button>
      </div>
      <div class="filter-bar">
        <button v-for="s in statusFilters" :key="s.value"
          :class="['filter-btn', statusFilter === s.value && 'active']"
          @click="statusFilter = s.value; loadTasks()">
          {{ s.label }}
        </button>
      </div>
      <div class="task-items">
        <div v-if="!tasks.length" class="empty">暂无任务</div>
        <div v-for="t in tasks" :key="t.id"
          :class="['task-item', selectedTask?.id === t.id && 'selected']"
          @click="selectTask(t)">
          <div class="task-item-top">
            <span class="task-platform">{{ t.platform }}</span>
            <span :class="['badge', statusClass(t.status)]">{{ statusLabel(t.status) }}</span>
            <button v-if="['failed','publishing'].includes(t.status)"
              class="btn-xs btn-retry" @click.stop="retryTask(t.id)" title="重试">↺</button>
          </div>
          <div class="task-title">{{ t.title || '(无标题)' }}</div>
          <div class="task-meta">
            <span class="muted">{{ t.group_label }}</span>
            <span v-if="t.scheduled_at" class="countdown">{{ formatScheduled(t.scheduled_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Right: task detail -->
    <div class="task-detail-panel">
      <div v-if="selectedTask" class="detail">
        <div class="detail-header">
          <div>
            <h3>{{ selectedTask.title || '(无标题)' }}</h3>
            <div class="detail-sub">
              <span :class="['badge', statusClass(selectedTask.status)]">{{ statusLabel(selectedTask.status) }}</span>
              <span class="muted">· {{ selectedTask.platform }} · 分组: {{ selectedTask.group_label }}</span>
            </div>
          </div>
          <div class="detail-actions">
            <button v-if="['failed','publishing'].includes(selectedTask.status)" class="btn-primary" @click="retryTask(selectedTask.id)">重试</button>
            <button v-if="['pending','scheduled'].includes(selectedTask.status)" class="btn-danger" @click="cancelTask(selectedTask.id)">取消</button>
          </div>
        </div>
        <div v-if="selectedTask.error_msg" class="error-box">{{ selectedTask.error_msg }}</div>
        <div v-if="progressLog[selectedTask.id]?.length" class="progress-log">
          <div class="progress-log-title">发布进度</div>
          <div v-for="(line, i) in progressLog[selectedTask.id]" :key="i"
               :class="['progress-line', line.startsWith('✓') ? 'progress-ok' : '']">
            {{ line }}
          </div>
        </div>
        <div class="detail-fields">
          <div class="field">
            <label>标题</label>
            <div>{{ selectedTask.title || '—' }}</div>
          </div>
          <div class="field">
            <label>描述</label>
            <div class="desc-text">{{ selectedTask.description || '—' }}</div>
          </div>
          <div class="field">
            <label>标签</label>
            <div class="tags-row">
              <span v-for="tag in splitTags(selectedTask.tags)" :key="tag" class="tag">{{ tag }}</span>
            </div>
          </div>
          <div class="field">
            <label>小黄车商品</label>
            <div>{{ taskProductNames(selectedTask) || '未挂商品' }}</div>
          </div>
          <div class="field">
            <label>账号</label>
            <div>{{ selectedTask.account_name || '未指定' }}</div>
          </div>
          <div class="field" v-if="selectedTask.scheduled_at">
            <label>定时发布</label>
            <div>{{ selectedTask.scheduled_at }}</div>
          </div>
          <div class="field" v-if="selectedTask.published_at">
            <label>发布时间</label>
            <div>{{ selectedTask.published_at }}</div>
          </div>
        </div>
      </div>
      <div v-else class="empty-detail">← 选择左侧任务查看详情</div>
    </div>

    <!-- Create Task Modal -->
    <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false">
      <div class="modal">
        <h3>创建发布任务</h3>

        <label>选择分组 *（仅显示已合并的）</label>
        <div class="group-list">
          <div v-if="!mergedGroups.length" class="muted" style="padding:8px;font-size:12px">暂无已合并分组</div>
          <div v-for="g in mergedGroups" :key="g.id"
            :class="['group-item', newTask.group_id === g.id && 'group-item-selected']"
            @click="newTask.group_id = g.id; onGroupSelect()">
            <div class="group-item-name">{{ g.label }}</div>
            <div class="group-item-sub">{{ g.wig_model }} · {{ g.wig_color }}</div>
            <span v-if="publishedGroupIds.has(g.id)" class="group-published-badge">✓ 已发布</span>
          </div>
        </div>

        <label>平台 *</label>
        <select v-model="newTask.platform" class="input">
          <option value="douyin">抖音</option>
          <option value="kuaishou">快手</option>
          <option value="xiaohongshu">小红书</option>
          <option value="bilibili">B站</option>
        </select>

        <label>发布账号</label>
        <select v-model="newTask.account_id" class="input">
          <option value="">立即发布（不指定账号）</option>
          <option v-for="a in accounts" :key="a.id" :value="a.id">
            {{ a.account_name }} ({{ a.platform }})
          </option>
        </select>

        <label>发布时间</label>
        <div class="schedule-row">
          <label class="radio-label">
            <input type="radio" v-model="scheduleMode" value="now" /> 立即发布
          </label>
          <label class="radio-label">
            <input type="radio" v-model="scheduleMode" value="later" /> 定时发布
          </label>
        </div>
        <div v-if="scheduleMode === 'later'" class="schedule-later-row">
          <div class="schedule-field">
            <span class="schedule-label">每天</span>
            <input v-model="scheduleTime" type="time" class="input input-time" />
            <span class="schedule-label">开始</span>
          </div>
          <div class="schedule-field">
            <span class="schedule-label">间隔</span>
            <input v-model.number="scheduleInterval" type="number" min="1" class="input input-interval" placeholder="60" />
            <span class="schedule-label">分钟发布一篇</span>
          </div>
          <div class="schedule-preview">下次发布: {{ schedulePreview }}</div>
        </div>

        <label>标题</label>
        <div class="input-with-ai">
          <input v-model="newTask.title" class="input" placeholder="最多25字" maxlength="30" />
          <button class="btn-ai" @click="generateMeta" :disabled="!newTask.group_id || generating" title="AI生成">
            {{ generating ? '生成中...' : 'AI生成' }}
          </button>
        </div>

        <label>描述</label>
        <textarea v-model="newTask.description" class="textarea" rows="4" placeholder="100-200字，含卖点和互动引导"></textarea>

        <label>标签（逗号分隔，#格式）</label>
        <input v-model="newTask.tags" class="input" placeholder="#假发,#卷发,#变身" />

        <label>小黄车商品（可多选）</label>
        <div class="product-multi">
          <div class="product-multi-list">
            <label v-for="p in products" :key="p.id" class="product-check-item">
              <input type="checkbox" :value="p.id" v-model="newTask.product_ids" />
              <span>{{ p.product_name }}</span>
            </label>
            <div v-if="!products.length" class="muted" style="font-size:12px;padding:6px 0">暂无商品</div>
          </div>
          <button class="btn-secondary btn-sm" style="margin-top:6px" @click="autoMatchProduct" :disabled="!newTask.group_id">自动匹配</button>
        </div>
        <div v-if="matchedProduct" class="match-hint">建议: {{ matchedProduct.product_name }} ({{ matchedProduct.keywords }})</div>

        <div class="modal-actions">
          <button class="btn-secondary" @click="showCreateModal = false">取消</button>
          <button class="btn-primary" @click="submitCreate" :disabled="!newTask.group_id || !newTask.platform">发布</button>
        </div>
      </div>
    </div>

    <!-- Accounts management panel (collapsible) -->
    <div class="accounts-panel">
      <div class="accounts-header" @click="showAccounts = !showAccounts">
        <span>账号管理</span>
        <span>{{ showAccounts ? '▲' : '▼' }}</span>
      </div>
      <div v-if="showAccounts" class="accounts-body">
        <div v-for="a in accounts" :key="a.id" class="account-row">
          <span class="acc-platform">{{ a.platform }}</span>
          <span>{{ a.account_name }}</span>
          <span :class="['badge', a.cookie_file ? 'badge-green' : 'badge-gray']">
            {{ a.cookie_file ? '已登录' : '未登录' }}
          </span>
          <button class="btn-xs" @click="loginAccount(a.id)">登录</button>
          <button class="btn-xs btn-danger" @click="deleteAccount(a.id)">删除</button>
        </div>
        <div class="add-account">
          <select v-model="newAccount.platform" class="input-sm">
            <option value="douyin">抖音</option>
            <option value="kuaishou">快手</option>
          </select>
          <input v-model="newAccount.account_name" class="input-sm" placeholder="账号名" />
          <button class="btn-sm btn-primary" @click="addAccount">添加</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  getGroups, getPublishTasks, createPublishTask, retryPublishTask, cancelPublishTask,
  getProducts, getPublishAccounts, createPublishAccount, deletePublishAccount, loginPublishAccount,
  generatePublishMeta, matchGroupProduct, createWS,
} from '../api.js'
import { useToast } from '../composables/toast.js'

const { showToast } = useToast()

const tasks = ref([])
const selectedTask = ref(null)
const showCreateModal = ref(false)
const statusFilter = ref('')
const mergedGroups = ref([])
const accounts = ref([])
const products = ref([])
const generating = ref(false)
const matchedProduct = ref(null)
const scheduleMode = ref('now')
const progressLog = ref({})   // task_id → string[]
let ws = null
const scheduleTime = ref('10:00')
const scheduleInterval = ref(60)
const showAccounts = ref(false)

const publishedGroupIds = computed(() =>
  new Set(tasks.value.filter(t => t.status === 'done').map(t => t.group_id))
)

// Compute next scheduled_at from scheduleTime
const schedulePreview = computed(() => {
  if (!scheduleTime.value) return ''
  const [h, m] = scheduleTime.value.split(':').map(Number)
  const now = new Date()
  const t = new Date(now)
  t.setHours(h, m, 0, 0)
  if (t <= now) t.setDate(t.getDate() + 1)
  return t.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
})

function computeScheduledAt() {
  if (!scheduleTime.value) return null
  const [h, m] = scheduleTime.value.split(':').map(Number)
  const now = new Date()
  const t = new Date(now)
  t.setHours(h, m, 0, 0)
  if (t <= now) t.setDate(t.getDate() + 1)
  return t.toISOString().slice(0, 16)  // yyyy-MM-ddTHH:mm
}

function taskProductNames(task) {
  if (!task) return ''
  if (task.product_ids) {
    const ids = String(task.product_ids).split(',').map(Number).filter(Boolean)
    return ids.map(id => products.value.find(p => p.id === id)?.product_name).filter(Boolean).join('、')
  }
  return task.product_name || ''
}

const statusFilters = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待发布' },
  { value: 'scheduled', label: '定时' },
  { value: 'publishing', label: '发布中' },
  { value: 'done', label: '已完成' },
  { value: 'failed', label: '失败' },
]

const newTask = ref({ group_id: '', platform: 'douyin', account_id: '', title: '', description: '', tags: '', product_ids: [] })
const newAccount = ref({ platform: 'douyin', account_name: '' })

function statusLabel(s) {
  return { pending: '待发布', scheduled: '定时', publishing: '发布中', done: '已完成', failed: '失败' }[s] || s
}
function statusClass(s) {
  return { pending: 'badge-yellow', scheduled: 'badge-blue', publishing: 'badge-orange', done: 'badge-green', failed: 'badge-red' }[s] || ''
}
function splitTags(tags) {
  if (!tags) return []
  return tags.split(',').map(s => s.trim()).filter(Boolean)
}
function formatScheduled(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = d - now
  if (diff < 0) return '已过期'
  const h = Math.floor(diff / 3600000)
  const m = Math.floor((diff % 3600000) / 60000)
  if (h > 0) return `${h}h${m}m后`
  return `${m}m后`
}

async function loadTasks() {
  tasks.value = await getPublishTasks(statusFilter.value || null)
}

async function selectTask(t) {
  selectedTask.value = t
}

async function retryTask(id) {
  try {
    await retryPublishTask(id)
    await loadTasks()
    showToast('已重新加入队列', 'success')
  } catch (e) {
    showToast('重试失败: ' + e.message, 'error')
  }
}

async function cancelTask(id) {
  if (!confirm('确认取消此任务？')) return
  try {
    await cancelPublishTask(id)
    selectedTask.value = null
    await loadTasks()
    showToast('任务已取消', 'success')
  } catch (e) {
    showToast('取消失败: ' + e.message, 'error')
  }
}

async function onGroupSelect() {
  matchedProduct.value = null
  newTask.value.product_ids = []
}

async function generateMeta() {
  if (!newTask.value.group_id) return
  generating.value = true
  try {
    const meta = await generatePublishMeta(newTask.value.group_id)
    if (meta) {
      newTask.value.title = meta.title || newTask.value.title
      newTask.value.description = meta.description || newTask.value.description
      newTask.value.tags = meta.tags || newTask.value.tags
      showToast('AI元数据已生成', 'success')
    }
  } catch (e) {
    showToast('生成失败: ' + e.message, 'error')
  } finally {
    generating.value = false
  }
}

async function autoMatchProduct() {
  if (!newTask.value.group_id) return
  try {
    const result = await matchGroupProduct(newTask.value.group_id)
    if (result.product) {
      matchedProduct.value = result.product
      if (!newTask.value.product_ids.includes(result.product.id)) {
        newTask.value.product_ids.push(result.product.id)
      }
      showToast(`自动匹配: ${result.product.product_name}`, 'success')
    } else {
      showToast('未找到匹配商品', 'info')
    }
  } catch (e) {
    showToast('匹配失败: ' + e.message, 'error')
  }
}

async function submitCreate() {
  const body = {
    group_id: newTask.value.group_id,
    platform: newTask.value.platform,
    account_id: newTask.value.account_id || null,
    scheduled_at: scheduleMode.value === 'later' ? computeScheduledAt() : null,
    title: newTask.value.title || null,
    description: newTask.value.description || null,
    tags: newTask.value.tags || null,
    product_ids: newTask.value.product_ids.length ? newTask.value.product_ids : null,
    auto_meta: false,
  }
  try {
    await createPublishTask(body)
    // Advance schedule time by interval for next task
    if (scheduleMode.value === 'later' && scheduleInterval.value) {
      const [h, m] = scheduleTime.value.split(':').map(Number)
      const next = new Date(0, 0, 0, h, m + scheduleInterval.value)
      scheduleTime.value = `${String(next.getHours()).padStart(2,'0')}:${String(next.getMinutes()).padStart(2,'0')}`
    }
    showCreateModal.value = false
    const defaultAcc = accounts.value.find(a => a.account_name === '颜遇生活')
    newTask.value = { group_id: '', platform: 'douyin', account_id: defaultAcc?.id || '', title: '', description: '', tags: '', product_ids: [] }
    matchedProduct.value = null
    await loadTasks()
    showToast('任务已创建', 'success')
  } catch (e) {
    showToast('创建失败: ' + e.message, 'error')
  }
}

async function addAccount() {
  if (!newAccount.value.account_name) return
  try {
    await createPublishAccount(newAccount.value)
    newAccount.value = { platform: 'douyin', account_name: '' }
    accounts.value = await getPublishAccounts()
    showToast('账号已添加', 'success')
  } catch (e) {
    showToast('添加失败: ' + e.message, 'error')
  }
}

async function deleteAccount(id) {
  if (!confirm('确认删除此账号？')) return
  try {
    await deletePublishAccount(id)
    accounts.value = await getPublishAccounts()
    showToast('已删除', 'success')
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error')
  }
}

async function loginAccount(id) {
  try {
    await loginPublishAccount(id)
    showToast('浏览器已启动，请手动扫码登录', 'info')
  } catch (e) {
    showToast('启动失败: ' + e.message, 'error')
  }
}

onMounted(async () => {
  await loadTasks()
  const groups = await getGroups()
  mergedGroups.value = groups.filter(g => g.merge_status === 2)
  accounts.value = await getPublishAccounts()
  const defaultAccount = accounts.value.find(a => a.account_name === '颜遇生活')
  if (defaultAccount) newTask.value.account_id = defaultAccount.id
  products.value = await getProducts()
  ws = createWS((msg) => {
    if (msg.type === 'publish_task_update') {
      loadTasks()
      if (selectedTask.value?.id === msg.task_id) {
        selectedTask.value = { ...selectedTask.value, status: msg.status, error_msg: msg.error_msg }
      }
    } else if (msg.type === 'publish_progress') {
      const id = msg.task_id
      if (!progressLog.value[id]) progressLog.value[id] = []
      progressLog.value[id].push(msg.message)
    }
  })
})

onUnmounted(() => ws?.close())
</script>

<style scoped>
.publish-layout { display: flex; gap: 20px; min-height: 600px; flex-direction: column; }
@media (min-width: 900px) { .publish-layout { flex-direction: row; } }

.task-list-panel { width: 100%; max-width: 320px; flex-shrink: 0; }
.panel-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.panel-header h3 { font-size: 15px; font-weight: 600; }
.filter-bar { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 12px; }
.filter-btn { background: #1e1e1e; border: 1px solid #333; color: #999; border-radius: 4px; padding: 3px 10px; cursor: pointer; font-size: 11px; }
.filter-btn.active { background: #fe2c55; border-color: #fe2c55; color: #fff; }

.task-items { display: flex; flex-direction: column; gap: 6px; }
.task-item { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 12px; cursor: pointer; }
.task-item:hover { border-color: #444; }
.task-item.selected { border-color: #fe2c55; }
.task-item-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.task-platform { font-size: 11px; color: #888; }
.task-title { font-size: 13px; font-weight: 500; margin-bottom: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.task-meta { display: flex; justify-content: space-between; font-size: 11px; }
.countdown { color: #f59e0b; }

.task-detail-panel { flex: 1; }
.detail { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; padding: 20px; }
.detail-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.detail-header h3 { font-size: 16px; font-weight: 600; margin-bottom: 6px; }
.detail-sub { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.detail-actions { display: flex; gap: 8px; }
.error-box { background: rgba(254,44,85,0.1); border: 1px solid rgba(254,44,85,0.3); border-radius: 6px; padding: 10px; font-size: 12px; color: #fe2c55; margin-bottom: 16px; }
.detail-fields { display: flex; flex-direction: column; gap: 12px; }
.field label { font-size: 11px; color: #888; margin-bottom: 3px; display: block; }
.field { font-size: 13px; }
.desc-text { line-height: 1.6; color: #ccc; }
.tags-row { display: flex; gap: 4px; flex-wrap: wrap; }
.tag { background: #2a2a2a; border: 1px solid #444; border-radius: 4px; padding: 2px 6px; font-size: 11px; }

.empty { text-align: center; color: #666; padding: 40px; }
.empty-detail { display: flex; align-items: center; justify-content: center; height: 200px; color: #555; font-size: 14px; }

.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 100; display: flex; align-items: center; justify-content: center; overflow-y: auto; }
.modal { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 24px; width: 480px; max-width: 95vw; max-height: 90vh; overflow-y: auto; }
.modal h3 { font-size: 16px; margin-bottom: 16px; }
label { display: block; font-size: 12px; color: #888; margin: 12px 0 4px; }
.input { width: 100%; background: #111; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 8px 12px; font-size: 13px; }
.textarea { width: 100%; background: #111; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 8px 12px; font-size: 13px; resize: vertical; }
.input-with-ai { display: flex; gap: 8px; }
.input-with-ai .input { flex: 1; }
.btn-ai { background: #1d4ed8; color: #fff; border: none; border-radius: 6px; padding: 8px 12px; cursor: pointer; font-size: 12px; white-space: nowrap; }
.btn-ai:disabled { opacity: 0.5; cursor: not-allowed; }
.product-row { display: flex; gap: 8px; align-items: center; }
.product-row .input { flex: 1; }
.match-hint { font-size: 11px; color: #34d399; margin-top: 4px; }
.schedule-row { display: flex; gap: 16px; margin: 8px 0; }
.radio-label { display: flex; align-items: center; gap: 4px; font-size: 13px; color: #ccc; cursor: pointer; }
.schedule-later-row { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.schedule-field { display: flex; align-items: center; gap: 6px; }
.schedule-label { font-size: 13px; color: #ccc; white-space: nowrap; }
.input-time { width: 110px; }
.input-interval { width: 80px; }
.schedule-preview { font-size: 11px; color: #f59e0b; }
.group-list { background: #111; border: 1px solid #333; border-radius: 6px; max-height: 180px; overflow-y: auto; }
.group-item { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #1e1e1e; position: relative; transition: background 0.15s; }
.group-item:last-child { border-bottom: none; }
.group-item:hover { background: #1a1a1a; }
.group-item-selected { background: rgba(254,44,85,0.08); border-left: 2px solid #fe2c55; }
.group-item-name { font-size: 13px; color: #e0e0e0; }
.group-item-sub { font-size: 11px; color: #666; margin-top: 2px; }
.group-published-badge { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); font-size: 11px; color: #34d399; font-weight: 600; }

.product-multi { display: flex; flex-direction: column; }
.product-multi-list { background: #111; border: 1px solid #333; border-radius: 6px; padding: 8px 10px; max-height: 160px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.product-check-item { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #e0e0e0; cursor: pointer; }
.product-check-item input[type=checkbox] { accent-color: #fe2c55; width: 14px; height: 14px; cursor: pointer; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }

.btn-primary { background: #fe2c55; color: #fff; border: none; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-sm { padding: 5px 12px; font-size: 12px; }
.btn-danger { background: transparent; color: #fe2c55; border: 1px solid #fe2c55; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-xs { background: #2a2a2a; color: #ccc; border: 1px solid #444; border-radius: 4px; padding: 3px 8px; cursor: pointer; font-size: 11px; margin-right: 4px; }
.btn-xs.btn-danger { color: #fe2c55; border-color: #fe2c55; }
.btn-xs.btn-retry { color: #60a5fa; border-color: #60a5fa; padding: 2px 6px; margin-left: auto; }

.badge { border-radius: 4px; padding: 2px 8px; font-size: 11px; }
.badge-green { background: rgba(52,211,153,0.15); color: #34d399; }
.badge-gray { background: #2a2a2a; color: #666; }
.badge-yellow { background: rgba(245,158,11,0.15); color: #f59e0b; }
.badge-blue { background: rgba(59,130,246,0.15); color: #60a5fa; }
.badge-orange { background: rgba(249,115,22,0.15); color: #fb923c; }
.badge-red { background: rgba(254,44,85,0.15); color: #fe2c55; }
.muted { color: #666; }

.progress-log { background: #111; border: 1px solid #2a2a2a; border-radius: 8px; padding: 12px 14px; margin-bottom: 16px; }
.progress-log-title { font-size: 11px; color: #888; margin-bottom: 8px; }
.progress-line { font-size: 12px; color: #aaa; padding: 2px 0; line-height: 1.5; }
.progress-line::before { content: '› '; color: #555; }
.progress-ok { color: #34d399; }
.progress-ok::before { content: ''; }

.accounts-panel { margin-top: 20px; background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px; }
.accounts-header { display: flex; justify-content: space-between; padding: 12px 16px; cursor: pointer; font-size: 14px; font-weight: 500; }
.accounts-body { padding: 12px 16px; display: flex; flex-direction: column; gap: 8px; }
.account-row { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.acc-platform { font-size: 11px; background: #2a2a2a; border-radius: 3px; padding: 1px 6px; color: #888; }
.add-account { display: flex; gap: 8px; margin-top: 8px; padding-top: 8px; border-top: 1px solid #2a2a2a; }
.input-sm { background: #111; border: 1px solid #333; color: #e0e0e0; border-radius: 5px; padding: 5px 8px; font-size: 12px; }
</style>
