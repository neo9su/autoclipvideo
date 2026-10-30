import fs from 'node:fs'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { patchPublishBundle } from '../../scripts/patch_publish_selection_bundle.mjs'
const require = createRequire(import.meta.url), { parse } = require('@babel/parser')
const original = fs.readFileSync(process.argv[2], 'utf8')
const helper = fs.readFileSync(new URL('../src/publishSelection.mjs', import.meta.url), 'utf8')
const updated = patchPublishBundle(original, helper)
function setup(source) {
  let found
  function visit(node) {
    if (!node || typeof node !== 'object') return
    if (node.type === 'ObjectExpression' && node.properties.some(p => p.key?.name === '__name' && p.value?.type === 'TemplateLiteral' && p.value.quasis[0].value.cooked === 'Publish')) found = node.properties.find(p => p.key?.name === 'setup')
    for (const [key, value] of Object.entries(node)) { if (['loc', 'extra'].includes(key)) continue; if (Array.isArray(value)) value.forEach(visit); else if (value && typeof value === 'object') visit(value) }
  }
  visit(parse(source, { sourceType: 'module' })); return found
}
const before = setup(original), after = setup(updated)
assert.equal(updated.slice(0, after.start), original.slice(0, before.start))
assert.equal(updated.slice(after.end, updated.length - ('\n' + helper.replace(/^export /gm, '')).length), original.slice(before.end))
// Lifecycle registration remains in setup, outside the wrapped render closure.
const code = updated.slice(after.start, after.end)
assert(code.indexOf('return Qn(async') < code.indexOf('(...codexRenderArgs)=>'))
assert(code.includes('createTask:body=>codexPostPublishTask'))
assert.throws(() => patchPublishBundle(updated, helper), /Already patched/)
console.log('production bundle: unrelated views preserved; lifecycle and no-retry creation verified')
