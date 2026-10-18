// Small additive entry for the deployed SPA, preserving its existing runtime fixes.
const prefix='/api/history-library'
let active=null,lastChange=null
const dialog=document.createElement('dialog')
dialog.setAttribute('aria-label','编辑商品链接')
dialog.style.cssText='width:min(640px,90vw);background:#202020;color:#eee;border:1px solid #555;border-radius:12px;padding:24px;z-index:10000'
const heading=document.createElement('h2');heading.textContent='编辑商品链接'
const name=document.createElement('p')
const hint=document.createElement('p');hint.textContent='找不到可留空；同名不同链接可保留，重复链接不能再次保存。'
const input=document.createElement('input');input.type='url';input.setAttribute('aria-label','商品链接');input.placeholder='粘贴完整商品链接，也可留空';input.style.cssText='box-sizing:border-box;width:100%;padding:12px;background:#111;color:white;border:1px solid #777'
const message=document.createElement('p');message.setAttribute('role','status')
const buttons=document.createElement('div');buttons.style.cssText='display:flex;gap:12px;margin-top:16px'
function button(text,action){const b=document.createElement('button');b.type='button';b.textContent=text;b.style.cssText='padding:8px 12px;cursor:pointer';b.addEventListener('click',action);buttons.append(b);return b}
async function api(path,data){
 const response=await fetch(prefix+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
 const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'操作未完成');return result
}
let busy=false
function setBusy(value){busy=value;save.disabled=value;undo.disabled=value||!lastChange||lastChange.id!==active?.id;close.disabled=value;input.disabled=value}
const save=button('保存链接',async()=>{
 if(busy||!active)return
 setBusy(true);message.textContent='正在保存…'
 try{
  const result=await api(`/products/${active.id}/link`,{product_url:input.value.trim(),expected_before:active.product_url||''})
  active.product_url=result.product_url
  if(result.changed)lastChange={id:active.id,batch:result.batch_id}
  message.textContent='链接已保存。关闭后刷新商品库可查看最新链接。'
 }catch(e){message.textContent=e.message}finally{setBusy(false)}
})
const undo=button('撤销上次链接修改',async()=>{
 if(busy||!lastChange||!active)return
 setBusy(true)
 try{await api(`/product-link-edits/${lastChange.batch}/restore`,{});lastChange=null;active=await api(`/products/${active.id}/link`);input.value=active.product_url||'';message.textContent='已恢复原链接。'}
 catch(e){message.textContent=e.message}finally{setBusy(false)}
})
const close=button('关闭',()=>dialog.close())
dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault()})
dialog.append(heading,name,hint,input,message,buttons);document.body.append(dialog)
async function openEditor(id){
 if(busy)return
 active=null;message.textContent='正在读取商品…';name.textContent='';input.value='';dialog.showModal();setBusy(true)
 try{active=await api(`/products/${id}/link`);name.textContent=`${active.id} · ${active.product_name}`;input.value=active.product_url||'';message.textContent='';input.focus()}
 catch(e){message.textContent=e.message}finally{setBusy(false);save.disabled=!active}
}
function entries(){
 for(const table of document.querySelectorAll('table')){
  const headers=[...table.querySelectorAll('thead th')].map(x=>x.textContent.trim())
  const column=headers.indexOf('商品链接');if(column<0||!headers.includes('平台商品ID'))continue
  for(const row of table.querySelectorAll('tbody tr')){
   const cells=row.querySelectorAll('td'),cell=cells[column],id=cells[0]?.textContent.trim()
   if(!cell||!/^\d+$/.test(id))continue
   let b=cell.querySelector('[data-manual-product-link]')
   if(!b){b=document.createElement('button');b.type='button';b.className='btn-xs';b.dataset.manualProductLink='';b.style.marginLeft='8px';b.addEventListener('click',()=>openEditor(Number(b.dataset.productId)));cell.append(b)}
   b.dataset.productId=id
   const text=cell.querySelector('a[href]')?'编辑链接':'填写链接'
   if(b.textContent!==text)b.textContent=text
  }
 }
}
let scheduled=false
new MutationObserver(()=>{if(!scheduled){scheduled=true;requestAnimationFrame(()=>{scheduled=false;entries()})}}).observe(document.getElementById('app')||document.body,{childList:true,subtree:true})
entries()
