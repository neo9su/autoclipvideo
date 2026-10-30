import fs from 'node:fs'
import {createRequire} from 'node:module'
const require=createRequire(import.meta.url),{parse}=require('../frontend/node_modules/@babel/parser')
export function patchSharedCopy(source,helper){
 const matches=[]
 function walk(n){if(!n||typeof n!=='object')return;if(n.type==='FunctionDeclaration'&&n.id?.name==='codexCreatePublishSelection')matches.push(n);for(const v of Object.values(n))if(Array.isArray(v))v.forEach(walk);else if(v&&typeof v==='object')walk(v)}
 walk(parse(source,{sourceType:'module'}))
 if(matches.length!==1)throw Error('Selection helper drift')
 const n=matches[0],old=source.slice(n.start,n.end)
 if(old.includes('sharedCopy'))throw Error('Already patched')
 if(!old.includes('sharedCart'))throw Error('Shared cart missing; inspect before patching')
 const fn=helper.slice(helper.indexOf('export function codexCreatePublishSelection'),helper.indexOf('// Creation is a mutation')).replace('export function','function').trim()
 source=source.slice(0,n.start)+fn+source.slice(n.end)
 const before='点击名称逐条编辑文案；本批所有视频共用下方商品，空白文案会分别自动生成。'
 if(source.split(before).length!==2)throw Error('Copy hint drift')
 source=source.replace(before,'标题按视频分别编辑；本批所有视频共用描述、标签及下方商品，空白内容会分别自动生成。')
 parse(source,{sourceType:'module'})
 return source
}
if(process.argv[1]?.endsWith('patch_shared_copy_bundle.mjs')&&process.argv[2])fs.writeFileSync(process.argv[3],patchSharedCopy(fs.readFileSync(process.argv[2],'utf8'),fs.readFileSync(new URL('../frontend/src/publishSelection.mjs',import.meta.url),'utf8')))
