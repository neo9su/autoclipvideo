export function catalogIsCodexRoom(roomId, rooms) {
  const room = rooms.find(r => String(r.id) === String(roomId))
  return !!room && (room.url === '__codex_completed__' || room.name === 'codex 成片' || room.url === '__custom__' || room.name === '自定义上传')
}

export function catalogRoomProducts(products, roomId, rooms) {
  const linkable = products.filter(p => p.enabled !== false && p.enabled !== 0 && String(p.product_url || '').trim())
  if (!roomId || catalogIsCodexRoom(roomId, rooms)) return linkable
  const combined = linkable.filter(p => String(p.room_id) === String(roomId) || !p.room_id)
  return combined.length ? combined : linkable
}

export function catalogSearchProducts(products, query) {
  let q = String(query || '').trim().toLowerCase()
  if (q.includes('氧气')) q = '氧气'
  return products.filter(p => p.enabled !== false && p.enabled !== 0 && String(p.product_url || '').trim())
    .filter(p => !q || String(p.product_name || '').toLowerCase().includes(q) ||
      (q !== '氧气' && String(p.keywords || '').toLowerCase().includes(q)))
}
