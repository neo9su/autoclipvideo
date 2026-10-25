import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import {publishPickerRooms} from '../src/publishPickerRooms.mjs'
const groups=[{id:10,room_id:1,room_name:'小圆圆不圆',ready:true},{id:11,room_id:'1',room_name:'旧名',ready:true},{id:12,room_id:9,room_name:'codex 成片',ready:true}]
assert.deepEqual(publishPickerRooms([],groups),[{id:1,name:'小圆圆不圆'},{id:9,name:'codex 成片'}])
assert.equal(publishPickerRooms([{id:'1',name:'接口最新名称'}],groups)[0].name,'接口最新名称')
assert.deepEqual(publishPickerRooms([], [{room_id:null,room_name:'无效'},{room_id:'bad',room_name:'无效'}]),[])
const source=fs.readFileSync(process.argv[2],'utf8'),a=source.indexOf('let publishGroupsError=z('),b=source.indexOf('async function _t(',a)
let roomsFailed=true,roomCalls=0
const context={publishPickerRooms,z:value=>({value}),Y:fn=>({get value(){return fn()}}),te:{value:[]},ee:{value:[]},re:{value:[]},w:{value:false},Q:'',st:g=>g.ready,t:()=>{},
 Do:async()=>{roomCalls++;if(roomsFailed)throw Error('offline');return [{id:1,name:'接口最新名称'}]},
 Eo:async()=>groups,ss:async()=>[{id:3,enabled:true}]}
vm.createContext(context);vm.runInContext(source.slice(a,b)+';globalThis.refresh=gt;globalThis.rooms=publishRoomChips;globalThis.error=publishRoomsError;',context)
await context.refresh()
assert.equal(context.rooms.value.length,2);assert.equal(context.rooms.value[0].name,'小圆圆不圆');assert.match(context.error.value,/直播间列表加载失败/)
roomsFailed=false;await context.refresh()
assert.equal(roomCalls,2);assert.equal(context.error.value,'');assert.equal(context.rooms.value[0].name,'接口最新名称');assert.equal(context.rooms.value.length,2)
assert(source.includes('H(publishRoomChips.value,e=>'))
console.log('Room-label fallback, deduplication, latest names and refresh recovery passed')
