"""Stage small review-UI patches against the actual frontend; preserve drift."""
import argparse
import json
from pathlib import Path

from wig_identity_release import digest, _encode_like


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Frontend anchor changed; inspect before patching')
    return text.replace(old, new, 1)


def patch_groups(data):
    text = data.decode('utf-8-sig').replace('\r\n', '\n')
    if 'recheckWigIdentity' in text:
        raise ValueError('Review UI already present')
    text = replace_once(text, '<script setup>\n', '''<script setup>
import { qianchuanStatusMap as identityStatusMap, identityReviewItems } from '../qianchuan-review.js'
import { recheckQianchuanIdentity } from '../api.js'
''')
    text = replace_once(text, 'const qianchuanStatusMap = {\n', "const qianchuanStatusMap = {\n  '-5': identityStatusMap[-5],\n")
    text = replace_once(text, 'return Number(status) < 0\n', 'return Number(status) < 0 && Number(status) !== -5\n')
    text = replace_once(text, 'v-if="g.qianchuan_status !== 2"', 'v-if="g.qianchuan_status !== 2 && Number(g.qianchuan_status) !== -5"')
    marker = '              <template v-if="g.qianchuan_status === '
    pos = text.index(marker)
    text = text[:pos] + '''              <button v-if="Number(g.qianchuan_status) === -5" class="btn-action orange"
                :disabled="qianchuanBusy[g.id]" @click="recheckWigIdentity(g)">
                {{ qianchuanBusy[g.id] ? '重新检查中…' : '修正素材后重新检查' }}
              </button>
''' + text[pos:]
    marker = '          <div v-if="g.qianchuan_error" class="qianchuan-error">⚠ {{ summarizeQianchuanError(g.qianchuan_error) }}</div>'
    text = replace_once(text, marker, marker + '''
          <ul v-if="Number(g.qianchuan_status) === -5" class="qianchuan-error">
            <li v-for="(item, index) in identityReviewItems(g)" :key="index">{{ item }}</li>
          </ul>''')
    marker = '    const result = await generateQianchuanGroup(group.id)\n'
    text = replace_once(text, marker, marker + '''    if (Number(result.status) === -5) {
      group.qianchuan_status = -5
      group.qianchuan_error = result.error
      group.qianchuan_review = result.review
      show('款式一致性待审核，请先核实录像与目标商品', 'info')
      await load()
      return
    }
''')
    handler = '''async function recheckWigIdentity(group) {
  qianchuanBusy.value[group.id] = true
  try {
    const result = await recheckQianchuanIdentity(group.id)
    show(result.review_required ? '证据仍不足或存在冲突，请修正素材后再检查' : '元数据检查通过；画面与商品仍需审核', 'info')
    await load()
  } catch (error) {
    show(error.message || '重新检查失败', 'error')
  } finally {
    qianchuanBusy.value[group.id] = false
  }
}

'''
    text = replace_once(text, 'async function generateQianchuan(', handler + 'async function generateQianchuan(')
    return _encode_like(text, data)


def prepare_frontend(src, release, module):
    src, release = Path(src).resolve(), Path(release).resolve()
    if src == release or src in release.parents:
        raise ValueError('Release must be outside src')
    names = ['views/Groups.vue', 'api.js']
    originals = {name: (src/name).read_bytes() for name in names}
    api = originals['api.js'].decode('utf-8-sig').replace('\r\n', '\n')
    if 'recheckQianchuanIdentity' in api or (src/'qianchuan-review.js').exists():
        raise ValueError('Review API/module already present')
    api += '''
export async function recheckQianchuanIdentity(id) {
  const res = await fetchWithTimeout(`${BASE}/api/v2/qianchuan/group/${id}/identity-recheck`, { method: 'POST' })
  if (!res.ok) throw new Error(await readErrorMessage(res, '重新检查失败'))
  return res.json()
}
'''
    payloads = {'views/Groups.vue': patch_groups(originals['views/Groups.vue']),
                'api.js': _encode_like(api, originals['api.js']), 'qianchuan-review.js': Path(module).read_bytes()}
    originals['qianchuan-review.js'] = None
    release.mkdir(parents=True, exist_ok=False)
    for kind, files in [('before', originals), ('after', payloads)]:
        for name, data in files.items():
            if data is not None:
                target = release/kind/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    manifest = {'backend': str(src), 'policy_version': 'wig-identity-review-ui-v2',
                'before': {name: digest(data) if data is not None else None for name,data in originals.items()},
                'after': {name: digest(data) for name,data in payloads.items()}}
    (release/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--src',required=True)
    parser.add_argument('--release',required=True)
    parser.add_argument('--module',required=True)
    args = parser.parse_args()
    prepare_frontend(args.src,args.release,args.module)
    print('Frontend source staged; not applied or built')
