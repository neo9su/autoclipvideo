import assert from 'node:assert/strict'
import {createPublishVideoUploader} from '../src/publishVideoUpload.mjs'
import {codexCreatePublishSelection} from '../src/publishSelection.mjs'
const ref=value=>({value})
const groups=[{id:1,publish_versions:'classic'}]
let form={group_id:1,platform:'douyin',account_id:2,title:'已有标题',description:'共享描述',tags:'共享标签',product_ids:[7,8],no_cart:false},extras={version:'classic'}
const selection=codexCreatePublishSelection({ref,getForm:()=>form,setForm:value=>{form=value},getGroups:()=>groups,getExtras:()=>extras,setExtras:value=>{extras=value},getShared:()=>({platform:form.platform,account_id:form.account_id}),defaultVersion:()=> 'classic'})
selection.adopt()
let calls=0
const uploader=createPublishVideoUploader({ref,isBusy:()=>false,
 upload:async(file,progress)=>{calls++;progress(100);if(file.name==='bad.mp4')throw Error('坏视频');return {group:{id:2,publish_versions:'classic'},reused:calls>1}},
 addGroup:group=>{if(!groups.some(item=>item.id===group.id))groups.push(group);if(!selection.ids.value.includes(group.id))selection.toggle(group)}})
await uploader.uploadFiles([{name:'成片.mp4',size:5},{name:'bad.mp4',size:5},{name:'same.mp4',size:5},{name:'bad.exe',size:5}])
assert.deepEqual(selection.ids.value,[1,2]);assert.equal(calls,3);assert.equal(uploader.errors.value.length,2);assert.equal(uploader.completed.value.length,2)
assert.equal(form.description,'共享描述');assert.equal(form.tags,'共享标签');assert.deepEqual(form.product_ids,[7,8]);assert.equal(form.account_id,2);assert.equal(uploader.busy.value,false)
// User cancellation stops remaining files, while an earlier successful upload stays selected.
let rejectCurrent,started
const start=new Promise(resolve=>started=resolve)
const cancelling=createPublishVideoUploader({ref,isBusy:()=>false,upload:(file,progress,signal)=>new Promise((resolve,reject)=>{started();rejectCurrent=()=>reject(Error('取消'));signal.addEventListener('abort',rejectCurrent)}),addGroup:()=>assert.fail('cancelled')})
const pending=cancelling.uploadFiles([{name:'x.mp4',size:1},{name:'y.mp4',size:1}]);await start;cancelling.cancel();await pending;assert.equal(cancelling.errors.value.length,1);assert.equal(cancelling.busy.value,false)
console.log('Multi-upload, partial failure, duplicate selection, shared copy/cart and cancel passed')

const {catalogRoomProducts}=await import('../src/publishCatalog.mjs');assert.equal(catalogRoomProducts([{id:7,enabled:1,product_url:'https://shop/1',room_id:1},{id:8,enabled:1,product_url:'https://shop/2',room_id:2}],8,[{id:8,url:'__custom__',name:'自定义上传'}]).length,2);
