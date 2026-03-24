<template>
  <div>
    <div class="page-header">
      <h2>商品库</h2>
      <div class="header-actions">
        <input v-model="searchKeyword" class="search-input" placeholder="搜索商品名/关键词..." @input="loadProducts" />
        <button class="btn-primary" @click="showAddModal = true">+ 新增商品</button>
        <button class="btn-secondary" @click="showBulkModal = true">批量导入</button>
      </div>
    </div>

    <div class="table-wrap">
      <table v-if="products.length">
        <thead>
          <tr>
            <th>ID</th>
            <th>商品名称</th>
            <th>平台商品ID</th>
            <th>匹配关键词</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in products" :key="p.id">
            <td class="muted">{{ p.id }}</td>
            <td>
              <a v-if="p.product_url" :href="p.product_url" target="_blank" class="link">{{ p.product_name }}</a>
              <span v-else>{{ p.product_name }}</span>
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
              <button class="btn-xs btn-danger" @click="deleteProduct(p.id)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无商品，点击"新增商品"添加</div>
    </div>

    <!-- Add Modal -->
    <div v-if="showAddModal" class="modal-overlay" @click.self="showAddModal = false">
      <div class="modal">
        <h3>新增商品</h3>
        <label>商品名称 *</label>
        <input v-model="form.product_name" class="input" placeholder="如：蓬松波波头假发" />
        <label>平台商品ID</label>
        <input v-model="form.product_id" class="input" placeholder="抖音商品ID" />
        <label>商品链接</label>
        <input v-model="form.product_url" class="input" placeholder="https://..." />
        <label>匹配关键词（逗号分隔）</label>
        <input v-model="form.keywords" class="input" placeholder="假发,Bob,黑色" />
        <div class="modal-actions">
          <button class="btn-secondary" @click="showAddModal = false">取消</button>
          <button class="btn-primary" @click="submitAdd" :disabled="!form.product_name">确认添加</button>
        </div>
      </div>
    </div>

    <!-- Bulk Import Modal -->
    <div v-if="showBulkModal" class="modal-overlay" @click.self="showBulkModal = false">
      <div class="modal modal-lg">
        <h3>批量导入商品</h3>
        <p class="hint">粘贴 JSON 数组，每项包含 product_name（必填）、product_id、product_url、keywords 字段</p>
        <textarea v-model="bulkJson" class="textarea" rows="12" placeholder='[{"product_name":"假发A","product_id":"123","keywords":"假发,卷发"}]'></textarea>
        <div v-if="bulkError" class="error-msg">{{ bulkError }}</div>
        <div class="modal-actions">
          <button class="btn-secondary" @click="showBulkModal = false">取消</button>
          <button class="btn-primary" @click="submitBulk">导入</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getProducts, createProduct, bulkCreateProducts, updateProduct, deleteProduct as apiDelete } from '../api.js'
import { useToast } from '../composables/toast.js'

const { showToast } = useToast()

const products = ref([])
const searchKeyword = ref('')
const showAddModal = ref(false)
const showBulkModal = ref(false)
const editingId = ref(null)
const editKeywords = ref('')
const bulkJson = ref('')
const bulkError = ref('')

const form = ref({ product_name: '', product_id: '', product_url: '', keywords: '' })

async function loadProducts() {
  products.value = await getProducts(searchKeyword.value)
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

async function toggleProduct(p) {
  try {
    await updateProduct(p.id, { enabled: !p.enabled })
    await loadProducts()
  } catch (e) {
    showToast('操作失败: ' + e.message, 'error')
  }
}

async function deleteProduct(id) {
  if (!confirm('确认删除此商品？')) return
  try {
    await apiDelete(id)
    await loadProducts()
    showToast('已删除', 'success')
  } catch (e) {
    showToast('删除失败: ' + e.message, 'error')
  }
}

async function submitAdd() {
  try {
    await createProduct(form.value)
    showAddModal.value = false
    form.value = { product_name: '', product_id: '', product_url: '', keywords: '' }
    await loadProducts()
    showToast('商品已添加', 'success')
  } catch (e) {
    showToast('添加失败: ' + e.message, 'error')
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
    showBulkModal.value = false
    bulkJson.value = ''
    await loadProducts()
    showToast(`成功导入 ${result.created} 个商品`, 'success')
  } catch (e) {
    bulkError.value = '导入失败: ' + e.message
  }
}

onMounted(loadProducts)
</script>

<style scoped>
.page-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.page-header h2 { font-size: 18px; font-weight: 600; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.search-input { background: #1e1e1e; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 6px 12px; font-size: 13px; width: 200px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: #888; font-weight: 500; padding: 10px 12px; border-bottom: 1px solid #2a2a2a; }
td { padding: 10px 12px; border-bottom: 1px solid #1e1e1e; vertical-align: middle; }
tr:hover td { background: #1a1a1a; }
.muted { color: #666; }
.mono { font-family: monospace; font-size: 12px; }
.link { color: #fe2c55; text-decoration: none; }
.link:hover { text-decoration: underline; }
.keywords { cursor: pointer; display: flex; gap: 4px; flex-wrap: wrap; }
.tag { background: #2a2a2a; border: 1px solid #444; border-radius: 4px; padding: 2px 6px; font-size: 11px; }
.badge { border-radius: 4px; padding: 2px 8px; font-size: 11px; }
.badge-green { background: rgba(52,211,153,0.15); color: #34d399; }
.badge-gray { background: #2a2a2a; color: #666; }
.btn-primary { background: #fe2c55; color: #fff; border: none; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-secondary { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; border-radius: 6px; padding: 7px 16px; cursor: pointer; font-size: 13px; }
.btn-xs { background: #2a2a2a; color: #ccc; border: 1px solid #444; border-radius: 4px; padding: 3px 8px; cursor: pointer; font-size: 11px; margin-right: 4px; }
.btn-xs:hover { background: #333; }
.btn-danger { color: #fe2c55; border-color: #fe2c55; }
.btn-danger:hover { background: rgba(254,44,85,0.1); }
.empty { text-align: center; color: #666; padding: 48px; }
.inline-input { background: #1e1e1e; border: 1px solid #555; color: #e0e0e0; border-radius: 4px; padding: 3px 8px; font-size: 12px; width: 180px; margin-right: 4px; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); z-index: 100; display: flex; align-items: center; justify-content: center; }
.modal { background: #1a1a1a; border: 1px solid #333; border-radius: 12px; padding: 24px; width: 420px; max-width: 95vw; }
.modal-lg { width: 600px; }
.modal h3 { font-size: 16px; margin-bottom: 16px; }
label { display: block; font-size: 12px; color: #888; margin: 12px 0 4px; }
.input { width: 100%; background: #111; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 8px 12px; font-size: 13px; }
.textarea { width: 100%; background: #111; border: 1px solid #333; color: #e0e0e0; border-radius: 6px; padding: 8px 12px; font-size: 12px; font-family: monospace; resize: vertical; }
.hint { font-size: 12px; color: #777; margin-bottom: 12px; }
.error-msg { color: #fe2c55; font-size: 12px; margin-top: 8px; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }
</style>
