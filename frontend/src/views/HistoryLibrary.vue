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
    <div class="controls"><input v-model="evidenceId" :disabled="busy" placeholder="录像ID" @input="evidence=null;homophones=null" /><button :disabled="busy" @click="inspectEvidence">读取口播证据</button></div>
    <p v-if="evidence">字幕 {{ evidence.cue_count }} 条，名称提及 {{ evidence.mention_count }} 处{{ evidence.truncated?'（显示前500处）':'' }}；时间均为原录像时间。</p>
    <table v-if="evidence"><thead><tr><th>源时间</th><th>发型名称候选</th><th>口播原文及上下文</th><th>判断</th></tr></thead>
      <tbody><tr v-for="(m,i) in evidence.mentions" :key="i"><td>{{ clock(m.start_sec) }}–{{ clock(m.end_sec) }}</td><td>{{ m.hairstyle_name }}</td><td>{{ m.context }}</td><td>{{ m.current_assertion?'当前介绍候选，画面待确认':'仅提及，不能确定当前款' }}</td></tr></tbody></table>
    <h3>疑似同音名称复核</h3>
    <p>使用上方录像ID和原录像秒数，每次最多10分钟。只列出同音线索；请核对原声、画面及商品规格后再判断，不会自动改名或挂车。</p>
    <div class="controls"><input v-model.number="reviewStart" type="number" min="0" step="0.001" aria-label="同音复核开始秒" @input="homophones=null" /><input v-model.number="reviewEnd" type="number" min="0" step="0.001" aria-label="同音复核结束秒" @input="homophones=null" /><button :disabled="busy" @click="inspectHomophones">查找疑似同音名称</button></div>
    <p v-if="homophones">录像 {{ homophones.recording_id }}，{{ clock(homophones.start_sec) }}–{{ clock(homophones.end_sec) }}：{{ homophones.candidate_count }} 处线索{{ homophones.truncated?'（显示前500处）':'' }}。无结果不表示没有提到商品。</p>
    <table v-if="homophones?.candidates.length"><thead><tr><th>源时间</th><th>原字幕</th><th>疑似名称</th><th>商品候选与链接</th></tr></thead><tbody>
      <tr v-for="(h,i) in homophones.candidates" :key="i"><td>{{ clock(h.start_sec) }}–{{ clock(h.end_sec) }}</td><td>{{ h.original_text }}<br />疑似误听：{{ h.observed_text }}</td><td>{{ h.hairstyle_name }}<br />待原声及画面复核</td><td><div v-for="p in h.product_candidates" :key="p.id">{{ p.id }} · {{ p.product_name }} <a v-if="productHref(p.product_url)" :href="productHref(p.product_url)" target="_blank" rel="noopener noreferrer">查看商品</a><span v-else> · 未绑定有效链接</span></div></td></tr>
    </tbody></table>
    <h3>分段计划登记（待视觉复核）</h3>
    <p>使用上方口播时间线的录像ID登记源时间区间。保存会读取原片生成内容校验值，不复制或切割原片；这里录入的名称与特征不会自动成为同款确认。</p>
    <div class="controls"><input v-model.number="draft.start_sec" type="number" min="0" step="0.001" placeholder="源开始秒" aria-label="源开始秒" /><input v-model.number="draft.end_sec" type="number" min="0" step="0.001" placeholder="源结束秒" aria-label="源结束秒" /></div>
    <div class="controls"><input v-model="draft.wig" placeholder="发型名称" aria-label="发型名称" /><input v-model="draft.color" placeholder="颜色" aria-label="颜色" /><input v-model="draftFeatures" placeholder="特征，逗号分隔" aria-label="特征" /></div>
    <div class="controls"><input v-model="draft.current_evidence" placeholder="支持当前展示款的口播原话" aria-label="口播原话" /><button :disabled="busy" @click="saveArchive">保存待复核分段计划</button><button :disabled="busy" @click="refreshArchive">查看最近计划</button></div>
    <p v-if="archiveMessage">{{ archiveMessage }}</p>
    <div v-for="p in archivePlans" :key="p.plan_id" class="batch">
      <span>录像 {{ p.recording_id }} · {{ p.document.segments.length }} 个区间 · {{ p.state==='withdrawn'?'已撤销':p.document.segments.every(s=>s.status==='ready')?'身份已核验':'待视觉复核' }} · 原片已校验，分段计划<br /><span v-for="s in p.document.segments" :key="s.segment_id">{{ clock(s.start_sec) }}–{{ clock(s.end_sec) }} · {{ s.hairstyle_name }} {{ s.color }} {{ s.features?.join(' / ') }} · {{ s.transcript_evidence?.verified?'口播已核对':'口播待核对' }}；{{ s.status==='ready'?'画面已核验':'画面待确认' }}<br /></span></span>
      <button :disabled="busy || p.state!=='active' || !p.document.segments.every(s=>s.status==='ready')" @click="exportArchive(p)">按源时间导出片段</button>
      <button :disabled="busy" @click="changeArchive(p)">{{ p.state==='withdrawn'?'恢复计划':'撤销计划' }}</button>
    </div>
    <h3>已导出的原片分段</h3>
    <p v-if="!exportBatches.length">暂无导出批次。候选计划待视觉核验后才能执行；此处生成的是按款归档素材，不是广告成片。</p>
    <div v-for="b in exportBatches" :key="b.batch_id" class="batch"><span>{{ b.files }} 个片段 · {{ exportStates[b.state] || b.state }}</span>
      <button v-if="['complete','failed','prepared','withdrawing'].includes(b.state)" :disabled="busy" @click="changeExport(b,'withdraw')">撤回此批片段</button>
      <button v-if="b.state==='withdrawn' && b.can_restore" :disabled="busy" @click="changeExport(b,'restore')">恢复完整批次</button>
      <button v-if="b.can_retry" :disabled="busy" @click="changeExport(b,'retry')">保留旧结果并重试</button>
      <button v-if="b.state==='prepared'" :disabled="busy" @click="changeExport(b,'recover')">检查并恢复落位</button>
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
const evidenceId=ref(''), evidence=ref(null)
const reviewStart=ref(0),reviewEnd=ref(600),homophones=ref(null)
function productHref(value){try{const u=new URL(value);return ['http:','https:'].includes(u.protocol)?u.href:''}catch{return ''}}
function inspectHomophones(){return action(async()=>{
  const id=Number(evidenceId.value),start=reviewStart.value,end=reviewEnd.value
  if(!Number.isSafeInteger(id)||id<=0)throw new Error('请输入一个有效录像ID')
  if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end-start>600)throw new Error('请输入有效时间，单次最多600秒')
  homophones.value=null;homophones.value=await request(`/recordings/${id}/homophone-review`,{start_sec:start,end_sec:end})
})}
const exportBatches=ref([]), exportStates={complete:'已完成',prepared:'等待完成核验',failed:'未完成，临时结果保留',withdrawn:'已撤回',withdrawing:'撤回待恢复',retrying:'重试待恢复'}
function exportArchive(p){return action(async()=>{
  archiveMessage.value='正在按源时间切片并校验，原片保留…'
  try{await request(`/archive-exports/${p.plan_id}/create`,{});archiveMessage.value='片段已生成，来源清单已保存。';await loadArchive()}catch(e){archiveMessage.value='';throw e}
})}
function changeExport(b,actionName){return action(async()=>{await request(`/archive-exports/${b.batch_id}/${actionName}`,{});await loadArchive()})}
const draft=ref({start_sec:0,end_sec:0,wig:'',color:'',current_evidence:''}), draftFeatures=ref(''), archivePlans=ref([]), archiveMessage=ref('')
async function loadArchive(){archivePlans.value=await request('/archive-plans');exportBatches.value=await request('/archive-exports')}
function refreshArchive(){return action(loadArchive)}
function saveArchive(){return action(async()=>{
  const id=Number(evidenceId.value)
  if(!Number.isSafeInteger(id)||id<=0)throw new Error('请先在口播时间线输入有效录像ID')
  if(!Number.isFinite(draft.value.start_sec)||!Number.isFinite(draft.value.end_sec)||draft.value.start_sec<0||draft.value.end_sec<=draft.value.start_sec)throw new Error('请输入有效源时间区间（秒）')
  const body={boundaries:[{...draft.value,features:draftFeatures.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean)}]}
  archiveMessage.value='正在校验原片并保存计划，大文件需要一些时间…'
  try{
    const result=await request(`/recordings/${id}/archive-plan`,body)
    archiveMessage.value=`计划已保存：${result.document.segments.length} 个区间，待视觉复核；原片未复制或切割。`
    await loadArchive()
  }catch(e){archiveMessage.value='';throw e}
})}
function changeArchive(p){return action(async()=>{await request(`/archive-plans/${p.plan_id}/${p.state==='withdrawn'?'restore':'withdraw'}`,{});await loadArchive()})}
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
onMounted(()=>action(async()=>{await refresh();await loadArchive();names.value=await request('/catalogue-names')}))
</script>
<style scoped>
.controls,.batch{display:flex;gap:16px;align-items:center;margin:16px 0}table{width:100%;text-align:left;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #333}p{color:#aaa}button,select{padding:8px} [role=alert]{color:#ff7070}
</style>
