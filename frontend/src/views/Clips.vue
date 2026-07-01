<template>
  <div>
    <div class="toolbar">
      <h2>剪辑文件</h2>
    </div>
    <table class="clips-table">
      <thead>
        <tr>
          <th>剪辑文件名</th>
          <th>原始文件</th>
          <th>房间</th>
          <th>录制时间</th>
          <th>大小</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in clips" :key="c.id">
          <td class="filename">{{ c.clip_filename?.split('/').pop() }}</td>
          <td class="filename dim">{{ c.filename }}</td>
          <td>{{ c.room_name }}</td>
          <td>{{ fmtTime(c.start_time) }}</td>
          <td>{{ c.clip_size != null ? formatBytes(c.clip_size) : '—' }}</td>
          <td>
            <div class="actions">
              <a :href="`${apiBase}/api/recordings/${c.id}/clip`" class="badge purple">下载剪辑</a>
              <button class="badge dim btn-action" @click="doReveal(c)">打开位置</button>
            </div>
          </td>
        </tr>
        <tr v-if="clips.length === 0">
          <td colspan="6" class="empty">暂无已完成的剪辑</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getClips, revealClip, formatBytes } from '../api.js'
import { useToast } from '../composables/toast.js'

const { show } = useToast()
const clips = ref([])
const apiBase = import.meta.env.DEV ? 'http://localhost:8899' : 'http://localhost:8899'
const fmtTime = (s) => s ? new Date(s).toLocaleString('zh-CN') : '—'

async function load() {
  try { clips.value = await getClips() }
  catch (e) { show(e.message || '加载失败', 'error') }
}

async function doReveal(c) {
  try { await revealClip(c.id) }
  catch (e) { show(e.message || '打开失败', 'error') }
}

onMounted(load)
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.toolbar h2 { font-size: 16px; font-weight: 600; }
.clips-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.clips-table th { text-align: left; padding: 10px 14px; color: #666; font-weight: 500; border-bottom: 1px solid #222; }
.clips-table td { padding: 12px 14px; border-bottom: 1px solid #1e1e1e; }
.clips-table tr:hover td { background: #1a1a1a; }
.filename { font-family: monospace; font-size: 12px; color: #aaa; }
.filename.dim { color: #555; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; text-decoration: none; display: inline-block; }
.badge.purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.badge.purple:hover { filter: brightness(1.3); }
.badge.dim { background: #2a2a2a; color: #555; }
.btn-action { cursor: pointer; border: none; font-family: inherit; }
.actions { display: flex; gap: 6px; align-items: center; }
.empty { text-align: center; color: #444; padding: 40px; }
</style>
