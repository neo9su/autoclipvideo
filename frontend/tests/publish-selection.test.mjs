import assert from 'node:assert/strict'
import { codexGroupMatches, codexCreatePublishSelection } from '../src/publishSelection.mjs'

assert(codexGroupMatches({ id: 11, label: 'codex · 人生_红棕色_偏分_长卷发' }, '人生 红棕'))
assert(codexGroupMatches({ id: 11, label: '人生_红棕色' }, '人生红棕'))
assert(codexGroupMatches({ id: 11 }, 'GP0000011'))
assert(!codexGroupMatches({ id: 11, label: '人生_红棕色' }, '人生 黑色'))
assert(codexGroupMatches({ id: 1, room_name: 'KUKU', codex_final_video: '雪_短发.mp4' }, 'kuku 雪'))

function fixture(failing = new Set()) {
  const groups = [{ id: 1, label: '人生' }, { id: 2, label: '夺回' }, { id: 3, label: '天蝎座' }]
  let form = { group_id: '', platform: 'douyin', account_id: 9, product_ids: [] }
  let extras = { version: 'codex', schemes: [], scheme: '', matched: null }
  const calls = [], messages = []
  let closed = 0, refreshFails = false, release
  const ref = value => ({ value })
  const batch = codexCreatePublishSelection({ ref, getForm: () => form, setForm: value => form = value,
    getExtras: () => extras, setExtras: value => extras = value, getGroups: () => groups,
    getShared: () => ({ platform: form.platform, account_id: form.account_id, scheduled_at: '2026-10-19T08:00', interval_minutes: 30 }),
    defaultVersion: () => 'codex', createTask: async body => { calls.push(body); if (release) await release; if (failing.has(body.group_id)) throw Error('retry manually') },
    loadTasks: async () => { if (refreshFails) throw Error('refresh failed') },
    toast: (...value) => messages.push(value), onComplete: () => closed++ })
  return { batch, groups, calls, form: () => form, extras: () => extras, closed: () => closed,
    failRefresh: () => refreshFails = true, hold: promise => release = promise }
}

{
  const f = fixture()
  f.batch.focus(f.groups[0]); Object.assign(f.form(), { title: '人生标题', description: '人生文案', product_ids: [101, 102] })
  f.batch.focus(f.groups[1]); Object.assign(f.form(), { title: '夺回标题', description: '夺回文案', product_ids: [201] })
  f.batch.focus(f.groups[0]); assert.deepEqual(f.form().product_ids, [101, 102]); assert.equal(f.form().title, '人生标题')
  f.batch.query.value = '找不到'; assert.deepEqual(f.batch.ids.value, [1, 2])
  await f.batch.submit()
  assert.equal(f.calls.length, 2); assert.equal(f.calls[0].group_id, 1); assert.equal(f.calls[1].group_id, 2)
  assert.deepEqual(f.calls.map(x => x.title), ['人生标题', '夺回标题'])
  assert.deepEqual(f.calls.map(x => x.product_ids), [[101, 102], [201]])
  assert(f.calls.every(x => x.publish_version === 'codex' && x.account_id === 9))
  assert.deepEqual(f.calls.map(x => x.scheduled_at), ['2026-10-19T08:00', '2026-10-19T08:30'])
  assert.equal(f.closed(), 1)
}
{
  const failures = new Set([2]), f = fixture(failures)
  f.batch.focus(f.groups[0]); f.batch.focus(f.groups[1]); f.failRefresh()
  await f.batch.submit(); assert.deepEqual(f.batch.ids.value, [2]); assert.equal(f.batch.errors.value[0].id, 2)
  failures.clear(); await f.batch.submit(); assert.deepEqual(f.calls.map(x => x.group_id), [1, 2, 2])
}
{
  const f = fixture(); f.batch.focus(f.groups[0])
  let release; f.hold(new Promise(resolve => release = resolve))
  const first = f.batch.submit(); await f.batch.submit(); f.batch.focus(f.groups[1])
  assert.equal(f.calls.length, 1); assert.deepEqual(f.batch.ids.value, [1]); release(); await first
}
{
  const f = fixture(); f.batch.focus(f.groups[0]); f.form().title = '保留'
  let release; const operation = f.batch.runEditing(() => new Promise(resolve => release = resolve))
  f.batch.focus(f.groups[1]); assert.equal(f.form().group_id, 1); release(); await operation
  f.batch.focus(f.groups[1]); f.batch.toggle(f.groups[1]); assert.equal(f.form().title, '保留')
}
console.log('publish selection: search, isolated drafts, per-video tasks, partial failures and concurrent-click guards passed')

{
  const { codexPostPublishTask } = await import('../src/publishSelection.mjs')
  let attempts = 0
  await assert.rejects(codexPostPublishTask('/mock', { group_id: 1 }, async () => { attempts++; return new Response(JSON.stringify({ detail: '模拟失败' }), { status: 500 }) }), /模拟失败/)
  assert.equal(attempts, 1)
  attempts = 0
  await assert.rejects(codexPostPublishTask('/mock', { group_id: 1 }, async () => { attempts++; throw Error('network') }), /未确认/)
  assert.equal(attempts, 1)
}
