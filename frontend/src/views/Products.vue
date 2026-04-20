<template>
  <div>
    <div class="page-header">
      <h2>商品库</h2>
      <div class="header-actions">
        <!-- 直播间筛选 -->
        <select v-model="roomFilter" class="room-filter-select">
          <option :value="0">全部直播间</option>
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <input v-model="searchKeyword" class="search-input" placeholder="搜索商品名/关键词..." @input="applyFilter" />
        <button class="btn-primary" @click="openAddModal">+ 新增商品</button>
        <button class="btn-secondary" @click="showBulkModal = true">批量导入</button>
        <button class="btn-warn" @click="loadDuplicates" title="检测重复链接">🔍 重复检测</button>
      </div>
    </div>

    <!-- 重复链接提示栏 -->
    <div v-if="duplicates.length" class="dup-banner">
      <span class="dup-title">⚠ 发现 {{ dupUrlCount }} 个重复链接，共 {{ duplicates.length }} 条商品</span>
      <button class="btn-xs btn-danger" @click="duplicates = []">关闭</button>
      <div class="dup-list">
        <div v-for="p in duplicates" :key="p.id" class="dup-item">
          <span class="dup-id muted">#{{ p.id }}</span>
          <span class="dup-name">{{ p.product_name }}</span>
          <span class="dup-url muted">{{ (p.product_url || '').slice(0, 60) }}</span>
          <button class="btn-xs btn-danger" @click="deleteProduct(p.id, true)">删除</button>
        </div>
      </div>
    </div>

    <div class="table-wrap">
      <table v-if="filtered.length">
        <thead>
          <tr>
            <th>ID</th>
            <th>直播间</th>
            <th>商品名称</th>
            <th>平台商品ID</th>
            <th>匹配关键词</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in filtered" :key="p.id" :class="p._dup ? 'row-dup' : ''">
            <td class="muted">{{ p.id }}</td>
            <td>
              <select class="room-select" :value="p.room_id || ''" @change="changeRoom(p, $event.target.value)">
                <option value="">—</option>
                <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
              </select>
            </td>
            <td class="name-cell">
              <span class="name-wrap">
                <a v-if="p.product_url" :href="p.product_url" target="_blank" class="link"
                   :class="p.product_thumb ? 'has-thumb' : ''"
                   @mouseenter="p.product_thumb && showPreview(p, $event)" @mouseleave="hidePreview()">{{ p.product_name }}</a>
                <span v-else>{{ p.product_name }}</span>
                <span v-if="p._dup" class="dup-badge">重复</span>
              </span>
            </td>
            <td class="mono">{{ p.product_id || '—' }}</td>
            <td>
              <span v-if="editingId === p.id">
                <input v-model="editKeywords" class="inline-input" @keyup.enter="saveKeywords(p.id)" @keyup.escape="editingId = null" />
                <button class="btn-xs" @click="saveKeywords(p.id)">保存</button>
              </span>
              <span v-else class="keywords" @click="startEditKeywords(p)">
                <span v-for="kw in splitKw(p.keywords)" :key="kw" class="tag">{{ kw }}</span>
                <span v-if="!p.keywords" class="muted">点击编辑</span>
              </span>
            </td>
            <td>
              <span :class="['badge', p.enabled ? 'badge-green' : 'badge-gray']">
                {{ p.enabled ? '启用' : '停用' }}
              </span>
            </td>
            <td>
              <button class="btn-xs" @click="toggleProduct(p)">{{ p.enabled ? '停用' : '启用' }}</button>
              <button class="btn-xs btn-danger" @click="deleteProduct(p.id, false)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无商品</div>
    </div>

    <!-- 悬停预览浮层 -->
    <div v-if="previewPopup.visible" class="img-popup" :style="{ top: previewPopup.y + 'px', left: previewPopup.x + 'px' }">
      <img v-if="previewPopup.url" :src="previewPopup.url" class="popup-img" @error="previewPopup.url = ''" />
      <span v-else class="popup-noimg">无预览图</span>
    </div>

    <!-- 新增商品 Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
      <div class="modal">
        <h3>新增商品</h3>
        <label>直播间</label>
        <select v-model="form.room_id" class="input">
          <option value="">不关联直播间</option>
          <option v-for="r in rooms" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
        <label>商品名称 *</label>
        <input v-model="form.product_name" class="input" placeholder="如：蓬松波波头假发" />
        <label>平台商品ID</label>
        <input v-model="form.product_id" class="input" placeholder="抖音商品ID" />
        <label>商品链接</label>
        <div class="url-input-wrap">
          <input v-model="form.product_url" class="input" placeholder="https://..."
                 @blur="checkUrlDup" @input="urlDupResult = null" />
          <div v-if="urlDupResult && urlDupResult.length" class="url-dup-hint">
            ⚠ 已存在相同链接：{{ urlDupResult.map(p => p.product_name).join('、') }}
          </div>
          <div v-else-if="urlDupResult !== null && urlDupResult.length === 0" class="url-ok-hint">✓ 链接未重复</div>
        </div>
        <label>缩略图URL（可选，鼠标悬停时预览）</label>
        <div class="thumb-input-wrap">
          <input v-model="form.product_thumb" class="input" placeholder="https://p3-aio.ecombdimg.com/img/..." />
          <img v-if="form.product_thumb" :src="form.product_thumb" class="thumb-preview" @error="e => e.target.style.display='none'" />
        </div>
        <label>匹配关键词（逗号分隔）</label>
        <input v-model="form.keywords" class="input" placeholder="假发,Bob,黑色" />
        <div class="modal-actions">
          <button class="btn-secondary" @click="showAddModal = false">取消</button>
          <button class="btn-primary" @click="submitAdd" :disabled="!form.product_name">确认添加</button>
        </div>
      </div>
    </div>

    <!-- 批量导入 Modal -->
    <div v-if="showBulkModal" class="modal-overlay" @click.self="showBulkModal = false">
      <div class="modal modal-lg">
        <h3>批量导入商品</h3>
        <div class="bulk-tabs">
          <button :class="['bulk-tab', bulkMode === 'excel' && 'bulk-tab-active']" @click="bulkMode = 'excel'">Excel 导入</button>
          <button :class="['bulk-tab', bulkMode === 'json' && 'bulk-tab-active']" @click="bulkMode = 'json'">JSON 导入</button>
        </div>

        <!-- Excel 模式 -->
        <template v-if="bulkMode === 'excel'">
          <p class="hint">上传 .xlsx 文件，列名：product_name（必填）、product_id、product_url、keywords、platform、room_id</p>
          <a :href="`${apiBase}/api/products/template.xlsx`" class="download-tpl" download>⬇ 下载导入模板</a>
          <div class="file-drop" @click="$refs.xlsxInput.click()" @dragover.prevent @drop.prevent="onDrop">
            <span v-if="!xlsxFile">点击选择或拖拽 .xlsx 文件</span>
            <span v-else class="file-name">📄 {{ xlsxFile.name }}</span>
          </div>
          <input ref="xlsxInput" type="file" accept=".xlsx,.xls" style="display:none" @change="onFileChange" />
          <div v-if="bulkError" class="error-msg">{{ bulkError }}</div>
          <div class="modal-actions">
            <button class="btn-secondary" @click="closeBulkModal">取消</button>
            <button class="btn-primary" @click="submitExcel" :disabled="!xlsxFile || bulkLoading">
              {{ bulkLoading ? '导入中…' : '导入' }}
            </button>
          </div>
        </template>

        <!-- JSON 模式 -->
        <template v-else>
          <p class="hint">粘贴 JSON 数组，每项包含 product_name（必填）、product_id、product_url、keywords</p>
          <textarea v-model="bulkJson" class="textarea" rows="12" placeholder='[{"product_name":"假发A","product_id":"123","keywords":"假发,卷发"}]'></textarea>
          <div v-if="bulkError" class="error-msg">{{ bulkError }}</div>
          <div class="modal-actions">
            <button class="btn-secondary" @click="closeBulkModal">取消</button>
            <button class="btn-primary" @click="submitBulk">导入</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { getRooms, getProducts, createProduct, bulkCreateProducts, updateProduct, deleteProduct as apiDelete } from '../api.js'
import { useToast } from '../composables/toast.js'

const BASE = import.meta.env.VITE_API_BASE || ''
const apiBase = BASE

const { showToast } = useToast()

const products = ref([])
const rooms = ref([])
const searchKeyword = ref('')
const roomFilter = ref(0)
const showAddModal = ref(false)
const showBulkModal = ref(false)
const bulkMode = ref('excel')
const editingId = ref(null)
const editKeywords = ref('')
const bulkJson = ref('')
const bulkError = ref('')
const bulkLoading = ref(false)
const xlsxFile = ref(null)
const xlsxInput = ref(null)
const duplicates = ref([])
const urlDupResult = ref(null)

const form = ref({ product_name: '', product_id: '', product_url: '', product_thumb: '', keywords: '', room_id: '' })

// 悬停预览
const previewPopup = ref({ visible: false, url: '', x: 0, y: 0 })
let previewTimer = null

function showPreview(p, e) {
  clearTimeout(previewTimer)
  previewTimer = setTimeout(() => {
    const rect = e.target.getBoundingClientRect()
    previewPopup.value = {
      visible: true,
      url: p.product_thumb || '',
      x: rect.right + 8,
      y: rect.top + window.scrollY
    }
  }, 300)
}
function hidePreview() {
  clearTimeout(previewTimer)
  previewPopup.value.visible = false
}

// 过滤
const filtered = computed(() => {
  let list = products.value
  if (roomFilter.value) list = list.filter(p => p.room_id === roomFilter.value || !p.room_id)
  const q = searchKeyword.value.trim().toLowerCase()
  if (q) list = list.filter(p => (p.product_name || '').toLowerCase().includes(q) || (p.keywords || '').toLowerCase().includes(q))
  return list
})

function applyFilter() { /* 触发 computed 重算 */ }

const dupUrlCount = computed(() => new Set(duplicates.value.map(p => p.product_url)).size)

async function loadProducts() {
  products.value = await getProducts()
}

async function loadDuplicates() {
  try {
    const res = await fetch(`${BASE}/api/products/duplicate-urls`)
    const data = await res.json()
    duplicates.value = data
    // 标记主列表中重复行
    const dupIds = new Set(data.map(p => p.id))
    products.value = products.value.map(p => ({ ...p, _dup: dupIds.has(p.id) }))
    if (!data.length) showToast('未发现重复链接', 'success')
  } catch (e) {
    showToast('检测失败: ' + e.message, 'error')
  }
}

async function checkUrlDup() {
  const url = form.value.product_url.trim()
  if (!url) { urlDupResult.value = null; return }
  const res = await fetch(`${BASE}/api/products/check-url?url=${encodeURIComponent(url)}`)
  const data = await res.json()
  urlDupResult.value = data.duplicates || []
}

function splitKw(kw) {
  if (!kw) return []
  return kw.split(',').map(s => s.trim()).filter(Boolean)
}

function startEditKeywords(p) {
  editingId.value = p.id
  editKeywords.value = p.keywords || ''
}

async function saveKeywords(id) {
  try {
    await updateProduct(id, { keywords: editKeywords.value })
    editingId.value = null
    await loadProducts()
    showToast('关键词已更新', 'success')
  } catch (e) {
    showToast('更新失败: ' + e.message, 'error')
  }
}

async function changeRoom(p, roomId) {
  try {
    await updateProduct(p.id, { room_id: roomId ? parseInt(roomId) : null })
    await loadProducts()
  } catch (e) {
    showToast('更新失败: ' + e.message, 'error')
  }
}

async function toggleProduct(p) {
  try {
    await updateProduct(p.id, { enabled: !p.enabled })
    await loadProducts()
  } catch (e) {
    showToast('操作失败: ' + e.message, 'error')
  }
}

async function deleteProduct(id, fromDup) {
  if (!confirm('确认删除此商品？')) return
  try {
    await apiDelete(id)
    if (fromDup) duplicates.value = duplicates.value.filter(p => p.id !== id)
    await loadProducts()
    showToast('已删除', 'success')
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error')
  }
}

function openAddModal() {
  form.value = { product_name: '', product_id: '', product_url: '', product_thumb: '', keywords: '', room_id: '' }
  urlDupResult.value = null
  showAddModal.value = true
}

async function submitAdd() {
  try {
    const payload = { ...form.value, room_id: form.value.room_id || null }
    await createProduct(payload)
    showAddModal.value = false
    await loadProducts()
    showToast('商品已添加', 'success')
  } catch (e) {
    showToast('添加失败: ' + e.message, 'error')
  }
}

function closeBulkModal() {
  showBulkModal.value = false
  bulkJson.value = ''
  bulkError.value = ''
  xlsxFile.value = null
  bulkLoading.value = false
}

function onFileChange(e) {
  xlsxFile.value = e.target.files[0] || null
  bulkError.value = ''
}

function onDrop(e) {
  const f = e.dataTransfer.files[0]
  if (f && (f.name.endsWith('.xlsx') || f.name.endsWith('.xls'))) {
    xlsxFile.value = f
    bulkError.value = ''
  } else {
    bulkError.value = '请上传 .xlsx 或 .xls 文件'
  }
}

async function submitExcel() {
  if (!xlsxFile.value) return
  bulkLoading.value = true
  bulkError.value = ''
  try {
    const fd = new FormData()
    fd.append('file', xlsxFile.value)
    const res = await fetch(`${BASE}/api/products/import-excel`, { method: 'POST', body: fd })
    if (!res.ok) { bulkError.value = await res.text(); return }
    const result = await res.json()
    closeBulkModal()
    await loadProducts()
    const msg = `成功导入 ${result.created} 个商品` + (result.skipped_rows.length ? `，跳过 ${result.skipped_rows.length} 行（无商品名）` : '')
    showToast(msg, 'success')
  } catch (e) {
    bulkError.value = '导入失败: ' + e.message
  } finally {
    bulkLoading.value = false
  }
}

async function submitBulk() {
  bulkError.value = ''
  let data
  try {
    data = JSON.parse(bulkJson.value)
    if (!Array.isArray(data)) throw new Error('必须是JSON数组')
  } catch (e) {
    bulkError.value = 'JSON解析失败: ' + e.message
    return
  }
  try {
    const result = await bulkCreateProducts(data)
    closeBulkModal()
    await loadProducts()
    showToast(`成功导入 ${result.created} 个商品`, 'success')
  } catch (e) {
    bulkError.value = '导入失败: ' + e.message
  }
}

onMounted(async () => {
  rooms.value = await getRooms()
  await loadProducts()
})
</script>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; flex-wrap: wrap; gap: 8px; }
.page-header h2 { font-size: 18px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.search-input { background: #1e1e1e; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 6px 12px; font-size: 13px; width: 180px; }
.room-filter-select { background: #1e1e1e; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 6px 10px; font-size: 13px; cursor: pointer; }
.room-filter-select:focus { outline: none; border-color: #fe2c55; }

/* 重复检测 */
.btn-warn { background: rgba(251,191,36,0.12); color: #fbbf24; border: 1px solid rgba(251,191,36,0.3); border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-warn:hover { background: rgba(251,191,36,0.2); }
.dup-banner { background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.25); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
.dup-title { font-size: 13px; color: #fbbf24; font-weight: 500; }
.dup-list { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; max-height: 240px; overflow-y: auto; }
.dup-item { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 4px 0; border-bottom: 1px solid #2a2a2a; }
.dup-id { width: 36px; flex-shrink: 0; }
.dup-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dup-url { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.dup-badge { background: rgba(254,44,85,0.15); color: #fe2c55; border: 1px solid rgba(254,44,85,0.3); border-radius: 3px; padding: 1px 5px; font-size: 10px; margin-left: 4px; flex-shrink: 0; }
.row-dup td { background: rgba(254,44,85,0.04); }

/* 表格 */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: #888; font-weight: 500; padding: 10px 12px; border-bottom: 1px solid #2a2a2a; }
td { padding: 10px 12px; border-bottom: 1px solid #1e1e1e; vertical-align: middle; }
tr:hover td { background: #1a1a1a; }
.muted { color: #666; }
.name-cell { max-width: 300px; }
.name-wrap { display: flex; align-items: center; gap: 6px; }
.room-select { background: #1e1e1e; border: 1px solid #333; color: #ccc; border-radius: 4px; padding: 2px 4px; font-size: 11px; cursor: pointer; }
.room-select:focus { outline: none; border-color: #fe2c55; }
.mono { font-family: monospace; font-size: 12px; }
.link { color: #fe2c55; text-decoration: none; }
.link:hover { text-decoration: underline; }
.keywords { cursor: pointer; display: flex; gap: 4px; flex-wrap: wrap; }
.tag { background: #2a2a2a; border: 1px solid #444; border-radius: 4px; padding: 2px 6px; font-size: 11px; }
.badge { border-radius: 4px; padding: 2px 8px; font-size: 11px; }
.badge-green { background: rgba(52,211,153,0.15); color: #34d399; }
.badge-gray { background: #2a2a2a; color: #666; }
.empty { text-align: center; color: #666; padding: 48px; }
.inline-input { background: #1e1e1e; border: 1px solid #555; color: #e0e0e0; border-radius: 4px; padding: 3px 8px; font-size: 12px; width: 180px; margin-right: 4px; }

/* 悬停图片预览 */
.img-popup { position: fixed; z-index: 9999; background: #1a1a1a; border: 1px solid #444; border-radius: 8px; padding: 6px; pointer-events: none; box-shadow: 0 8px 32px rgba(0,0,0,0.6); }
.popup-img { width: 160px; height: 160px; object-fit: cover; border-radius: 4px; display: block; }
.popup-noimg { display: block; width: 120px; text-align: center; color: #666; font-size: 12px; padding: 16px 0; }

/* Buttons */
.btn-primary { background: #fe2c55; color: #fff; border: none; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-xs { background: #2a2a2a; color: #ccc; border: 1px solid #444; border-radius: 4px; padding: 3px 8px; cursor: pointer; font-size: 11px; margin-right: 4px; }
.btn-xs:hover { background: #333; }
.btn-danger { color: #fe2c55; border-color: rgba(254,44,85,0.4); }
.btn-danger:hover { background: rgba(254,44,85,0.1); }

/* Modals */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 100; display: flex; align-items: center; justify-content: center; }
.modal { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 24px; width: 440px; max-width: 95vw; max-height: 90vh; overflow-y: auto; }
.modal-lg { width: 560px; }
.modal h3 { font-size: 16px; margin-bottom: 16px; }
label { display: block; font-size: 12px; color: #888; margin: 12px 0 4px; }
.input { width: 100%; background: #111; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 8px 12px; font-size: 13px; box-sizing: border-box; }
.input:focus { outline: none; border-color: #fe2c55; }
.textarea { width: 100%; background: #111; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 8px 12px; font-size: 12px; font-family: monospace; resize: vertical; box-sizing: border-box; }
.hint { font-size: 12px; color: #777; margin-bottom: 8px; }
.error-msg { color: #fe2c55; font-size: 12px; margin-top: 8px; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }

/* URL 重复检测 */
.url-input-wrap { position: relative; }
.url-dup-hint { font-size: 11px; color: #fbbf24; margin-top: 4px; }
.url-ok-hint { font-size: 11px; color: #34d399; margin-top: 4px; }

/* 批量导入 tabs */
.bulk-tabs { display: flex; gap: 4px; margin-bottom: 14px; }
.bulk-tab { background: #222; color: #888; border: 1px solid #333; border-radius: 6px; padding: 5px 14px; cursor: pointer; font-size: 13px; }
.bulk-tab-active { background: rgba(254,44,85,0.15); color: #fe2c55; border-color: rgba(254,44,85,0.4); }

/* 下载模板 */
.download-tpl { display: inline-block; font-size: 12px; color: #60a5fa; margin-bottom: 10px; text-decoration: none; }
.download-tpl:hover { text-decoration: underline; }

/* 文件拖拽区 */
.file-drop { border: 2px dashed #444; border-radius: 8px; padding: 24px; text-align: center; cursor: pointer; font-size: 13px; color: #888; margin-bottom: 8px; transition: border-color 0.2s; }
.file-drop:hover { border-color: #fe2c55; color: #ccc; }
.file-name { color: #e0e0e0; }

/* 缩略图输入 */
.thumb-input-wrap { display: flex; align-items: center; gap: 8px; }
.thumb-input-wrap .input { flex: 1; }
.thumb-preview { width: 48px; height: 48px; object-fit: cover; border-radius: 4px; border: 1px solid #333; flex-shrink: 0; }
.has-thumb { border-bottom: 1px dashed rgba(254,44,85,0.5); }
</style>
