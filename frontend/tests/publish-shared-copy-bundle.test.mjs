import {test} from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {patchSharedCopy} from '../../scripts/patch_shared_copy_bundle.mjs'
test('replace selection helper only; preserve existing response and cart fixes',()=>{
 const helper=fs.readFileSync(new URL('../src/publishSelection.mjs',import.meta.url),'utf8')
 const fixture='const existingResponseFix="keep";function codexCreatePublishSelection(options){const sharedCart={};return options}const hint="点击名称逐条编辑文案；本批所有视频共用下方商品，空白文案会分别自动生成。";'
 const result=patchSharedCopy(fixture,helper)
 assert(result.startsWith('const existingResponseFix="keep";'))
 assert(result.includes('description: sharedCopy.description || null, tags: sharedCopy.tags || null'))
 assert(result.includes('product_ids: sharedCart.no_cart ? null : [...sharedCart.product_ids]'))
 assert(result.includes('本批所有视频共用描述、标签及下方商品'))
 assert.throws(()=>patchSharedCopy(result,helper),/Already patched/)
 assert.throws(()=>patchSharedCopy('changed',helper),/drift/)
})
