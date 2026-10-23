"""Patch the drifted production frontend with visible/safe product-link handling."""
import argparse
import hashlib
import shutil
from pathlib import Path


EXPECTED = {
    "Products.vue": "158592fc38424860db00bc7fe2839becf7efbbc196fa75cee208a41dcc8adcc2",
    "Publish.vue": "8874bf212f64ee627097b45c55d5e992ac75c4b5b1dc3c830b5eb5018b8c011f",
}


def replace_once(text, before, after, name):
    if text.count(before) != 1:
        raise RuntimeError(f"anchor mismatch for {name}: {text.count(before)}")
    return text.replace(before, after, 1)


def patch(root, backup):
    views = root / "src" / "views"
    backup.mkdir(parents=True, exist_ok=False)
    paths = {name: views / name for name in EXPECTED}
    for name, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != EXPECTED[name]:
            raise RuntimeError(f"source drift for {name}: {digest}")
        shutil.copy2(path, backup / name)

    path = paths["Products.vue"]
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "            <th>平台商品ID</th>\n            <th>匹配关键词</th>",
                        "            <th>平台商品ID</th>\n            <th>商品链接</th>\n            <th>匹配关键词</th>", "product header")
    text = replace_once(text, '            <td class="mono">{{ p.product_id || \'—\' }}</td>\n            <td>',
                        '            <td class="mono">{{ p.product_id || \'—\' }}</td>\n'
                        '            <td class="url-cell">\n'
                        '              <a v-if="p.product_url" :href="p.product_url" target="_blank" rel="noopener" class="link">打开链接</a>\n'
                        '              <span v-else class="link-missing">未绑定</span>\n'
                        '            </td>\n            <td>', "product link cell")
    text = replace_once(text, ".mono { font-family: monospace; font-size: 12px; }\n.link {",
                        ".mono { font-family: monospace; font-size: 12px; }\n.url-cell { white-space: nowrap; }\n.link-missing { color: #f59e0b; font-size: 12px; }\n.link {", "product link styles")
    path.write_text(text, encoding="utf-8")

    path = paths["Publish.vue"]
    text = path.read_text(encoding="utf-8")
    before = """const roomFilteredProducts = computed(() => {
  // Use selected group's room first, fall back to room chip filter, then show all
  const roomId = selectedGroupRoomId.value || (roomFilter.value !== 0 ? roomFilter.value : null)
  if (!roomId) return products.value
  const byRoom = products.value.filter(p => p.room_id === roomId)
  const globals = products.value.filter(p => !p.room_id)
  const combined = [...byRoom, ...globals]
  return combined.length > 0 ? combined : products.value
})"""
    after = """const roomFilteredProducts = computed(() => {
  // Cart-required publishes may only select products with a stored real URL.
  const linkable = products.value.filter(p => Boolean(p.product_url))
  // Use selected group's room first, fall back to room chip filter, then show all
  const roomId = selectedGroupRoomId.value || (roomFilter.value !== 0 ? roomFilter.value : null)
  if (!roomId) return linkable
  const byRoom = linkable.filter(p => p.room_id === roomId)
  const globals = linkable.filter(p => !p.room_id)
  const combined = [...byRoom, ...globals]
  return combined.length > 0 ? combined : linkable
})"""
    path.write_text(replace_once(text, before, after, "publish product filter"), encoding="utf-8")
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    print(patch(args.root, args.backup))
