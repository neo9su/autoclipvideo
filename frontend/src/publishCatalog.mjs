export function catalogSearchProducts(products, query) {
  let q = String(query || '').trim().toLowerCase()
  if (q.includes('氧气')) q = '氧气'
  return products.filter(p => p.enabled !== false && p.enabled !== 0 && String(p.product_url || '').trim())
    .filter(p => !q || String(p.product_name || '').toLowerCase().includes(q) ||
      (q !== '氧气' && String(p.keywords || '').toLowerCase().includes(q)))
}
