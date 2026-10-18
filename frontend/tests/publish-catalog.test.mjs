import {test} from 'node:test'
import assert from 'node:assert/strict'
import {catalogSearchProducts} from '../src/publishCatalog.mjs'
test('oxygen typo matches all real names without stray keywords',()=>{
 const rows=[{id:1,product_name:'氧气栗子',product_url:'a',enabled:1},{id:2,product_name:'氧气栗子卷发',product_url:'b',enabled:true},{id:3,product_name:'夺回人生',keywords:'氧气',product_url:'c',enabled:1},{id:4,product_name:'氧气栗子',product_url:'d',enabled:0},{id:5,product_name:'氧气栗子',product_url:''}]
 assert.deepEqual(catalogSearchProducts(rows,'氧气粒子').map(p=>p.id),[1,2])
})
