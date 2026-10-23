import {test} from 'node:test'
import assert from 'node:assert/strict'
import {catalogSearchProducts} from '../src/publishCatalog.mjs'
test('oxygen typo matches all real names without stray keywords',()=>{
 const rows=[{id:1,product_name:'氧气栗子',product_url:'a',enabled:1},{id:2,product_name:'氧气栗子卷发',product_url:'b',enabled:true},{id:3,product_name:'夺回人生',keywords:'氧气',product_url:'c',enabled:1},{id:4,product_name:'氧气栗子',product_url:'d',enabled:0},{id:5,product_name:'氧气栗子',product_url:''}]
 assert.deepEqual(catalogSearchProducts(rows,'氧气粒子').map(p=>p.id),[1,2])
})

test('codex room can select linked products from every room, retaining regular room filtering',async()=>{
 const {catalogRoomProducts,catalogIsCodexRoom}=await import('../src/publishCatalog.mjs')
 const rooms=[{id:19,url:'__codex_completed__',name:'codex 成片'},{id:1,name:'小圆圆不圆'}]
 const products=[{id:1,room_id:1,product_url:'a',enabled:1},{id:2,room_id:2,product_url:'b',enabled:1},{id:3,room_id:null,product_url:'c',enabled:1},{id:4,room_id:2,product_url:'',enabled:1},{id:5,room_id:3,product_url:'e',enabled:0}]
 assert(catalogIsCodexRoom('19',rooms))
 assert.deepEqual(catalogRoomProducts(products,19,rooms).map(p=>p.id),[1,2,3])
 assert.deepEqual(catalogRoomProducts(products,1,rooms).map(p=>p.id),[1,3])
 assert.deepEqual(catalogRoomProducts(products,null,rooms).map(p=>p.id),[1,2,3])
})
