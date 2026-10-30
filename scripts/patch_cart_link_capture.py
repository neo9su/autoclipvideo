"""Stage a minimal source patch; no browser access, deployment or database writes."""
from pathlib import Path
import argparse


def patch(source):
    edits=[
        ('            const ctx = (box && box.outerHTML) ? box.outerHTML.slice(0, 4000) : \'\';\n            const idm = ctx.match(/\\b(\\d{15,20})\\b/);',
         "            const titles = new Set([...box.querySelectorAll('img[alt]')].map(e => (e.getAttribute('alt') || '').trim()).filter(s => s.length >= 6));\n            const hrefs = titles.size === 1 ? [...box.querySelectorAll('a[href]')].map(a => a.href) : [];"),
        ("                      id: idm ? idm[1] : '', explaining: /讲解中/.test(t)});",
         "                      hrefs, explaining: /讲解中/.test(t)});"),
        ("        for (const o of out) { if (!u[o.title]) { u[o.title] = 1; r.push(o); } }",
         "        for (const o of out) { const key = JSON.stringify([o.title, [...new Set(o.hrefs)].sort(), o.thumb]); if (!u[key]) { u[key] = 1; r.push(o); } }"),
        ('        pid = str(it.get("id") or "").strip() or ("dom_" + hashlib.md5(title.encode("utf-8")).hexdigest()[:12])',
         '        from cart_link_evidence import card_link_evidence\n        evidence = card_link_evidence(title, it.get("hrefs"))\n        pid = evidence["product_id"]'),
        ('"thumb": str(it.get("thumb") or "")[:300], "product_url": "",',
         '"thumb": str(it.get("thumb") or "")[:300], "product_url": evidence["product_url"],\n                       "link_evidence_status": evidence["link_evidence_status"], "observed_product_links": evidence["observed_product_links"],')]
    for old,new in edits:
        if source.count(old)!=1:raise ValueError('Unexpected collector source; inspect before patching')
        source=source.replace(old,new,1)
    compile(source,'cart_capture.py','exec')
    return source


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    with a.output.open('x',encoding='utf-8') as f:f.write(patch(a.source.read_text(encoding='utf-8')))
