async page => {
  const groups = [
    { id: 11, label: 'codex · 11 · 人生_红棕色_偏分_长卷发', room_id: 1, room_name: '小圆圆不圆', wig_model: '人生', wig_color: '红棕色', editing_mode: 'codex', codex_status: 2, codex_available: true, publish_versions: 'codex', codex_final_video: 'codex/11.mp4' },
    { id: 12, label: 'codex · 12 · 夺回_黑茶色_中分_长卷发', room_id: 1, room_name: '小圆圆不圆', wig_model: '夺回', wig_color: '黑茶色', editing_mode: 'codex', codex_status: 2, codex_available: true, publish_versions: 'codex', codex_final_video: 'codex/12.mp4' },
    { id: 13, label: '天蝎座_黑色_齐刘海', room_id: 2, room_name: 'KUKU公主', wig_model: '天蝎座', wig_color: '黑色', editing_mode: 'codex', codex_status: 2, codex_available: true, publish_versions: 'codex', codex_final_video: 'codex/13.mp4' },
  ]
  const products = [101, 102, 201].map(id => ({ id, room_id: 1, product_name: id === 201 ? '夺回 商品' : '人生 同名商品', product_url: `https://haohuo.jinritemai.com/detail?id=${id}`, enabled: 1 }))
  let posts = []
  await page.unroute('**/*')
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (url.hostname === '127.0.0.1' && !path.startsWith('/api/')) return route.continue()
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': '*' } })
    let body = []
    if (path === '/api/publish-tasks' && request.method() === 'POST') {
      const payload = request.postDataJSON()
      const fail = await page.evaluate(id => { window.__fixtureAttempts = [...(window.__fixtureAttempts || []), id]; return window.__failFixtureGroup === id }, payload.group_id)
      if (fail) return route.fulfill({ status: 500, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': '*' }, body: JSON.stringify({ detail: '模拟失败，请手工重试' }) })
      posts.push(payload)
      await page.evaluate(data => { window.__publishFixturePosts = data }, posts)
      body = { id: 900 + posts.length, ...payload, status: 'pending' }
    } else if (request.method() !== 'GET') {
      await page.evaluate(data => { window.__unexpectedMutations = [...(window.__unexpectedMutations || []), data] }, { method: request.method(), path })
      return route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Unexpected mock mutation' }) })
    }
    else if (path.includes('publish-groups') || path === '/api/groups') body = groups
    else if (path === '/api/rooms') body = [{ id: 1, name: '小圆圆不圆', enabled: true }, { id: 2, name: 'KUKU公主', enabled: true }]
    else if (path === '/api/products') body = products
    else if (path.includes('publish-accounts')) body = [{ id: 9, platform: 'douyin', account_name: '颜遇生活', cookie_file: 'fixture' }]
    else if (path === '/api/publish-tasks') body = posts.map((data, index) => ({ id: 900 + index, ...data, status: 'pending' }))
    else if (path.includes('boot')) body = { available: false }
    else if (path === '/api/gpu/status') body = { online: true, maintenance: false }
    else if (path === '/api/status') body = { rooms: [], recordings: [], gpu_online: true }
    else if (path === '/api/stats') body = {}
    return route.fulfill({ status: 200, contentType: 'application/json', headers: { 'Access-Control-Allow-Origin': '*' }, body: JSON.stringify(body) })
  })
  if (page.routeWebSocket) await page.routeWebSocket(/.*/, () => {})
  await page.goto('http://127.0.0.1:5179/')
  console.log('Local copy of deployed frontend loaded with all nonlocal requests mocked')
}
