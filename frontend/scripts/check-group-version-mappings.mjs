import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const groupsView = await readFile(new URL('../src/views/Groups.vue', import.meta.url), 'utf8')
const api = await readFile(new URL('../src/api.js', import.meta.url), 'utf8')

const expectedMappings = [
  ["version === 'classic'", 'mergeGroup(group.id)'],
  ["version === 'director'", 'retryDirector(group.id)'],
  ["version === 'qianchuan'", 'retryQianchuan(group.id)'],
  ["await retryStyles(group.id, version)", 'retryStyles(group.id, version)'],
  ['JSON.stringify({ version })', 'JSON.stringify({ version })'],
]
for (const [needle, description] of expectedMappings) {
  assert.ok((groupsView + api).includes(needle), `missing mapping: ${description}`)
}

assert.match(api, /retry-director/)
assert.match(api, /retry-qianchuan/)
assert.match(api, /retry-styles/)
assert.match(api, /JSON\.stringify\(\{ version \}\)/)
assert.match(groupsView, /merge_status.*merged_filename|merged_filename.*merge_status/s)
console.log('five-version endpoint mappings: ok')
