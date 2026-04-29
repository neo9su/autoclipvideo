<template>
  <div class="publish-layout">
    <!-- Left: task list -->
    <div class="task-list-panel">
      <div class="panel-header">
        <h3>发布任务</h3>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn-secondary" @click="openBatchModal">批量排期</button>
          <button class="btn-warn-sm" @click="doBulkCancel" title="取消所有待发/定时任务">批量取消</button>
          <button class="btn-primary" @click="showCreateModal = true">+ 创建任务</button>
        </div>
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
            <span v-if="t.no_cart" class="badge badge-no-cart">无车</span>
            <button v-if="['failed','publishing'].includes(t.status)"
              class="btn-xs btn-retry" @click.stop="retryTask(t.id)" title="重试">↺</button>
            <button v-if="t.status === 'scheduled' && isExpired(t.scheduled_at)"
              class="btn-xs btn-retry" @click.stop="openReschedule(t)" title="重新排期">↻</button>
            <button v-if="t.status === 'failed'"
              class="btn-xs btn-danger btn-del-failed" @click.stop="deleteFailedTask(t.id)" title="删除">×</button>
          </div>
          <div class="task-title">{{ t.title || '(无标题)' }}</div>
          <div class="task-meta">
            <span class="muted"><span v-if="t.room_name" class="task-room-tag">{{ t.room_name }}</span>{{ t.group_label }}</span>
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
            <button v-if="selectedTask.status === 'scheduled' && isExpired(selectedTask.scheduled_at)" class="btn-warning" @click="openReschedule(selectedTask)">重新排期</button>
            <button class="btn-secondary" @click="regenMeta(selectedTask.id)" :disabled="regenning" title="重新生成标题和文案">{{ regenning ? '生成中…' : '重生成文案' }}</button>
            <button v-if="selectedTask.status === 'failed'" class="btn-danger" @click="deleteFailedTask(selectedTask.id)">删除</button>
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
            <div v-if="selectedTask.no_cart" class="no-cart-hint" style="margin:0">无车发布</div>
            <div v-else>{{ taskProductNames(selectedTask) || '未挂商品' }}</div>
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

        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <label style="margin:0">选择分组 *（仅显示已合并的）</label>
          <button class="btn-xs" @click="refreshGroups" :disabled="groupsRefreshing" style="font-size:11px">
            {{ groupsRefreshing ? '…' : '↻ 刷新' }}
          </button>
        </div>
        <div class="room-filter-chips">
          <button :class="['room-chip', roomFilter === 0 && 'active']" @click="roomFilter = 0; newTask.group_id = ''; newTask.product_ids = []">全部</button>
          <button v-for="r in rooms" :key="r.id"
            :class="['room-chip', roomFilter === r.id && 'active']"
            @click="roomFilter = r.id; newTask.group_id = ''; newTask.product_ids = []">{{ r.name }}</button>
        </div>
        <div class="group-list">
          <div v-if="!filteredGroups.length" class="muted" style="padding:8px;font-size:12px">暂无已合并分组</div>
          <div v-for="g in filteredGroups" :key="g.id"
            :class="['group-item', newTask.group_id === g.id && 'group-item-selected', g.is_custom && 'group-item-custom']"
            @click="newTask.group_id = g.id; onGroupSelect()">
            <div class="group-item-name">{{ g.label }}</div>
            <div class="group-item-sub">
              <span v-if="g.room_name" class="group-room-tag">{{ g.room_name }}</span>{{ g.wig_model }} · {{ g.wig_color }}
              <span v-if="g.director_status === 2" class="vbadge vbadge-director">🎬</span>
              <span v-if="g.classic_status === 2" class="vbadge vbadge-classic">📹</span>
              <span v-if="g.creative_status === 2" class="vbadge vbadge-creative">✍️</span>
            </div>
            <span v-if="publishedGroupIds.has(g.id)" class="group-published-badge">✓ 已发布</span>
            <div class="group-item-actions" @click.stop>
              <button class="gact-btn" title="预览视频" @click="previewGroup = g">▶</button>
              <button class="gact-btn gact-orange" title="重新剪辑" @click="openReclipModal(g)">↺ 重剪</button>
              <button class="gact-btn gact-red" title="删除分组" @click="confirmDeleteGroup(g)">✕</button>
            </div>
          </div>
        </div>

        <!-- Version selector: shown when selected group has both versions -->
        <template v-if="selectedGroup && ((selectedGroup.classic_status === 2 ? 1 : 0) + (selectedGroup.director_status === 2 ? 1 : 0) + (selectedGroup.creative_status === 2 ? 1 : 0)) >= 2">
          <label>发布版本</label>
          <div class="version-switcher">
            <div :class="['vsw-option', selectedPublishVersion === 'director' && 'vsw-active']"
                 @click="setPublishVersion('director')">
              <span class="vsw-label">🎬 导演版</span>
              <span class="vsw-preview-btn" @click.stop="previewGroup = selectedGroup; previewVersion = 'director'">▶ 预览</span>
            </div>
            <div :class="['vsw-option', selectedPublishVersion === 'classic' && 'vsw-active']"
                 @click="setPublishVersion('classic')">
              <span class="vsw-label">📹 经典版</span>
              <span class="vsw-preview-btn" @click.stop="previewGroup = selectedGroup; previewVersion = 'classic'">▶ 预览</span>
            </div>
            <div v-if="selectedGroup && selectedGroup.creative_status === 2"
                 :class="['vsw-option', selectedPublishVersion === 'creative' && 'vsw-active']"
                 @click="setPublishVersion('creative')">
              <span class="vsw-label">✍️ 自编版</span>
              <span class="vsw-preview-btn" @click.stop="previewGroup = selectedGroup; previewVersion = 'creative'">▶ 预览</span>
            </div>
          </div>
        </template>

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

        <!-- AI方案选择器 -->
        <div v-if="metaSchemes.length" class="scheme-picker">
          <div class="scheme-picker-label">选择文案方案：</div>
          <div class="scheme-tabs">
            <button
              v-for="s in metaSchemes" :key="s.type"
              :class="['scheme-tab', selectedScheme === s.type && 'scheme-tab-active']"
              @click="applyScheme(s)"
            >{{ s.type }}</button>
          </div>
          <div v-if="selectedScheme" class="scheme-preview">
            <div class="scheme-preview-title">{{ currentScheme?.title }}</div>
            <div class="scheme-preview-desc">{{ currentScheme?.description }}</div>
          </div>
        </div>

        <label>描述</label>
        <textarea v-model="newTask.description" class="textarea" rows="4" placeholder="100-200字，含卖点和互动引导"></textarea>

        <label>标签（逗号分隔，#格式）</label>
        <input v-model="newTask.tags" class="input" placeholder="#假发,#卷发,#变身" />

        <!-- 无车发布开关 -->
        <div class="no-cart-row">
          <button :class="['no-cart-btn', newTask.no_cart ? 'no-cart-btn-on' : 'no-cart-btn-off']"
            @click="newTask.no_cart = !newTask.no_cart; if(newTask.no_cart) newTask.product_ids = []">
            {{ newTask.no_cart ? '✓ 无车发布（不挂商品）' : '挂小黄车商品' }}
          </button>
        </div>

        <!-- 商品选择（仅有车时显示） -->
        <template v-if="!newTask.no_cart">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px">
            <label style="margin:0">
              小黄车商品（可多选）
              <span v-if="selectedGroupRoomId" class="muted" style="font-weight:normal">· 已按直播间筛选</span>
            </label>
            <button v-if="cartFilteredProducts.length" class="btn-xs" @click="toggleAllProducts">
              {{ newTask.product_ids.length === cartFilteredProducts.length ? '取消全选' : '全选' }}
            </button>
          </div>
          <input
            v-model="cartSearch"
            class="input"
            style="margin:6px 0 4px;padding:5px 10px;font-size:12px"
            placeholder="搜索商品名/关键词…"
          />
          <div class="product-multi">
            <div class="product-multi-list">
              <label v-for="p in cartFilteredProducts" :key="p.id" class="product-check-item">
                <input type="checkbox" :value="p.id" v-model="newTask.product_ids" />
                <span v-if="p.room_name" class="product-room-tag">{{ p.room_name }}</span>
                <span>{{ p.product_name }}</span>
              </label>
              <div v-if="!cartFilteredProducts.length" class="muted" style="font-size:12px;padding:6px 0">暂无商品</div>
            </div>
            <button class="btn-secondary btn-sm" style="margin-top:6px" @click="autoMatchProduct" :disabled="!newTask.group_id">自动匹配</button>
          </div>
          <div v-if="matchedProduct" class="match-hint">建议: {{ matchedProduct.product_name }} ({{ matchedProduct.keywords }})</div>
        </template>

        <div class="modal-actions">
          <button class="btn-secondary" @click="showCreateModal = false">取消</button>
          <button class="btn-primary" @click="submitCreate" :disabled="!newTask.group_id || !newTask.platform">发布</button>
        </div>
      </div>
    </div>

    <!-- Video preview modal -->
    <div v-if="previewGroup" class="preview-overlay" @click.self="previewGroup = null">
      <div class="preview-modal">
        <div class="preview-header">
          <span>{{ previewGroup.label }}</span>
          <div v-if="previewGroup.classic_status === 2 && previewGroup.director_status === 2" class="preview-tabs">
            <button :class="['ptab', previewVersion === 'director' && 'ptab-active']" @click="previewVersion = 'director'">🎬 导演版</button>
            <button :class="['ptab', previewVersion === 'classic' && 'ptab-active']" @click="previewVersion = 'classic'">📹 经典版</button>
          </div>
          <button class="preview-close" @click="previewGroup = null">✕</button>
        </div>
        <video class="preview-video" :src="previewVideoUrl" :key="previewVersion" controls autoplay playsinline></video>
      </div>
    </div>

    <!-- Reclip modal -->
    <div v-if="reclipModal" class="preview-overlay" @click.self="!reclipModal.saving && (reclipModal = null)">
      <div class="reclip-modal">
        <template v-if="reclipModal.submitted">
          <div style="text-align:center;padding:20px 0">
            <div style="font-size:32px;margin-bottom:8px">✓</div>
            <div style="font-size:15px;font-weight:600;margin-bottom:6px">重剪已加入队列</div>
            <div style="font-size:12px;color:#999">{{ reclipModal.feedback.trim() ? 'AI将根据反馈调整片段策略' : '将使用不同片段重新生成' }}</div>
          </div>
          <button class="btn-primary" style="width:100%;margin-top:8px" @click="reclipModal = null">知道了</button>
        </template>
        <template v-else>
          <div style="font-size:14px;font-weight:600;margin-bottom:12px">重新剪辑「{{ reclipModal.group.label }}」</div>
          <label style="font-size:12px;color:#999;display:block;margin-bottom:6px">反馈意见（可选）</label>
          <textarea v-model="reclipModal.feedback" class="textarea" rows="3" placeholder="如：片段太短，缺少试戴环节，想要更多互动内容..."></textarea>
          <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
            <button class="btn-secondary" @click="reclipModal = null">取消</button>
            <button class="btn-primary" :disabled="reclipModal.saving" @click="doReclip">
              {{ reclipModal.saving ? '提交中...' : '确认重剪' }}
            </button>
          </div>
        </template>
      </div>
    </div>

    <!-- Reschedule modal -->
    <div v-if="showRescheduleModal" class="modal-overlay" @click.self="showRescheduleModal = false">
      <div class="modal" style="max-width:360px">
        <h3>重新排期</h3>
        <p class="muted" style="font-size:13px;margin:4px 0 12px">为「{{ rescheduleTask?.title || rescheduleTask?.id }}」设置新的发布时间</p>
        <label>新发布时间 *</label>
        <input v-model="rescheduleTime" type="datetime-local" class="input" />
        <div class="modal-actions" style="margin-top:16px">
          <button class="btn-secondary" @click="showRescheduleModal = false">取消</button>
          <button class="btn-primary" @click="submitReschedule" :disabled="!rescheduleTime">确认</button>
        </div>
      </div>
    </div>

    <!-- Batch schedule modal -->
    <div v-if="showBatchModal" class="modal-overlay" @click.self="showBatchModal = false">
      <div class="modal">
        <h3>批量排期发布</h3>
        <p style="font-size:12px;color:#999;margin:0 0 16px">
          自动为所有已合并但未发布的分组创建定时任务，按排期顺序无人工干预自动发布。
        </p>

        <label>平台 *</label>
        <select v-model="batchForm.platform" class="input" @change="loadUnscheduledGroups">
          <option value="douyin">抖音</option>
          <option value="kuaishou">快手</option>
        </select>

        <label>直播间筛选（可选）</label>
        <select v-model="batchForm.room_id" class="input" @change="loadUnscheduledGroups">
          <option :value="null">全部直播间</option>
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>

        <label>发布账号</label>
        <select v-model="batchForm.account_id" class="input">
          <option :value="null">不指定账号</option>
          <option v-for="a in accounts" :key="a.id" :value="a.id">
            {{ a.account_name }} ({{ a.platform }})
          </option>
        </select>

        <label>开始时间 *</label>
        <input v-model="batchForm.start_datetime" type="datetime-local" class="input" />

        <label>发布间隔（分钟）</label>
        <input v-model.number="batchForm.interval_minutes" type="number" min="1" class="input" />

        <div class="no-cart-row" style="margin:12px 0 4px">
          <button :class="['no-cart-btn', batchForm.no_cart ? 'no-cart-btn-on' : 'no-cart-btn-off']"
            @click="batchForm.no_cart = !batchForm.no_cart">
            {{ batchForm.no_cart ? '✓ 无车发布（不挂商品）' : '挂小黄车商品' }}
          </button>
        </div>

        <div style="margin-bottom:10px">
          <label class="no-cart-toggle" style="color:#a78bfa">
            <input type="checkbox" v-model="batchForm.auto_meta" />
            <span>自动 AI 生成文案（每篇独立生成，耗时较长）</span>
          </label>
        </div>

        <!-- Preview -->
        <div v-if="unscheduledGroups.length" class="batch-preview">
          <div class="batch-preview-title">
            待排期分组（{{ unscheduledGroups.length }} 个）：
          </div>
          <div class="batch-preview-list">
            <div v-for="(g, i) in unscheduledGroups" :key="g.id" class="batch-preview-item">
              <span class="batch-idx">{{ i + 1 }}</span>
              <span class="batch-label">{{ g.label }}</span>
              <span class="batch-time muted">{{ previewTime(i) }}</span>
            </div>
          </div>
        </div>
        <div v-else-if="batchLoading" class="muted" style="font-size:12px;padding:8px 0">加载中…</div>
        <div v-else class="muted" style="font-size:12px;padding:8px 0">暂无可排期的分组（所有已合并分组均已有发布任务）</div>

        <div class="modal-actions">
          <button class="btn-secondary" @click="showBatchModal = false">取消</button>
          <button class="btn-primary"
            :disabled="!unscheduledGroups.length || !batchForm.start_datetime || batchSubmitting"
            @click="submitBatch">
            {{ batchSubmitting ? '创建中…' : `确认排期（${unscheduledGroups.length} 篇）` }}
          </button>
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
          <button class="btn-xs" @click="loginAccount(a.id)" :disabled="loggingInId === a.id">{{ loggingInId === a.id ? '登录中…' : '登录' }}</button>
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
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  getRooms, getGroups, getGroup, getPublishTasks, createPublishTask, retryPublishTask, cancelPublishTask, bulkCancelPublishTasks,
  getProducts, getPublishAccounts, createPublishAccount, deletePublishAccount, loginPublishAccount,
  generatePublishMeta, matchGroupProduct, createWS, deleteGroup, reclipRecording,
  getUnscheduledGroups, batchSchedulePublish, regenPublishTaskMeta, reschedulePublishTask,
} from '../api.js'
import { useToast } from '../composables/toast.js'

const { showToast } = useToast()

const tasks = ref([])
const selectedTask = ref(null)
const regenning = ref(false)
const showRescheduleModal = ref(false)
const rescheduleTask = ref(null)
const rescheduleTime = ref('')
const showCreateModal = ref(false)
watch(showCreateModal, (v) => { if (v) refreshGroups() })
const statusFilter = ref('')
const mergedGroups = ref([])
const groupsRefreshing = ref(false)
const rooms = ref([])
const roomFilter = ref(1)   // default: 小圆圆不圆 (id=1)
const accounts = ref([])
const products = ref([])
const generating = ref(false)
const matchedProduct = ref(null)
const metaSchemes = ref([])
const selectedScheme = ref('')
const previewGroup = ref(null)   // group being previewed in video modal
const previewVersion = ref('director')  // 'director' | 'classic'
const reclipModal = ref(null)    // {group, feedback, saving, submitted}
const selectedPublishVersion = ref('both')
const BASE_URL = import.meta.env.VITE_API_BASE || ''
const scheduleMode = ref('now')
const progressLog = ref({})   // task_id → string[]
let ws = null
const scheduleTime = ref('10:00')
const scheduleInterval = ref(60)
const showAccounts = ref(false)

// ── Batch schedule ─────────────────────────────────────────────────────────────
const loggingInId = ref(null)
const showBatchModal = ref(false)
const batchSubmitting = ref(false)
const batchLoading = ref(false)
const unscheduledGroups = ref([])

function _defaultBatchStart() {
  const now = new Date()
  now.setSeconds(0, 0)
  // round up to next hour
  now.setMinutes(0)
  now.setHours(now.getHours() + 1)
  // format for datetime-local input: "YYYY-MM-DDTHH:MM"
  return now.toISOString().slice(0, 16)
}

const batchForm = ref({
  platform: 'douyin',
  account_id: null,
  room_id: null,
  start_datetime: _defaultBatchStart(),
  interval_minutes: 90,
  no_cart: false,
  auto_meta: false,
})

function previewTime(index) {
  if (!batchForm.value.start_datetime) return ''
  const base = new Date(batchForm.value.start_datetime)
  const t = new Date(base.getTime() + index * batchForm.value.interval_minutes * 60000)
  return t.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function loadUnscheduledGroups() {
  batchLoading.value = true
  try {
    unscheduledGroups.value = await getUnscheduledGroups(batchForm.value.platform, batchForm.value.room_id)
  } finally {
    batchLoading.value = false
  }
}

async function openBatchModal() {
  batchForm.value.start_datetime = _defaultBatchStart()
  showBatchModal.value = true
  await loadUnscheduledGroups()
}

async function submitBatch() {
  if (!batchForm.value.start_datetime || !unscheduledGroups.value.length) return
  batchSubmitting.value = true
  try {
    const result = await batchSchedulePublish({
      platform: batchForm.value.platform,
      account_id: batchForm.value.account_id || null,
      start_datetime: new Date(batchForm.value.start_datetime).toISOString(),
      interval_minutes: batchForm.value.interval_minutes,
      no_cart: batchForm.value.no_cart,
      auto_meta: batchForm.value.auto_meta,
      room_id: batchForm.value.room_id || null,
    })
    showBatchModal.value = false
    await loadTasks()
    showToast(result.message || `已创建 ${result.created} 个排期任务`, 'success')
  } catch (e) {
    showToast('批量排期失败: ' + e.message, 'error')
  } finally {
    batchSubmitting.value = false
  }
}

const filteredGroups = computed(() =>
  roomFilter.value === 0
    ? mergedGroups.value
    : mergedGroups.value.filter(g => g.room_id === roomFilter.value)
)

const publishedGroupIds = computed(() =>
  new Set(tasks.value.filter(t => t.status === 'done').map(t => t.group_id))
)

// Products filtered to match the selected group's room
const selectedGroupRoomId = computed(() => {
  if (!newTask.value.group_id) return null
  const g = mergedGroups.value.find(g => g.id === newTask.value.group_id)
  return g ? g.room_id : null
})

const roomFilteredProducts = computed(() => {
  // Use selected group's room first, fall back to room chip filter, then show all
  const roomId = selectedGroupRoomId.value || (roomFilter.value !== 0 ? roomFilter.value : null)
  if (!roomId) return products.value
  const byRoom = products.value.filter(p => p.room_id === roomId)
  const globals = products.value.filter(p => !p.room_id)
  const combined = [...byRoom, ...globals]
  return combined.length > 0 ? combined : products.value
})

const cartSearch = ref('')
const cartFilteredProducts = computed(() => {
  const base = roomFilteredProducts.value
  const q = cartSearch.value.trim().toLowerCase()
  if (!q) return base
  return base.filter(p =>
    (p.product_name || '').toLowerCase().includes(q) ||
    (p.keywords || '').toLowerCase().includes(q)
  )
})

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

const newTask = ref({ group_id: '', platform: 'douyin', account_id: '', title: '', description: '', tags: '', product_ids: [], no_cart: false })
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

async function refreshGroups() {
  groupsRefreshing.value = true
  try {
    const [groups, prods] = await Promise.all([getGroups(), getProducts()])
    mergedGroups.value = groups.filter(g => (g.merge_status === 2 || g.classic_status === 2 || g.director_status === 2 || g.creative_status === 2) && (g.merged_filename || g.director_final_video || g.creative_final_video))
    products.value = prods.filter(p => p.enabled)
  } finally {
    groupsRefreshing.value = false
  }
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

async function doBulkCancel() {
  if (!confirm('确认批量取消所有「待发布」和「定时」状态的任务？已发布/正在发布的任务不受影响。')) return
  try {
    const result = await bulkCancelPublishTasks({ status: 'all' })
    await loadTasks()
    showToast(`已取消 ${result.deleted} 个任务`, 'success')
  } catch (e) {
    showToast('批量取消失败: ' + e.message, 'error')
  }
}

async function deleteFailedTask(id) {
  try {
    await cancelPublishTask(id)
    if (selectedTask.value?.id === id) selectedTask.value = null
    await loadTasks()
    showToast('已删除', 'success')
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error')
  }
}

function isExpired(iso) {
  if (!iso) return false
  return new Date(iso) < new Date()
}

function openReschedule(task) {
  rescheduleTask.value = task
  // Default to 30 minutes from now
  const d = new Date(Date.now() + 30 * 60000)
  rescheduleTime.value = d.toISOString().slice(0, 16)
  showRescheduleModal.value = true
}

async function submitReschedule() {
  if (!rescheduleTask.value || !rescheduleTime.value) return
  try {
    await reschedulePublishTask(rescheduleTask.value.id, new Date(rescheduleTime.value).toISOString())
    showRescheduleModal.value = false
    await loadTasks()
    if (selectedTask.value?.id === rescheduleTask.value.id) {
      selectedTask.value = tasks.value.find(t => t.id === rescheduleTask.value.id) || null
    }
    showToast('已重新排期', 'success')
  } catch (e) {
    showToast('重新排期失败: ' + e.message, 'error')
  }
}

async function regenMeta(id) {
  regenning.value = true
  try {
    const result = await regenPublishTaskMeta(id)
    await loadTasks()
    if (selectedTask.value?.id === id) {
      selectedTask.value = tasks.value.find(t => t.id === id) || null
    }
    showToast('文案已更新: ' + (result.title || ''), 'success')
  } catch (e) {
    showToast('重生成失败: ' + e.message, 'error')
  } finally {
    regenning.value = false
  }
}

async function onGroupSelect() {
  matchedProduct.value = null
  newTask.value.product_ids = []
  metaSchemes.value = []
  selectedScheme.value = ''
  const g = mergedGroups.value.find(g => g.id === newTask.value.group_id)
  selectedPublishVersion.value = g?.publish_versions || 'both'
}

const currentScheme = computed(() =>
  metaSchemes.value.find(s => s.type === selectedScheme.value) || null
)

const selectedGroup = computed(() =>
  newTask.value.group_id ? mergedGroups.value.find(g => g.id === newTask.value.group_id) : null
)

const previewVideoUrl = computed(() => {
  if (!previewGroup.value) return ''
  if (previewVersion.value === 'classic') return `${BASE_URL}/api/groups/${previewGroup.value.id}/download`
  if (previewVersion.value === 'director') return `${BASE_URL}/api/groups/${previewGroup.value.id}/director-download`
  return `${BASE_URL}/api/groups/${previewGroup.value.id}/download`
})

watch(previewGroup, (g) => {
  if (!g) return
  previewVersion.value = g.director_status === 2 ? 'director' : g.creative_status === 2 ? 'creative' : 'classic'
})

function groupVideoUrl(groupId) {
  return `${BASE_URL}/api/groups/${groupId}/download`
}

async function setPublishVersion(version) {
  const g = selectedGroup.value
  if (!g) return
  selectedPublishVersion.value = version
  g.publish_versions = version
  try {
    await fetch(`${BASE_URL}/api/groups/${g.id}/publish-versions`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ publish_versions: version }),
    })
  } catch (e) {
    showToast('版本设置失败: ' + e.message, 'error')
  }
}

async function confirmDeleteGroup(g) {
  if (!confirm(`确认删除分组「${g.label}」？此操作不可撤销。`)) return
  try {
    await deleteGroup(g.id)
    mergedGroups.value = mergedGroups.value.filter(x => x.id !== g.id)
    if (newTask.value.group_id === g.id) {
      newTask.value.group_id = ''
      metaSchemes.value = []
      selectedScheme.value = ''
    }
    showToast('分组已删除', 'success')
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error')
  }
}

async function openReclipModal(g) {
  reclipModal.value = { group: g, feedback: '', saving: false, submitted: false }
}

async function doReclip() {
  if (!reclipModal.value || reclipModal.value.saving) return
  reclipModal.value.saving = true
  try {
    const detail = await getGroup(reclipModal.value.group.id)
    const recs = detail.recordings || []
    if (!recs.length) throw new Error('该分组没有关联录像')
    await Promise.all(recs.map(r => reclipRecording(r.id, reclipModal.value.feedback)))
    reclipModal.value.submitted = true
  } catch (e) {
    showToast('重剪失败: ' + e.message, 'error')
  } finally {
    reclipModal.value.saving = false
  }
}

async function generateMeta() {
  if (!newTask.value.group_id) return
  generating.value = true
  metaSchemes.value = []
  selectedScheme.value = ''
  try {
    const meta = await generatePublishMeta(newTask.value.group_id)
    if (meta && meta.schemes && meta.schemes.length) {
      metaSchemes.value = meta.schemes
      // Auto-apply first scheme
      applyScheme(meta.schemes[0])
      showToast(`AI生成了 ${meta.schemes.length} 套文案方案`, 'success')
    } else if (meta) {
      // Legacy single-scheme fallback
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

function applyScheme(scheme) {
  selectedScheme.value = scheme.type
  newTask.value.title = scheme.title || ''
  newTask.value.description = scheme.description || ''
  newTask.value.tags = scheme.tags || ''
}

function toggleAllProducts() {
  const pool = cartFilteredProducts.value
  if (newTask.value.product_ids.length === pool.length) {
    newTask.value.product_ids = []
  } else {
    newTask.value.product_ids = pool.map(p => p.id)
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
    no_cart: newTask.value.no_cart,
  }
  try {
    try {
      await createPublishTask(body)
    } catch (e) {
      if (e.message?.includes('duplicate')) {
        const go = confirm(`该分组已存在 ${body.platform} 发布任务（可能已发布或排队中）。\n确认要再次发布吗？\n如需重复发布，请先在任务列表删除旧任务。`)
        if (go) showToast('请先在发布列表删除旧任务，再重新创建', 'info')
        return
      }
      throw e
    }
    // Advance schedule time by interval for next task
    if (scheduleMode.value === 'later' && scheduleInterval.value) {
      const [h, m] = scheduleTime.value.split(':').map(Number)
      const next = new Date(0, 0, 0, h, m + scheduleInterval.value)
      scheduleTime.value = `${String(next.getHours()).padStart(2,'0')}:${String(next.getMinutes()).padStart(2,'0')}`
    }
    showCreateModal.value = false
    const defaultAcc = accounts.value.find(a => a.account_name === '颜遇生活')
    newTask.value = { group_id: '', platform: 'douyin', account_id: defaultAcc?.id || '', title: '', description: '', tags: '', product_ids: [], no_cart: false }
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
  if (loggingInId.value === id) return  // 防重复点击
  loggingInId.value = id
  try {
    await loginPublishAccount(id)
    showToast('浏览器已启动，请扫码登录，登录成功后自动关闭', 'info')
  } catch (e) {
    loggingInId.value = null
    showToast('启动失败: ' + e.message, 'error')
  }
}

onMounted(async () => {
  await loadTasks()
  const [groups, roomList] = await Promise.all([getGroups(), getRooms()])
  mergedGroups.value = groups.filter(g => (g.merge_status === 2 || g.classic_status === 2 || g.director_status === 2 || g.creative_status === 2) && (g.merged_filename || g.director_final_video || g.creative_final_video))
  rooms.value = roomList
  accounts.value = await getPublishAccounts()
  const defaultAccount = accounts.value.find(a => a.account_name === '颜遇生活')
  if (defaultAccount) newTask.value.account_id = defaultAccount.id
  products.value = (await getProducts()).filter(p => p.enabled)
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
    } else if (msg.type === 'clip_progress' && msg.phase === 'done') {
      // A clip group just finished merging — refresh group list
      refreshGroups()
    } else if (msg.type === 'login_done') {
      loggingInId.value = null
      if (msg.success) {
        getPublishAccounts().then(list => { accounts.value = list })
        showToast('登录成功，Cookie 已更新', 'success')
      } else {
        showToast('登录失败或超时，请重试', 'error')
      }
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
.task-room-tag { font-size: 10px; color: #888; background: #222; border: 1px solid #333; border-radius: 3px; padding: 1px 4px; margin-right: 5px; }

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
.scheme-picker { background: #111; border: 1px solid #333; border-radius: 8px; padding: 12px; margin-bottom: 8px; }
.scheme-picker-label { font-size: 11px; color: #888; margin-bottom: 8px; }
.scheme-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.scheme-tab { background: #2a2a2a; color: #ccc; border: 1px solid #444; border-radius: 20px; padding: 4px 14px; cursor: pointer; font-size: 12px; }
.scheme-tab:hover { background: #333; }
.scheme-tab-active { background: #fe2c55; color: #fff; border-color: #fe2c55; }
.scheme-preview { background: #1a1a1a; border-radius: 6px; padding: 8px 10px; }
.scheme-preview-title { font-size: 13px; font-weight: 600; color: #e0e0e0; margin-bottom: 4px; }
.scheme-preview-desc { font-size: 11px; color: #999; line-height: 1.5; max-height: 60px; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
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
.room-filter-chips { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 6px; }
.room-chip { background: #1e1e1e; border: 1px solid #333; color: #888; border-radius: 4px; padding: 3px 10px; cursor: pointer; font-size: 11px; white-space: nowrap; }
.room-chip.active { background: #fe2c55; border-color: #fe2c55; color: #fff; }
.group-list { background: #111; border: 1px solid #333; border-radius: 6px; max-height: 180px; overflow-y: auto; }
.group-item { padding: 8px 12px; cursor: pointer; border-bottom: 1px solid #1e1e1e; position: relative; transition: background 0.15s; }
.group-item-actions { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); display: none; gap: 4px; align-items: center; }
.group-item:hover .group-item-actions { display: flex; }
.gact-btn { background: #2a2a2a; color: #ccc; border: 1px solid #444; border-radius: 4px; padding: 2px 7px; cursor: pointer; font-size: 11px; }
.gact-btn:hover { background: #3a3a3a; }
.gact-orange { color: #f97316; border-color: #f97316; }
.gact-orange:hover { background: rgba(249,115,22,0.1); }
.gact-red { color: #fe2c55; border-color: #fe2c55; }
.gact-red:hover { background: rgba(254,44,85,0.1); }
.preview-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 200; display: flex; align-items: center; justify-content: center; }
.preview-modal { background: #111; border: 1px solid #333; border-radius: 12px; width: min(420px, 95vw); overflow: hidden; }
.preview-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid #222; font-size: 13px; font-weight: 600; }
.preview-close { background: none; border: none; color: #888; cursor: pointer; font-size: 16px; padding: 0 4px; }
.preview-close:hover { color: #fff; }
.preview-video { width: 100%; max-height: 70vh; display: block; background: #000; }
.reclip-modal { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 20px; width: min(400px, 95vw); }
.group-item:last-child { border-bottom: none; }
.group-item:hover { background: #1a1a1a; }
.group-item-selected { background: rgba(254,44,85,0.08); border-left: 2px solid #fe2c55; }
.group-item-name { font-size: 13px; color: #e0e0e0; }
.group-item-sub { font-size: 11px; color: #666; margin-top: 2px; display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.group-room-tag { font-size: 10px; color: #888; background: #222; border: 1px solid #333; border-radius: 3px; padding: 1px 5px; white-space: nowrap; }
.group-published-badge { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); font-size: 11px; color: #34d399; font-weight: 600; }
.group-item-custom { background: #f5f3ef; border-left: 2px solid #fb923c; }
.group-item-custom:hover { background: #ede9e1; }
.group-item-custom .group-item-name { color: #1a1a1a; }
.group-item-custom .group-item-sub { color: #777; }
.group-item-custom.group-item-selected { background: rgba(251,146,60,0.15); border-left: 2px solid #fb923c; }

.vbadge { font-size: 10px; border-radius: 3px; padding: 0 3px; }
.vbadge-director { color: #a78bfa; }
.vbadge-classic { color: #34d399; }
.vbadge-creative { color: #f59e0b; }

.version-switcher { display: flex; gap: 8px; margin-bottom: 4px; }
.vsw-option { flex: 1; display: flex; align-items: center; justify-content: space-between; background: #111; border: 1px solid #333; border-radius: 8px; padding: 8px 12px; cursor: pointer; transition: all 0.15s; }
.vsw-option:hover { border-color: #555; background: #1a1a1a; }
.vsw-active { border-color: #fe2c55; background: rgba(254,44,85,0.08); }
.vsw-label { font-size: 13px; color: #e0e0e0; }
.vsw-preview-btn { font-size: 11px; color: #60a5fa; background: rgba(96,165,250,0.1); border: 1px solid rgba(96,165,250,0.3); border-radius: 4px; padding: 2px 7px; transition: all 0.15s; }
.vsw-preview-btn:hover { background: rgba(96,165,250,0.2); }

.preview-tabs { display: flex; gap: 6px; }
.ptab { background: #2a2a2a; color: #888; border: 1px solid #444; border-radius: 20px; padding: 3px 12px; cursor: pointer; font-size: 12px; }
.ptab:hover { background: #333; color: #ccc; }
.ptab-active { background: #fe2c55; color: #fff; border-color: #fe2c55; }

.product-multi { display: flex; flex-direction: column; }
.product-multi-list { background: #111; border: 1px solid #333; border-radius: 6px; padding: 8px 10px; max-height: 160px; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; }
.product-check-item { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #e0e0e0; cursor: pointer; }
.product-room-tag { font-size: 10px; color: #888; background: #222; border: 1px solid #333; border-radius: 3px; padding: 1px 5px; white-space: nowrap; flex-shrink: 0; }
.product-check-item input[type=checkbox] { accent-color: #fe2c55; width: 14px; height: 14px; cursor: pointer; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }

.btn-primary { background: #fe2c55; color: #fff; border: none; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-warn-sm { background: rgba(251,191,36,0.1); color: #fbbf24; border: 1px solid rgba(251,191,36,0.3); border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 13px; }
.btn-warn-sm:hover { background: rgba(251,191,36,0.2); }
.btn-sm { padding: 5px 12px; font-size: 12px; }
.btn-danger { background: transparent; color: #fe2c55; border: 1px solid #fe2c55; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-xs { background: #2a2a2a; color: #ccc; border: 1px solid #444; border-radius: 4px; padding: 3px 8px; cursor: pointer; font-size: 11px; margin-right: 4px; }
.btn-xs.btn-danger { color: #fe2c55; border-color: #fe2c55; }
.btn-xs.btn-retry { color: #60a5fa; border-color: #60a5fa; padding: 2px 6px; margin-left: auto; }
.btn-warning { background: transparent; color: #f59e0b; border: 1px solid #f59e0b; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-xs.btn-del-failed { color: #fe2c55; border-color: #fe2c55; padding: 2px 7px; margin-left: 4px; font-size: 13px; line-height: 1; }

.badge { border-radius: 4px; padding: 2px 8px; font-size: 11px; }
.badge-green { background: rgba(52,211,153,0.15); color: #34d399; }
.badge-gray { background: #2a2a2a; color: #666; }
.badge-yellow { background: rgba(245,158,11,0.15); color: #f59e0b; }
.badge-blue { background: rgba(59,130,246,0.15); color: #60a5fa; }
.badge-orange { background: rgba(249,115,22,0.15); color: #fb923c; }
.badge-red { background: rgba(254,44,85,0.15); color: #fe2c55; }
.badge-no-cart { background: rgba(100,200,255,0.15); color: #67d4f0; }
.no-cart-row { margin: 8px 0; }
.no-cart-btn { width: 100%; padding: 9px 12px; border-radius: 8px; border: 1px solid; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.15s; text-align: center; }
.no-cart-btn-off { background: rgba(254,44,85,0.08); border-color: rgba(254,44,85,0.3); color: #fe2c55; }
.no-cart-btn-off:hover { background: rgba(254,44,85,0.15); }
.no-cart-btn-on { background: rgba(100,200,255,0.12); border-color: rgba(100,200,255,0.4); color: #67d4f0; }
.no-cart-btn-on:hover { background: rgba(100,200,255,0.2); }
.no-cart-hint { font-size: 12px; color: #67d4f0; padding: 8px 10px; background: rgba(100,200,255,0.08); border-radius: 6px; border: 1px solid rgba(100,200,255,0.2); margin-top: 4px; }
.batch-preview { background: #111; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px 12px; margin: 10px 0; max-height: 220px; overflow-y: auto; }
.batch-preview-title { font-size: 12px; color: #999; margin-bottom: 6px; }
.batch-preview-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px solid #1e1e1e; font-size: 12px; }
.batch-preview-item:last-child { border-bottom: none; }
.batch-idx { width: 20px; text-align: right; color: #555; flex-shrink: 0; }
.batch-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.batch-time { flex-shrink: 0; font-size: 11px; }
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
