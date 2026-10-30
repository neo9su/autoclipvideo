import fs from 'node:fs'
import { createRequire } from 'node:module'
const require=createRequire(import.meta.url),{parse}=require('../frontend/node_modules/@babel/parser')
function walk(n,f){if(!n||typeof n!=='object')return;if(n.type)f(n);for(const v of Object.values(n)){if(Array.isArray(v))v.forEach(x=>walk(x,f));else if(v&&typeof v==='object')walk(v,f)}}
export function patchCatalogBundle(source,helper){
  if(source.includes('codexCatalogSearchProducts'))throw Error('Already patched')
  let setup;walk(parse(source,{sourceType:'module'}),n=>{if(n.type==='ObjectExpression'&&n.properties.some(p=>p.key?.name==='__name'&&(p.value?.value==='Publish'||p.value?.quasis?.[0]?.value.cooked==='Publish')))setup=n.properties.find(p=>p.type==='ObjectMethod'&&p.key.name==='setup')})
  if(!setup)throw Error('Publish setup missing');const nodes=[];walk(setup.body,n=>nodes.push(n))
  const matches=nodes.filter(n=>n.type==='FunctionDeclaration'&&n.id?.name==='en'),filters=nodes.filter(n=>n.type==='VariableDeclarator'&&n.id?.name==='$e');if(matches.length!==1||filters.length!==1)throw Error('Binding drift')
  const fn=matches[0],filter=filters[0].init.arguments[0].body
  if(!source.slice(fn.start,fn.end).includes('Ps(I.value.group_id)')||!source.slice(filter.start,filter.end).includes('Qe.value.trim()'))throw Error('Body drift')
  const edits=[{start:fn.start,end:fn.end,text:`async function en(){if(!I.value.group_id)return;try{let r=await fetch(Q+'/api/groups/'+I.value.group_id+'/match-product?q='+encodeURIComponent(Qe.value),{method:'POST'});if(!r.ok)throw Error(await r.text());let e=await r.json(),a=e.products||(e.product?[e.product]:[]);if(a.length){ae.value=a[0];I.value.product_ids=a.map(p=>p.id);t('已匹配 '+a.length+' 件商品'+(a.length>10?'，本系统最多选择10件，请减少选择后创建':''),a.length>10?'info':'success')}else t('未找到匹配商品','info')}catch(e){t('匹配失败: '+e.message,'error')}}`},
  {start:filter.start,end:filter.end,text:'codexCatalogSearchProducts(F.value,Qe.value)'}]
  for(const edit of edits.sort((a,b)=>b.start-a.start))source=source.slice(0,edit.start)+edit.text+source.slice(edit.end)
  source+='\n'+helper.replace('export function catalogSearchProducts','function codexCatalogSearchProducts')
  parse(source,{sourceType:'module'});return source
}
if(process.argv[1]?.endsWith('patch_publish_catalog_bundle.mjs')&&process.argv[2])fs.writeFileSync(process.argv[3],patchCatalogBundle(fs.readFileSync(process.argv[2],'utf8'),fs.readFileSync(new URL('../frontend/src/publishCatalog.mjs',import.meta.url),'utf8')))
