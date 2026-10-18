import {test} from 'node:test'
import assert from 'node:assert/strict'
import {patchCatalogBundle} from '../../scripts/patch_publish_catalog_bundle.mjs'
const helper='export function catalogSearchProducts(p,q){return p}'
const fixture='const Other={unchanged:"keep"};const View={__name:"Publish",setup(){const $e=Y(()=>{let t=Qe.value.trim();return F.value});async function en(){return Ps(I.value.group_id)}return en}};const Tail="keep";'
test('only matching and filtering expressions change; wrappers and other views survive',()=>{
 const out=patchCatalogBundle(fixture,helper)
 assert.ok(out.startsWith('const Other={unchanged:"keep"};'))
 assert.ok(out.includes('return en}};const Tail="keep";'))
 assert.ok(out.includes('codexCatalogSearchProducts(F.value,Qe.value)'))
 assert.ok(out.includes('I.value.product_ids=a.map(p=>p.id)'))
 assert.throws(()=>patchCatalogBundle(out,helper),/Already patched/)
 assert.throws(()=>patchCatalogBundle(fixture.replace('Ps(I.value.group_id)','wrong()'),helper),/Body drift/)
})
