// Targeted update of the deployed Publish view. Other drifted views stay byte-identical.
import fs from 'node:fs'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { parse } = require('../frontend/node_modules/@babel/parser')
const parseJS = source => parse(source, { sourceType: 'module' })
function walk(node, fn) {
  if (!node || typeof node !== 'object') return
  if (typeof node.type === 'string') fn(node)
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'extra', 'comments', 'tokens'].includes(key)) continue
    if (Array.isArray(value)) value.forEach(child => walk(child, fn))
    else if (value && typeof value === 'object') walk(value, fn)
  }
}
function setupOf(source) {
  let setup
  walk(parseJS(source), node => {
    if (node.type === 'ObjectExpression' && node.properties.some(p => p.key?.name === '__name' && literal(p.value) === 'Publish')) {
      setup = node.properties.find(p => p.type === 'ObjectMethod' && p.key.name === 'setup')
    }
  })
  if (!setup) throw Error('Publish setup missing')
  return setup
}
function apply(source, edits) {
  const sorted = [...edits].sort((a, b) => b.start - a.start)
  let boundary = source.length + 1
  for (const edit of sorted) {
    if (edit.end > boundary) throw Error('Overlapping bundle edits')
    source = source.slice(0, edit.start) + edit.text + source.slice(edit.end)
    boundary = edit.start
  }
  parseJS(source)
  return source
}
function unique(items, name) { if (items.length !== 1) throw Error(`${name}: expected one, found ${items.length}`); return items[0] }
const literal = node => node?.type === 'StringLiteral' ? node.value : node?.type === 'TemplateLiteral' && !node.expressions.length ? node.quasis[0].value.cooked : null
const prop = (node, key) => node?.properties?.find(p => (p.key?.name || p.key?.value) === key)
const adapter = `
let codexPublishBatch=codexCreatePublishSelection({
 ref:z,getForm:()=>I.value,setForm:form=>{I.value=form},getGroups:()=>ee.value,
 getExtras:()=>({version:O.value,schemes:oe.value,scheme:se.value,matched:ae.value}),
 setExtras:state=>{O.value=state.version;oe.value=state.schemes;se.value=state.scheme;ae.value=state.matched},
 getShared:()=>({platform:I.value.platform,account_id:I.value.account_id,scheduled_at:A.value==='later'?tt():null,interval_minutes:de.value}),
 defaultVersion:g=>g.publish_versions&&g.publish_versions!=='both'?g.publish_versions:(['codex','qianchuan','conservative','realistic','director','creative','classic'].find(v=>g[v+'_status']===2&&g[v+'_available'])||'classic'),
 createTask:body=>codexPostPublishTask(Q+'/api/publish-tasks',body),loadTasks:ft,toast:t,editingBusy:()=>ie.value,
 onComplete:()=>{l.value=false;I.value={group_id:'',platform:'douyin',account_id:T.value.find(a=>a.account_name==='颜遇生活')?.id||'',title:'',description:'',tags:'',product_ids:[],no_cart:false};ae.value=null}
});
const codexOriginalMeta=Zt,codexOriginalMatch=en;
Zt=()=>codexPublishBatch.runEditing(codexOriginalMeta);
en=()=>codexPublishBatch.runEditing(codexOriginalMatch);
An(l,opened=>{if(opened)codexPublishBatch.adopt();else codexPublishBatch.clear()});
`
export function patchPublishBundle(source, helper) {
  if (source.includes('codexCreatePublishSelection')) throw Error('Already patched')
  const setup = setupOf(source), nodes = []
  walk(setup.body, n => nodes.push(n))
  const scope = source.slice(setup.start, setup.end)
  for (const anchor of ['I=z({', 'O=z(`both`)', 'ee=z([])', 'ne=z(1)', 'async function tn()', 'async function Zt()', 'async function en()', 'async function ft()', 'await Cs(e)']) {
    if (!scope.includes(anchor)) throw Error(`Production binding drift: ${anchor}`)
  }
  const edits = []
  const fn = unique(nodes.filter(n => n.type === 'FunctionDeclaration' && n.id.name === 'tn'), 'submit')
  edits.push({ start: fn.start, end: fn.end, text: 'async function tn(){await codexPublishBatch.submit()}' })
  const filter = unique(nodes.filter(n => n.type === 'VariableDeclarator' && n.id.name === 'Xe'), 'group filter')
  const body = filter.init.arguments[0].body
  edits.push({ start: body.start, end: body.end, text: `(${source.slice(body.start, body.end)}).filter(g=>codexPublishBatch.matches(g))` })
  const row = unique(nodes.filter(n => n.type === 'CallExpression' && ['K', 'G'].includes(n.callee.name) && literal(n.arguments[0]) === 'div' && n.arguments[1]?.type === 'ObjectExpression' && prop(n.arguments[1], 'class') && source.slice(prop(n.arguments[1], 'class')?.start, prop(n.arguments[1], 'class')?.end).includes('`group-item`')), 'group row')
  const click = prop(row.arguments[1], 'onClick').value
  edits.push({ start: click.start, end: click.end, text: '()=>codexPublishBatch.focus(e)' })
  const cls = prop(row.arguments[1], 'class').value
  const oldClass = source.slice(cls.start, cls.end)
  if (!oldClass.includes('I.value.group_id===e.id')) throw Error('Selected row drift')
  edits.push({ start: cls.start, end: cls.end, text: oldClass.replace('I.value.group_id===e.id', 'codexPublishBatch.ids.value.includes(e.id)') })
  const children = row.arguments[2]
  if (children.type !== 'ArrayExpression') throw Error('Row children drift')
  edits.push({ start: children.start + 1, end: children.start + 1, text: "K('input',{type:'checkbox',style:{float:'left',marginRight:'8px',width:'16px',height:'16px',accentColor:'#fe2c55'},checked:codexPublishBatch.ids.value.includes(e.id),disabled:codexPublishBatch.submitting.value||codexPublishBatch.busy.value||ie.value,'aria-label':'选择视频 '+e.label,onClick:event=>{event.stopPropagation();codexPublishBatch.toggle(e)}},null,8,['checked','disabled'])," })
  const submit = unique(nodes.filter(n => n.type === 'CallExpression' && literal(n.arguments[0]) === 'button' && prop(n.arguments[1], 'onClick')?.value?.name === 'tn'), 'submit button')
  edits.push({ start: submit.start, end: submit.end, text: "K('button',{class:'btn-primary',onClick:tn,disabled:!codexPublishBatch.ids.value.length||!I.value.platform||codexPublishBatch.submitting.value||codexPublishBatch.busy.value},codexPublishBatch.submitting.value?'正在创建…':'创建 '+codexPublishBatch.ids.value.length+' 个发布任务',9,['disabled'])" })
  let chips = 0
  for (const n of nodes) {
    if (n.type !== 'ArrowFunctionExpression' || n.body.type !== 'BlockStatement') continue
    const text = source.slice(n.body.start, n.body.end)
    if (!/^\{ne\.value=(?:0|e\.id),I\.value\.group_id=``[,]I\.value\.product_ids=\[\]\}$/.test(text)) continue
    const expr = text.slice(1).split(',')[0]
    edits.push({ start: n.body.start, end: n.body.end, text: `{${expr}}` }); chips++
  }
  if (chips !== 2) throw Error(`Room chips drift: ${chips}`)
  const ret = setup.body.body.find(n => n.type === 'ReturnStatement')
  if (!ret) throw Error('Render return missing')
  edits.push({ start: ret.start, end: ret.start, text: adapter })
  // Closing while submitting would erase pending/failed drafts.
  for (const n of nodes) {
    if (n.start < ret.start || n.type !== 'AssignmentExpression') continue
    if (source.slice(n.left.start, n.left.end) === 'l.value' && source.slice(n.right.start, n.right.end) === '!1') {
      edits.push({ start: n.start, end: n.end, text: '!codexPublishBatch.submitting.value&&(l.value=false)' })
    }
  }
  source = apply(source, edits)
  // Add search and selected-video editor navigation around the existing list.
  let lists = []
  walk(setupOf(source).body, n => { if (n.type === 'CallExpression' && n.callee.name === 'K' && literal(n.arguments[0]) === 'div' && n.arguments[1]?.name === 'Nb') lists.push(n) })
  const list = unique(lists, 'list wrapper')
  const controls = `K('input',{class:'input',type:'search',placeholder:'搜索视频/发型/颜色/分组编号，空格组合搜索','aria-label':'搜索分组视频',value:codexPublishBatch.query.value,onInput:event=>codexPublishBatch.query.value=event.target.value,style:{width:'100%',boxSizing:'border-box'}},null,8,['value']),
K('div',{style:{fontSize:'12px',margin:'8px 0'}},'已选 '+codexPublishBatch.ids.value.length+' 个视频；点击名称逐条编辑文案和商品，空白文案会分别自动生成。',1),
K('div',{class:'room-filter-chips',style:{display:'flex',gap:'6px',flexWrap:'wrap',marginBottom:'8px'}},codexPublishBatch.ids.value.map(id=>K('button',{type:'button',class:['room-chip',I.value.group_id===id?'active':''],onClick:()=>codexPublishBatch.focus(ee.value.find(g=>g.id===id))},'编辑 '+(ee.value.find(g=>g.id===id)?.label||id),1))),
K('button',{type:'button',class:'btn-xs',onClick:()=>codexPublishBatch.clear(),disabled:codexPublishBatch.submitting.value},'清空选择',8,['disabled']),
K('div',{'aria-live':'polite'},codexPublishBatch.errors.value.map(error=>K('div',{role:'alert',style:{color:'#f59e0b',fontSize:'12px'}},'分组 '+error.id+'：'+error.message+'（成功项不会重复提交）',1)))`
  source = apply(source, [{ start: list.start, end: list.end, text: `K('div',null,[${controls},${source.slice(list.start, list.end)}])` }])
  const empty = source.indexOf('`暂无已合并分组`', setupOf(source).start)
  if (empty < 0) throw Error('Empty label drift')
  source = source.slice(0, empty) + "(codexPublishBatch.query.value.trim()?'未找到匹配的视频，请更换关键词':'暂无已合并分组')" + source.slice(empty + '`暂无已合并分组`'.length)
  // Disable inputs during submission, reusing the existing complete form.
  let modals = []
  walk(setupOf(source).body, n => { if (n.type === 'CallExpression' && n.callee.name === 'K' && literal(n.arguments[0]) === 'div' && n.arguments[1]?.name === 'Ob') modals.push(n) })
  const modal = unique(modals, 'create modal'), array = modal.arguments[2]
  if (array.type !== 'ArrayExpression') throw Error('Modal children drift')
  const [title, ...rest] = array.elements
  source = apply(source, [{ start: array.start, end: array.end, text: `[${source.slice(title.start, title.end)},K('fieldset',{disabled:codexPublishBatch.submitting.value,style:{border:0,padding:0,margin:0,minWidth:0}},[${rest.map(n => source.slice(n.start, n.end)).join(',')}],8,['disabled'])]` }])
  // The deployed render has compiler-generated block arrays. New controls have
  // variable cardinality, so opt this view out of that optimization via Vue's
  // standard block-tracking helper instead of corrupting dynamic-child indexes.
  if (!source.includes('function Oi(e,t=!1){Di+=e,e<0&&Ti&&t&&(Ti.hasOnce=!0)}')) throw Error('Vue block tracking binding drift')
  const returned = setupOf(source).body.body.find(n => n.type === 'ReturnStatement').argument
  const render = returned.type === 'SequenceExpression' ? returned.expressions.at(-1) : returned
  if (render.type !== 'ArrowFunctionExpression') throw Error('Render closure drift')
  source = apply(source, [{ start: render.start, end: render.end, text: `(...codexRenderArgs)=>{Oi(-1);try{return (${source.slice(render.start, render.end)})(...codexRenderArgs)}finally{Oi(1)}}` }])
  const standalone = helper.replace(/^export /gm, '')
  source += '\n' + standalone
  parseJS(source)
  return source
}
if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split('/').pop())) {
  const [input, output] = process.argv.slice(2)
  const helper = fs.readFileSync(new URL('../frontend/src/publishSelection.mjs', import.meta.url), 'utf8')
  fs.writeFileSync(output, patchPublishBundle(fs.readFileSync(input, 'utf8'), helper))
  console.log(`Patched Publish view: ${output}`)
}
