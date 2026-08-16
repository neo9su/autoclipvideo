import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const groupsSource = await readFile(new URL('../src/views/Groups.vue', import.meta.url), 'utf8')
const apiSource = await readFile(new URL('../src/api.js', import.meta.url), 'utf8')

assert.match(groupsSource, /version === 'classic'\) await mergeGroup\(group\.id\)/)
assert.match(groupsSource, /version === 'director'\) await retryDirector\(group\.id\)/)
assert.match(groupsSource, /version === 'qianchuan'\) await retryQianchuan\(group\.id\)/)
assert.match(groupsSource, /await retryStyles\(group\.id, version\)/)
assert.match(groupsSource, /if \(version === 'classic'\) return Number\(group\.merge_status/)
assert.match(groupsSource, /Boolean\(group\.merged_filename\)/)
assert.match(apiSource, /\/retry-director/)
assert.match(apiSource, /\/retry-qianchuan/)
assert.match(apiSource, /body = JSON\.stringify\(\{ version \}\)/)

console.log('five-version trigger mapping ok')
