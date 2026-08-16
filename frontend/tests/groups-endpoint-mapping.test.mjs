import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const api = await readFile(new URL('../src/api.js', import.meta.url), 'utf8')
const view = await readFile(new URL('../src/views/Groups.vue', import.meta.url), 'utf8')

for (const endpoint of [
  '/api/groups/${id}/merge',
  '/api/groups/${id}/retry-director',
  '/api/groups/${id}/retry-styles',
  '/api/groups/${id}/retry-qianchuan',
]) assert.ok(api.includes(endpoint), `missing API endpoint mapping: ${endpoint}`)
assert.match(api, /body\s*=\s*JSON\.stringify\(\{ version \}\)/)
assert.match(view, /version === 'classic'\) await mergeGroup\(group\.id\)/)
assert.match(view, /version === 'director'\) await retryDirector\(group\.id\)/)
assert.match(view, /version === 'qianchuan'\) await retryQianchuan\(group\.id\)/)
assert.match(view, /await retryStyles\(group\.id, version\)/)

console.log('five-version endpoint mappings verified')
