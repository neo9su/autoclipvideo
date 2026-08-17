import test from 'node:test'
import assert from 'node:assert/strict'
import { STYLE_VERSIONS, VERSION_ENDPOINTS } from './version-endpoints.js'

test('maps each five-version control to its independent backend action', () => {
  const groupId = 181
  assert.equal(VERSION_ENDPOINTS.classic(groupId), '/api/groups/181/merge')
  assert.equal(VERSION_ENDPOINTS.director(groupId), '/api/groups/181/retry-director')
  assert.equal(VERSION_ENDPOINTS.realistic(groupId), '/api/groups/181/retry-styles')
  assert.equal(VERSION_ENDPOINTS.conservative(groupId), '/api/groups/181/retry-styles')
  assert.equal(VERSION_ENDPOINTS.qianchuan(groupId), '/api/groups/181/retry-qianchuan')
  assert.deepEqual(STYLE_VERSIONS, ['realistic', 'conservative'])
})

test('keeps all version controls visible and explains blocked prerequisites', async () => {
  const { readFile } = await import('node:fs/promises')
  const view = await readFile(new URL('./views/Groups.vue', import.meta.url), 'utf8')
  assert.match(view, /v-for="version in fiveVersions"/)
  assert.match(view, /five-version-disabled-reason/)
  assert.match(view, /缺少可匹配的千川录像或 SRT/)
  assert.match(view, /:aria-label="`\$\{version\.label\}：/)
})
