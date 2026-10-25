import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import {publishPickerRooms} from '../src/publishPickerRooms.mjs'
const source=fs.readFileSync(process.argv[2],'utf8')
const a=source.indexOf('let publishGroupsError=z('),b=source.indexOf('async function _t(',a)
assert(a>=0&&b>a)
async function scenario(groupFailure,productFailure){
 const old=[{id:9}],w={value:false},ee={value:old},re={value:[{id:8}]},notices=[]
 let calls=0,release
 const pending=new Promise(r=>release=r)
 const context={manualPublishUpload:{revision:{value:0},mergeGroups:groups=>groups},w,ee,re,te:{value:[]},Y:fn=>({get value(){return fn()}}),publishPickerRooms,Do:async()=>[],Q:'',z:value=>({value}),st:x=>x.ready,t:msg=>notices.push(msg),
  Eo:async()=>{calls++;await pending;if(groupFailure)throw Error('offline');return [{id:1,ready:true},{id:2,ready:false}]},
  ss:async()=>{if(productFailure)throw Error('offline');return [{id:3,enabled:true}]}}
 vm.createContext(context);vm.runInContext(source.slice(a,b)+';globalThis.refresh=gt;globalThis.error=publishGroupsError;',context)
 const first=context.refresh(),second=context.refresh();assert.equal(first,second);assert.equal(calls,1);assert.equal(w.value,true)
 release();await first;assert.equal(w.value,false)
 if(groupFailure){assert.equal(ee.value,old);assert.match(context.error.value,/分组加载失败/)}
 else{assert.equal(ee.value.length,1);assert.equal(ee.value[0].id,1);assert.equal(context.error.value,'')}
 assert.equal(re.value[0].id,productFailure?8:3)
}
for(const g of [false,true])for(const p of [false,true])await scenario(g,p)
assert(source.includes('G(`div`,Pb,w.value?`正在加载视频分组…`'))
assert(source.includes('await Promise.allSettled([ft(),gt(),'))
console.log('4 loading failure/success combinations, retained data and duplicate refresh verified')
