import fs from 'node:fs'
import {createRequire} from 'node:module'
const require=createRequire(import.meta.url),{parse}=require('../frontend/node_modules/@babel/parser')
export function patchCodexCartRooms(source,helper){
 if(source.includes('function codexCatalogRoomProducts'))throw Error('Already patched')
 const before='F=Y(()=>{let e=re.value.filter(e=>!!e.product_url),t=Ze.value||(ne.value===0?null:ne.value);if(!t)return e;let n=e.filter(e=>e.room_id===t),r=e.filter(e=>!e.room_id),i=[...n,...r];return i.length>0?i:e})'
 const label='Ze.value?(W(),G(`span`,mx,`· 已按直播间筛选`))'
 for(const anchor of [before,label])if(source.split(anchor).length!==2)throw Error('Codex cart binding drift')
 source=source.replace(before,'F=Y(()=>codexCatalogRoomProducts(re.value,Ze.value||(ne.value===0?null:ne.value),te.value))')
 source=source.replace(label,'Ze.value?(W(),G(`span`,mx,codexCatalogIsCodexRoom(Ze.value,te.value)?`· 可选全部直播间商品`:`· 已按直播间筛选`))')
 const extra=helper.slice(0,helper.indexOf('export function catalogSearchProducts')).replaceAll('export function catalog','function codexCatalog')
 // Keep references inside the extracted helpers bound to the deployed helper names.
 source+='\n'+extra.replace('|| catalogIsCodexRoom(', '|| codexCatalogIsCodexRoom(')
 parse(source,{sourceType:'module'});return source
}
if(process.argv[1]?.endsWith('patch_codex_cart_rooms.mjs')&&process.argv[2])fs.writeFileSync(process.argv[3],patchCodexCartRooms(fs.readFileSync(process.argv[2],'utf8'),fs.readFileSync(new URL('../frontend/src/publishCatalog.mjs',import.meta.url),'utf8')))
