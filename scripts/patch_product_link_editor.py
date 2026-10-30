"""Patch only the existing product URL cell and its handlers; refuse source drift."""
from pathlib import Path
import argparse

CELL='''            <td class="url-cell">
              <a v-if="p.product_url" :href="p.product_url" target="_blank" rel="noopener" class="link">打开链接</a>
              <span v-else class="link-missing">未绑定</span>
            </td>'''
NEW_CELL='''            <td class="url-cell">
              <div v-if="linkEditingId === p.id">
                <input v-model="linkDraft" class="inline-input" style="width:280px" :disabled="linkSaving" :aria-label="`商品${p.id}链接`" placeholder="粘贴商品链接，也可留空" @keyup.enter="saveProductLink(p)" @keyup.escape="!linkSaving && (linkEditingId=null)" />
                <button class="btn-xs" :disabled="linkSaving" @click="saveProductLink(p)">保存链接</button>
                <button class="btn-xs" :disabled="linkSaving" @click="linkEditingId=null">取消</button>
              </div>
              <div v-else>
                <a v-if="p.product_url" :href="p.product_url" target="_blank" rel="noopener" class="link">打开链接</a>
                <span v-else class="link-missing">未绑定</span>
                <button class="btn-xs" :disabled="linkSaving" @click="startEditProductLink(p)">{{ p.product_url?'编辑链接':'填写链接' }}</button>
                <button v-if="lastLinkChange?.id===p.id" class="btn-xs" :disabled="linkSaving" @click="undoProductLink">撤销上次链接修改</button>
              </div>
            </td>'''
HANDLERS='''
const linkEditingId=ref(null),linkDraft=ref(''),linkBefore=ref(''),linkSaving=ref(false),lastLinkChange=ref(null)
function startEditProductLink(p){linkEditingId.value=p.id;linkDraft.value=p.product_url||'';linkBefore.value=p.product_url||''}
async function linkRequest(path,body){
  const response=await fetch(`${BASE}/api/history-library${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'链接保存失败');return data
}
async function saveProductLink(p){
  if(linkSaving.value)return
  linkSaving.value=true
  try{
    const result=await linkRequest(`/products/${p.id}/link`,{product_url:linkDraft.value.trim(),expected_before:linkBefore.value})
    if(result.changed)lastLinkChange.value={id:p.id,batch:result.batch_id}
    linkEditingId.value=null;await loadProducts();showToast('商品链接已保存','success')
  }catch(e){showToast(e.message,'error')}finally{linkSaving.value=false}
}
async function undoProductLink(){
  if(linkSaving.value||!lastLinkChange.value)return
  linkSaving.value=true
  try{await linkRequest(`/product-link-edits/${lastLinkChange.value.batch}/restore`,{});lastLinkChange.value=null;await loadProducts();showToast('已恢复原链接','success')}
  catch(e){showToast(e.message,'error')}finally{linkSaving.value=false}
}
'''


def patch(source):
    anchor="const editingId = ref(null)"
    if source.count(CELL)!=1 or source.count(anchor)!=1 or 'linkEditingId' in source:
        raise ValueError('Unexpected Products.vue source; inspect before patching')
    return source.replace(CELL,NEW_CELL,1).replace(anchor,anchor+'\n'+HANDLERS,1)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    with a.output.open('x',encoding='utf-8') as f:f.write(patch(a.source.read_text(encoding='utf-8')))
