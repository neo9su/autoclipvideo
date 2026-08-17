import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const api = await readFile(new URL('../src/api.js', import.meta.url), 'utf8')
const view = await readFile(new URL('../src/views/Groups.vue', import.meta.url), 'utf8')

for (const endpoint of [
  '/api/groups/${id}/merge',
  '/api/groups/${id}/retry-director',
  '/api/groups/${id}/retry-qianchuan',
]) assert.ok(api.includes(endpoint), `missing API endpoint mapping: ${endpoint}`)
assert.match(api, /encodeURIComponent\(version\)/)
assert.match(api, /retry-styles\/\$\{encodeURIComponent\(version\)\}/)
assert.match(view, /version === 'classic'\) await mergeGroup\(group\.id\)/)
assert.match(view, /version === 'director'\) await retryDirector\(group\.id\)/)
assert.match(view, /version === 'qianchuan'\) await retryQianchuan\(group\.id\)/)
assert.match(view, /await retryStyles\(group\.id, version\)/)
assert.match(view, /经典版/)
assert.match(view, /导演版/)
assert.match(view, /直出版/)
assert.match(view, /保守版/)
assert.match(view, /千川版/)
assert.doesNotMatch(view, /generateStyles\(/)

assert.match(view, /const fiveVersions = \[/)
for (const label of ['经典版', '导演版', '直出版', '保守版', '千川版']) {
  assert.ok(view.includes(`label: '${label}'`), `missing independent trigger label: ${label}`)
}
assert.match(view, /version === 'realistic' \|\| version === 'conservative'/)
assert.match(view, /await retryStyles\(group\.id, version\)/)
assert.doesNotMatch(view, /generateStyles\(/)
assert.doesNotMatch(view, /直出版 \+ 保守版/)
assert.match(view, /versionNeedsRetry\(g, version\.key\)/)

console.log('five-version endpoint mappings and independent triggers verified')
