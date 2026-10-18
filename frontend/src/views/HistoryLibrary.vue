<template>
  <section>
    <h2>历史素材库</h2>
    <p>清理三个自然月以前的旧成片及分组。原录像保留，清理结果可在下方恢复。</p>
    <div class="controls">
      <select v-model="mode" @change="plan = null">
        <option value="all">全部</option><option value="published">已发布</option><option value="unpublished">未发布</option>
      </select>
      <button :disabled="busy" @click="preview">预览清理范围</button>
      <button :disabled="busy || !plan?.count" @click="apply">清理预览中的旧成片与分组</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="plan">截止 {{ plan.cutoff.slice(0,10) }}：{{ plan.count }} 个分组，{{ size(plan.bytes) }}。文件移入可恢复区，暂不释放磁盘空间。</p>
    <table v-if="plan?.count"><thead><tr><th>分组</th><th>名称</th><th>发布状态</th><th>文件数</th></tr></thead>
      <tbody><tr v-for="g in plan.groups" :key="g.id"><td>{{ g.id }}</td><td>{{ g.label }}</td><td>{{ g.published ? '已发布' : '未发布' }}</td><td>{{ g.files }}</td></tr></tbody>
    </table>
    <h3>可恢复的清理批次</h3>
    <p v-if="!batches.length">暂无清理记录</p>
    <div v-for="b in batches" :key="b.batch_id" class="batch">
      <span>{{ b.count }} 个分组 · {{ size(b.bytes) }} · {{ b.state === 'restored' ? '已恢复' : '可恢复' }}</span>
      <button v-if="['quarantined','prepared'].includes(b.state)" :disabled="busy" @click="restore(b)">恢复此批次</button>
    </div>
    <h3>商品发型名预览</h3>
    <p>按商品名提取主播命名。同名商品保留各自商品记录，颜色和规格在素材分段时另行区分。</p>
    <table><thead><tr><th>商品</th><th>发型名称候选</th><th>商品全名</th></tr></thead>
      <tbody><tr v-for="p in names" :key="p.id"><td>{{ p.id }}</td><td>{{ p.name || '需确认' }}</td><td>{{ p.product_name }}</td></tr></tbody>
    </table>
  </section>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { remoteFetch } from '../remoteApi.js'
const mode=ref('all'), plan=ref(null), batches=ref([]), names=ref([]), busy=ref(false), error=ref('')
const size=v=>`${(v/1024**3).toFixed(2)} GB`
async function request(path, data) {
  const r=await remoteFetch('/api/history-library'+path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}, 0)
  const d=await r.json(); if(!r.ok) throw new Error(typeof d.detail==='string'?d.detail:'操作失败'); return d
}
async function action(fn) { busy.value=true;error.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false} }
async function refresh(){batches.value=await request('/cleanup/batches')}
function preview(){return action(async()=>{plan.value=await request('/cleanup/preview',{mode:mode.value})})}
function apply(){
  if(!confirm(`将 ${plan.value.count} 个分组及旧成片移入可恢复区，是否继续？`))return
  return action(async()=>{await request('/cleanup/apply',{mode:plan.value.mode,cutoff:plan.value.cutoff,fingerprint:plan.value.fingerprint});plan.value=null;await refresh()})
}
function restore(b){return action(async()=>{await request(`/cleanup/${b.batch_id}/restore`,{});await refresh()})}
onMounted(()=>action(async()=>{await refresh();names.value=await request('/catalogue-names')}))
</script>
<style scoped>
.controls,.batch{display:flex;gap:16px;align-items:center;margin:16px 0}table{width:100%;text-align:left;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #333}p{color:#aaa}button,select{padding:8px} [role=alert]{color:#ff7070}
</style>
