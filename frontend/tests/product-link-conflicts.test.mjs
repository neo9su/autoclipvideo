import {test} from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
test('duplicate notice identifies all owners including disabled products and opens the selected owner',async()=>{
 const source=fs.readFileSync(new URL('../src/product-link-editor.js',import.meta.url),'utf8')
 const helper=source.slice(source.indexOf('async function showSaveError'),source.indexOf('const buttons='))
 const element=()=>({style:{},children:[],append(...x){this.children.push(...x)},replaceChildren(){this.children=[]},addEventListener(_,fn){this.click=fn}})
 const conflicts=element(),opened=[]
 const ctx={document:{createElement:element},message:element(),conflicts,active:{id:683},input:{value:'https://example.test/item'},openEditor:id=>opened.push(id),fetch:async()=>({ok:true,json:async()=>[{id:1,product_name:'同名商品',product_url:'https://example.test/item',enabled:1,room_name:'小圆'},{id:2,product_name:'同名商品',product_url:'https://example.test/item',enabled:0},{id:683,product_url:'https://example.test/item'},{id:3,product_url:'different'}]})}
 vm.createContext(ctx);vm.runInContext(helper,ctx);await ctx.showSaveError(Error('此链接已存在于其他商品中'))
 assert.equal(conflicts.children.length,2)
 assert.match(conflicts.children[0].children[0].textContent,/ID：1.*同名商品.*小圆.*启用/)
 assert.match(conflicts.children[1].children[0].textContent,/ID：2.*停用/)
 conflicts.children[1].children[1].click();assert.deepEqual(opened,[2])
})
