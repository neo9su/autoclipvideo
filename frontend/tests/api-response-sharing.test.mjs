import {test} from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import {patchSharedResponseBundle} from '../../scripts/patch_shared_response_bundle.mjs'
const api=fs.readFileSync(new URL('../src/api.js',import.meta.url),'utf8')
const body=api.slice(api.indexOf('const FETCH_TIMEOUT_MS'),api.indexOf('async function readErrorMessage')).replaceAll('export ','')
async function verify(source,name){
 let calls=0,resolve
 const pending=new Promise(r=>{resolve=r})
 const ctx={Response,AbortController,setTimeout,clearTimeout,CustomEvent:class{},window:{dispatchEvent(){}},fetch:()=>{calls++;return pending}}
 vm.createContext(ctx);vm.runInContext(source,ctx)
 const a=ctx[name]('/api/rooms'),b=ctx[name]('/api/rooms')
 resolve(new Response(JSON.stringify([{id:1,name:'小圆圆不圆'}]),{headers:{'content-type':'application/json'}}))
 const [one,two]=await Promise.all([a,b])
 assert.equal(calls,1)
 assert.notEqual(one,two)
 assert.deepEqual(await one.json(),await two.json())
}
test('deduplicated GET callers can independently read JSON bodies',()=>verify(body,'fetchWithTimeout'))
const fixture='const xo=new Map;function $(e,t={}){let o=(t.method||`GET`)==`GET`?e:null;if(o&&xo.has(o))return xo.get(o);let s=fetch(e,t);return o&&(xo.set(o,s),s.then(()=>xo.delete(o),()=>xo.delete(o))),s}'
test('production patch preserves shared network request and gives independent bodies',()=>verify(patchSharedResponseBundle(fixture),'$'))
test('production patch refuses drift and repeated application',()=>{
 assert.throws(()=>patchSharedResponseBundle('changed'),/drift/)
 assert.throws(()=>patchSharedResponseBundle(patchSharedResponseBundle(fixture)),/drift/)
})
