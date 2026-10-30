import {test}from'node:test'
import assert from'node:assert/strict'
import fs from'node:fs'
import {patchSharedCart}from'../../scripts/patch_shared_cart_bundle.mjs'
test('replace only cart helper and batch instruction; preserve other features',()=>{
 const helper=fs.readFileSync(new URL('../src/publishSelection.mjs',import.meta.url),'utf8')
 const source='const untouched="oxygen-search";function codexCreatePublishSelection(options){return options}const tail="点击名称逐条编辑文案和商品，空白文案会分别自动生成。";'
 const result=patchSharedCart(source,helper)
 assert(result.startsWith('const untouched="oxygen-search";'))
 assert(result.endsWith('const tail="点击名称逐条编辑文案；本批所有视频共用下方商品，空白文案会分别自动生成。";'))
 assert(result.includes('product_ids: sharedCart.no_cart ? null : [...sharedCart.product_ids]'))
 assert.throws(()=>patchSharedCart(result,helper),/Already patched/)
})
