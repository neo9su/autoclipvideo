import assert from 'node:assert/strict'
import { identityReviewItems, qianchuanStatusMap } from '../src/qianchuan-review.js'

assert.equal(qianchuanStatusMap[-5].label, '款式一致性待审核')
assert.equal(qianchuanStatusMap[-2].label, '商品不匹配')
const review = { identity: { issues: [{ code: 'recording_identity_conflict', recording_id: 17,
  expected: ['冷棕色'], observed: ['自然黑'] }] } }
for (const value of [review, JSON.stringify(review)]) {
  const items = identityReviewItems({ qianchuan_review: value })
  assert.equal(items.length, 1)
  assert.match(items[0], /录像 #17/)
  assert.match(items[0], /目标：冷棕色/)
  assert.match(items[0], /识别：自然黑/)
}
assert.deepEqual(identityReviewItems({ qianchuan_review: null }), [])
assert.match(identityReviewItems({ qianchuan_review: '{bad' })[0], /无法读取/)
console.log('Qianchuan review UI tests passed')
