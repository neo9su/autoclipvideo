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
    <h3>录像分辨率检查与可恢复弃用</h3>
    <p>输入录像ID（逗号分隔，每批最多100条）。仅处理本机未关联分组的完整录像；正在处理、已有关联或探测失败的文件会跳过。低于1080P的文件移入可恢复区，暂不释放磁盘空间。</p>
    <div class="controls"><input v-model="recordingIds" :disabled="busy" placeholder="录像ID，例如 45259,45260" @input="resolutionPlan=null" />
      <button :disabled="busy" @click="inspectResolution">检查分辨率</button>
      <button :disabled="busy || !resolutionPlan?.count" @click="discardLow">弃用预览中的低清录像</button></div>
    <p v-if="resolutionPlan">可弃用 {{ resolutionPlan.count }} 条，{{ size(resolutionPlan.bytes) }}</p>
    <table v-if="resolutionPlan"><thead><tr><th>录像ID</th><th>文件</th><th>分辨率</th><th>结果</th></tr></thead>
      <tbody><tr v-for="r in resolutionPlan.recordings" :key="r.id"><td>{{ r.id }}</td><td>{{ r.filename }}</td><td>{{ r.width ? `${r.width}×${r.height}` : '未确认' }}</td><td>{{ reasons[r.reason] || r.reason }}</td></tr></tbody></table>
    <div v-for="b in recordingBatches" :key="b.batch_id" class="batch"><span>{{ b.count }} 条低清录像 · {{ b.state==='restored'?'已恢复':b.state==='rolled_back'?'已回退':'可恢复' }}</span>
      <button v-if="['prepared','quarantined'].includes(b.state)" :disabled="busy" @click="restoreRecordings(b)">恢复此批录像</button></div>
    <h3>发型口播时间线</h3>
    <p>输入一条录像ID，核对原始字幕中提到的商品名称及时间。“当前介绍候选”仍需画面确认，不会据此自动切片。</p>
    <div class="controls"><input v-model="evidenceId" :disabled="busy" placeholder="录像ID" @input="evidence=null" /><button :disabled="busy" @click="inspectEvidence">读取口播证据</button></div>
    <p v-if="evidence">字幕 {{ evidence.cue_count }} 条，名称提及 {{ evidence.mention_count }} 处{{ evidence.truncated?'（显示前500处）':'' }}；时间均为原录像时间。</p>
    <table v-if="evidence"><thead><tr><th>源时间</th><th>发型名称候选</th><th>口播原文及上下文</th><th>判断</th></tr></thead>
      <tbody><tr v-for="(m,i) in evidence.mentions" :key="i"><td>{{ clock(m.start_sec) }}–{{ clock(m.end_sec) }}</td><td>{{ m.hairstyle_name }}</td><td>{{ m.context }}</td><td>{{ m.current_assertion?'当前介绍候选，画面待确认':'仅提及，不能确定当前款' }}</td></tr></tbody></table>
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
const evidenceId=ref(''), evidence=ref(null)
const clock=v=>`${Math.floor(v/60)}:${String(Math.floor(v%60)).padStart(2,'0')}`
function inspectEvidence(){return action(async()=>{
  const id=Number(evidenceId.value);if(!Number.isSafeInteger(id)||id<=0)throw new Error('请输入一个有效录像ID')
  evidence.value=null;evidence.value=await request(`/recordings/${id}/hairstyle-evidence`)
})}
const recordingIds=ref(''), resolutionPlan=ref(null), recordingBatches=ref([])
const reasons={below_1080p:'低于1080P，可恢复弃用', '1080p_or_higher':'保留', linked_material:'已关联分组或片段，跳过', active_or_unavailable:'正在处理或不可用，跳过', shared_source:'多个记录引用同一源文件，跳过', missing_or_external_file:'文件不在本机存储或不可用', source_changed:'文件正在变化', probe_failed:'探测失败，待检查', missing_recording:'录像ID不存在'}
let inspectedIds=[]
function inspectResolution(){return action(async()=>{
  const ids=recordingIds.value.split(/[,，\s]+/).filter(Boolean).map(Number)
  if(!ids.length || ids.length>100 || ids.some(n=>!Number.isSafeInteger(n)||n<=0))throw new Error('请输入1至100个有效录像ID')
  resolutionPlan.value=null
  resolutionPlan.value=await request('/recordings/inspect',{recording_ids:ids});inspectedIds=ids
})}
function discardLow(){
  if(!confirm(`将 ${resolutionPlan.value.count} 条低清录像移入可恢复区，是否继续？`))return
  return action(async()=>{await request('/recordings/quarantine',{recording_ids:inspectedIds,fingerprint:resolutionPlan.value.fingerprint});resolutionPlan.value=null;await refresh()})
}
function restoreRecordings(b){return action(async()=>{await request(`/recordings/${b.batch_id}/restore`,{});await refresh()})}
const size=v=>`${(v/1024**3).toFixed(2)} GB`
async function request(path, data) {
  const r=await remoteFetch('/api/history-library'+path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}, 0)
  const d=await r.json(); if(!r.ok) throw new Error(typeof d.detail==='string'?d.detail:'操作失败'); return d
}
async function action(fn) { busy.value=true;error.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false} }
async function refresh(){batches.value=await request('/cleanup/batches');recordingBatches.value=await request('/recordings/batches')}
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
