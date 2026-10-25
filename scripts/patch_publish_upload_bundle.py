"""Add the isolated finished-video uploader to the existing production picker."""
from pathlib import Path
import hashlib
from patch_publish_loading import once
EXPECTED='0df6aa886cec5d40ba17e35c0b763d635edc960e70bd600f9e5bb03c062dd210'


def patch(source):
    assert hashlib.sha256(source.encode()).hexdigest()==EXPECTED,'Production frontend drift'
    helper=(Path(__file__).parents[1]/'frontend/src/publishVideoUpload.mjs').read_text().replace('export function','function')
    adapter='''let manualPublishUpload=createPublishVideoUploader({ref:z,isBusy:()=>codexPublishBatch.submitting.value||codexPublishBatch.busy.value||ie.value,
 upload:(file,progress,signal)=>uploadPublishVideoRequest(Q+'/api/publish-videos/upload',file,progress,signal),
 addGroup:group=>{ee.value=[group,...ee.value.filter(item=>item.id!==group.id)];if(!te.value.some(room=>room.id===group.room_id))te.value=[...te.value,{id:group.room_id,name:group.room_name,url:'__custom__'}];ne.value=group.room_id;codexPublishBatch.query.value='';if(!codexPublishBatch.ids.value.includes(group.id))codexPublishBatch.toggle(group);}
});
'''
    source=once(source,'return Qn(async()=>{C();',adapter+'return Qn(async()=>{C();')
    source=once(source,'function gt(){if(publishGroupsLoad)return publishGroupsLoad;w.value=!0;', 'function gt(){if(publishGroupsLoad)return publishGroupsLoad;const uploadRevision=manualPublishUpload.revision.value;w.value=!0;')
    source=once(source,'ee.value=items.filter(st)', 'ee.value=manualPublishUpload.mergeGroups(items.filter(st),uploadRevision)')

    panel='''K('section',{style:{padding:'12px',border:'1px solid #444',borderRadius:'8px',marginBottom:'12px'}},[
 K('label',{for:'publish-manual-video'},'手动上传视频（可多选）'),
 K('input',{id:'publish-manual-video',type:'file',accept:'.mp4,.mov,video/mp4,video/quicktime',multiple:true,'aria-label':'上传发布视频',disabled:manualPublishUpload.busy.value||codexPublishBatch.submitting.value||ie.value,onChange:event=>{const files=Array.from(event.target.files||[]);event.target.value='';manualPublishUpload.uploadFiles(files)},style:{display:'block',maxWidth:'100%',margin:'8px 0'}},null,8,['disabled']),
 K('div',{class:'muted',style:{fontSize:'12px'}},'上传成片原样用于发布：15–300秒，MP4/MOV，单个不超过1000MB；成功后自动加入“自定义上传”并选中。'),
 K('div',{role:'status',style:{fontSize:'12px',marginTop:'6px'}},manualPublishUpload.status.value,1),
 manualPublishUpload.busy.value?K('button',{type:'button',class:'btn-xs',onClick:manualPublishUpload.cancel},'取消上传'):J('',true),
 ...manualPublishUpload.errors.value.map(error=>K('div',{role:'alert',style:{color:'#f59e0b',fontSize:'12px'}},error,1))]),'''
    source=once(source,"K('fieldset',{disabled:codexPublishBatch.submitting.value,",panel+"K('fieldset',{disabled:codexPublishBatch.submitting.value||manualPublishUpload.busy.value,")
    source=once(source,'onClick:t[38]||=Z(e=>!codexPublishBatch.submitting.value&&(l.value=false)', 'onClick:t[38]||=Z(e=>!codexPublishBatch.submitting.value&&!manualPublishUpload.busy.value&&(l.value=false)')
    source=once(source,"room.url === '__codex_completed__' || room.name === 'codex 成片'", "room.url === '__codex_completed__' || room.name === 'codex 成片' || room.url === '__custom__' || room.name === '自定义上传'")
    source=once(source,'e.editing_mode===`codex`?e.label:e.hair_display||e.label', '(e.editing_mode===`codex`||e.editing_mode===`manual_upload`)?e.label:e.hair_display||e.label')
    source=once(source,'e.editing_mode!==`codex`&&e.hair_feature?', 'e.editing_mode!==`codex`&&e.editing_mode!==`manual_upload`&&e.hair_feature?')
    contrast="\nif(!document.getElementById('publish-upload-contrast')){const style=document.createElement('style');style.id='publish-upload-contrast';style.textContent='.group-item-custom.group-item-selected .group-item-name{color:#fff!important}.group-item-custom.group-item-selected .group-item-sub{color:#ddd!important}';document.head.append(style)}\n"
    return source+'\n'+helper+contrast
