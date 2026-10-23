// Evaluate only on an authenticated Buyin shop-detail page. Read-only:
// no fetch, cart actions, storage writes, login changes or generated URLs.
(async () => {
  if (location.hostname !== 'buyin.jinritemai.com' ||
      location.pathname !== '/dashboard/merch-picking-library/shop-detail') {
    return {wrong_page: true, rows: []};
  }
  const rows = new Map();
  const cards = () => [...document.querySelectorAll('div[class*="card"]')]
    .filter(e => /[¥￥]\s*\d/.test(e.innerText || ''));
  let scroller = cards()[0];
  while (scroller && scroller !== document.body) {
    if (/(auto|scroll)/.test(getComputedStyle(scroller).overflowY) &&
        scroller.scrollHeight > scroller.clientHeight + 20) break;
    scroller = scroller.parentElement;
  }
  let previous = -1, stable = 0;
  for (let round = 0; round < 45; round++) {
    const seen = new WeakSet();
    let visited = 0;
    function walk(value, depth) {
      if (!value || typeof value !== 'object' || seen.has(value) ||
          depth > 9 || visited++ > 20000) return;
      seen.add(value);
      const model = value.base_model;
      if (model?.product_info?.name && model.product_info.detail_url) {
        const product = model.product_info, shop = model.shop_info || {};
        // Unsafe JS numeric IDs must never enter a recovery manifest.
        const safe = x => typeof x !== 'number' || Number.isSafeInteger(x);
        if (safe(value.product_id) && safe(shop.shop_id)) {
          const row = {name: product.name, detail_url: product.detail_url,
            product_id: value.product_id, promotion_id: value.promotion_id,
            shop_id: shop.shop_id, shop_name: shop.shop_name};
          rows.set(JSON.stringify([row.product_id, row.detail_url, row.shop_id, row.name]), row);
        }
      }
      for (const key of Object.keys(value)) {
        if (['_owner', 'return', 'sibling', 'stateNode', 'alternate', 'ref'].includes(key)) continue;
        try { walk(value[key], depth + 1); } catch (_) {}
      }
    }
    let element = cards()[0];
    for (let i = 0; i < 12 && element; i++, element = element.parentElement) {
      for (const key of Object.keys(element)) {
        if (key.startsWith('__reactProps')) walk(element[key], 0);
        if (key.startsWith('__reactFiber')) {
          let fiber = element[key];
          for (let j = 0; j < 30 && fiber; j++, fiber = fiber.return) walk(fiber.memoizedProps, 0);
        }
      }
    }
    if (rows.size === previous) stable++; else stable = 0;
    if (stable >= 3) return {rows: [...rows.values()], stop: 'stable_count', complete: false};
    previous = rows.size;
    if (scroller && scroller !== document.body) scroller.scrollTop = scroller.scrollHeight;
    else window.scrollTo(0, document.body.scrollHeight);
    await new Promise(resolve => setTimeout(resolve, 900));
  }
  return {rows: [...rows.values()], stop: 'round_limit', complete: false};
})()
