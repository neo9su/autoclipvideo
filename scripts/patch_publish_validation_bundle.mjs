import fs from 'node:fs'
import {createRequire} from 'node:module'
const require=createRequire(import.meta.url),{parse}=require('../frontend/node_modules/@babel/parser')
export function patchValidation(source,helper){
 const matches=[];function walk(n){if(!n||typeof n!=='object')return;if(n.type==='FunctionDeclaration'&&n.id?.name==='codexCreatePublishSelection')matches.push(n);for(const v of Object.values(n))if(Array.isArray(v))v.forEach(walk);else if(v&&typeof v==='object')walk(v)}
 walk(parse(source,{sourceType:'module'}));if(matches.length!==1)throw Error('Selection helper drift')
 const n=matches[0],old=source.slice(n.start,n.end)
 if(old.includes('const reject ='))throw Error('Already patched')
 if(!old.includes('sharedCopy'))throw Error('Shared copy missing')
 const fn=helper.slice(helper.indexOf('export function codexCreatePublishSelection'),helper.indexOf('// Creation is a mutation')).replace('export function','function').trim()
 source=source.slice(0,n.start)+fn+source.slice(n.end);parse(source,{sourceType:'module'});return source
}
if(process.argv[1]?.endsWith('patch_publish_validation_bundle.mjs')&&process.argv[2])fs.writeFileSync(process.argv[3],patchValidation(fs.readFileSync(process.argv[2],'utf8'),fs.readFileSync(new URL('../frontend/src/publishSelection.mjs',import.meta.url),'utf8')))
