import {test}from'node:test'
import assert from'node:assert/strict'
import fs from'node:fs'
import vm from'node:vm'
const source=fs.readFileSync(new URL('../../backend/publish_review.py',import.meta.url),'utf8').split('<script>')[1].split('</script>')[0]
function fixture(){const nodes={};for(const id of ['tasks','msg','shot','checked','submit','empty','refresh','hint'])nodes[id]={value:'',checked:false,disabled:true,replaceChildren(){},append(){},textContent:''};let posts=0
 const context=vm.createContext({document:{querySelector:q=>nodes[q.slice(1)],createElement:()=>({})},URL:{createObjectURL:()=> 'blob:mock',revokeObjectURL(){}},setInterval(){},fetch:async url=>{
 if(url.endsWith('/confirm')){posts++;return{ok:true}}
 if(url.endsWith('/screenshot'))return{ok:true,blob:async()=>new Blob(['png']),headers:{get:()=> 'token'}}
 return{ok:true,json:async()=>[]}
 }})
 vm.runInContext(source,context)
 return{nodes,context,posts:()=>posts}
}
test('confirming one task never disables a different task',async()=>{
 const f=fixture();await new Promise(setImmediate)
 vm.runInContext("rows=[{id:1,ready:true},{id:2,ready:true}];tasks.value='1';loadedId='1';token='one';checked.checked=true;enabled()",f.context)
 assert.equal(f.nodes.submit.disabled,false);await f.nodes.submit.onclick();assert.equal(f.nodes.submit.disabled,true)
 vm.runInContext("tasks.value='2';loadedId='2';token='two';checked.checked=true;enabled()",f.context)
 assert.equal(f.nodes.submit.disabled,false)
 vm.runInContext("tasks.value='1';loadedId='1';token='again';enabled()",f.context)
 assert.equal(f.nodes.submit.disabled,true);assert.equal(f.posts(),1)
})
test('ready task with no fresh screenshot explains the disabled button',async()=>{
 const f=fixture();await new Promise(setImmediate)
 vm.runInContext("rows=[{id:2,ready:true}];tasks.value='2';token='';checked.checked=true;enabled()",f.context)
 assert.equal(f.nodes.submit.disabled,true);assert.match(f.nodes.hint.textContent,/刷新截图/)
})
