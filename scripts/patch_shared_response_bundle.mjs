import fs from 'node:fs'
import {createRequire} from 'node:module'
const require=createRequire(import.meta.url)
const {parse}=require('../frontend/node_modules/@babel/parser')
export function patchSharedResponseBundle(source){
 const edits=[
  ['if(o&&xo.has(o))return xo.get(o);','if(o&&xo.has(o))return xo.get(o).then(response=>response.clone());'],
  ['s.then(()=>xo.delete(o),()=>xo.delete(o))),s}', 's.then(()=>xo.delete(o),()=>xo.delete(o))),o?s.then(response=>response.clone()):s}'],
 ]
 for(const [before,after] of edits){
  if(source.split(before).length!==2)throw Error('Shared-response bundle anchor drift; inspect before patching')
  source=source.replace(before,after)
 }
 parse(source,{sourceType:'module'})
 return source
}
if(process.argv[1]?.endsWith('patch_shared_response_bundle.mjs')&&process.argv[2]){
 fs.writeFileSync(process.argv[3],patchSharedResponseBundle(fs.readFileSync(process.argv[2],'utf8')))
}
