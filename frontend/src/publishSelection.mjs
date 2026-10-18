// Shared by the source view and the drift-checked production view patch.
export function codexGroupMatches(group, query) {
  const normalize = value => String(value ?? '').normalize('NFKC').toLowerCase().replace(/[\s_\-·&＆/\\,，。:：]+/gu, '')
  const tokens = String(query ?? '').trim().split(/\s+/u).filter(Boolean).map(normalize)
  const text = [group.id, `GP${String(group.id).padStart(7, '0')}`, group.label, group.room_name,
    group.wig_model, group.wig_color, group.hair_display, group.video_name, group.filename, group.merged_filename, group.codex_final_video,
    group.classic_final_video, group.director_final_video, group.creative_final_video,
    group.qianchuan_final_video, group.realistic_final_video, group.conservative_final_video].map(normalize).join('|')
  return tokens.every(token => text.includes(token))
}

export function codexCreatePublishSelection(options) {
  const { ref } = options
  const ids = ref([]), query = ref(''), submitting = ref(false), errors = ref([]), busy = ref(false)
  const drafts = new Map()
  let cart = { product_ids: [], no_cart: false }
  const clone = value => JSON.parse(JSON.stringify(value))
  const locked = () => submitting.value || busy.value || options.editingBusy?.()
  function snapshot() {
    const form = options.getForm()
    cart = { product_ids: [...(form.product_ids || [])], no_cart: !!form.no_cart }
    if (ids.value.includes(form.group_id)) drafts.set(form.group_id, { form: clone(form), extras: clone(options.getExtras()) })
  }
  function adopt() {
    const form = options.getForm()
    if (form.group_id && !ids.value.includes(form.group_id)) ids.value = [...ids.value, form.group_id]
    snapshot()
  }
  function focus(group) {
    if (locked() || !group) return
    snapshot()
    const shared = options.getShared()
    if (!ids.value.includes(group.id)) ids.value = [...ids.value, group.id]
    const draft = drafts.get(group.id)
    options.setForm(draft ? clone(draft.form) : { group_id: group.id, platform: shared.platform,
      account_id: shared.account_id || '', title: '', description: '', tags: '', product_ids: [], no_cart: false })
    // Platform/account/cart are shared; each video keeps its own copy.
    Object.assign(options.getForm(), { platform: shared.platform, account_id: shared.account_id || '', ...clone(cart) })
    options.setExtras(draft ? clone(draft.extras) : { version: options.defaultVersion(group), schemes: [], scheme: '', matched: null })
    snapshot()
  }
  function toggle(group) {
    if (locked()) return
    if (!ids.value.includes(group.id)) return focus(group)
    snapshot()
    ids.value = ids.value.filter(id => id !== group.id)
    drafts.delete(group.id)
    if (options.getForm().group_id === group.id) {
      const next = options.getGroups().find(g => g.id === ids.value[0])
      if (next) focus(next)
      else { options.setForm({ ...options.getForm(), group_id: '', title: '', description: '', tags: '', product_ids: [] }); options.setExtras({ version: '', schemes: [], scheme: '', matched: null }) }
    }
  }
  function clear() {
    ids.value = []; drafts.clear(); query.value = ''; errors.value = []
    options.setForm({ ...options.getForm(), group_id: '', title: '', description: '', tags: '', product_ids: [] })
    options.setExtras({ version: '', schemes: [], scheme: '', matched: null })
  }
  async function runEditing(operation) {
    if (locked()) return
    busy.value = true
    try { return await operation() } finally { busy.value = false }
  }
  async function submit() {
    if (locked()) return
    adopt(); snapshot()
    if (!ids.value.length) return
    const shared = clone(options.getShared())
    if (!shared.platform) return
    const sharedCart = clone(cart)
    if (!sharedCart.no_cart && !sharedCart.product_ids.length) { options.toast('请为本批视频选择共同挂车商品', 'error'); return }
    if (!sharedCart.no_cart && sharedCart.product_ids.length > 5) { options.toast('本批视频最多选择5件共同挂车商品', 'error'); return }
    const pending = ids.value.map(id => ({ id, draft: clone(drafts.get(id)) }))
    if (shared.scheduled_at && !Number.isFinite(Date.parse(/[zZ]|[+-]\d{2}:\d{2}$/.test(shared.scheduled_at) ? shared.scheduled_at : shared.scheduled_at + 'Z'))) {
      options.toast('请选择有效的发布时间', 'error'); return
    }
    submitting.value = true; errors.value = []
    let created = 0
    try {
      for (let index = 0; index < pending.length; index++) {
        const { id, draft } = pending[index]
        const form = draft.form
        const body = { group_id: id, platform: shared.platform, account_id: shared.account_id || null,
          scheduled_at: shared.scheduled_at ? new Date(Date.parse(/[zZ]|[+-]\d{2}:\d{2}$/.test(shared.scheduled_at) ? shared.scheduled_at : shared.scheduled_at + 'Z') + index * (shared.interval_minutes || 0) * 60000).toISOString().slice(0, 16) : null,
          title: form.title || null, description: form.description || null, tags: form.tags || null,
          product_ids: sharedCart.no_cart ? null : [...sharedCart.product_ids],
          publish_version: draft.extras.version, no_cart: sharedCart.no_cart,
          auto_meta: !String(form.title || '').trim() || !String(form.description || '').trim() }
        try {
          await options.createTask(body)
          created++; ids.value = ids.value.filter(value => value !== id); drafts.delete(id)
        } catch (error) {
          errors.value = [...errors.value, { id, message: String(error.message || error) }]
        }
      }
      try { await options.loadTasks() } catch { /* Never resubmit acknowledged tasks after a refresh error. */ }
      options.toast(`已创建 ${created} 个独立发布任务${errors.value.length ? `，${errors.value.length} 个未创建，请核对下方提示` : ''}`, errors.value.length ? 'info' : 'success')
      if (!ids.value.length) { options.onComplete(); clear() }
      else {
        const next = options.getGroups().find(group => group.id === ids.value[0])
        // Release only the submit guard before switching to a failed draft.
        submitting.value = false
        if (next) focus(next)
      }
    } finally { submitting.value = false }
  }
  return { ids, query, submitting, errors, busy, snapshot, adopt, focus, toggle, clear, runEditing, submit,
    matches: group => codexGroupMatches(group, query.value) }
}

// Creation is a mutation: never automatically retry an ambiguous response.
export async function codexPostPublishTask(url, body, fetchImpl = fetch) {
  let response
  try {
    response = await fetchImpl(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(60000) })
  } catch {
    throw new Error('创建结果未确认，请先刷新任务列表核对，避免重复提交')
  }
  if (!response.ok) {
    let text = await response.text()
    try { const data = JSON.parse(text); text = typeof data.detail === 'string' ? data.detail : text } catch { /* Plain-text server error. */ }
    throw new Error(text || `创建失败 (${response.status})`)
  }
  return response.json()
}
