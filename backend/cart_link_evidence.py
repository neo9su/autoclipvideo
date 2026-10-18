"""Retain observed card links; never invent a platform ID from a title or HTML number."""
import hashlib
import re
from urllib.parse import urlsplit,parse_qs


def card_link_evidence(title, hrefs):
    observed=[]
    for href in hrefs if isinstance(hrefs,list) else []:
        if not isinstance(href,str) or len(href)>2000 or any(c.isspace() for c in href):continue
        try:
            u=urlsplit(href);ids=parse_qs(u.query).get('id',[])
            valid=(u.scheme=='https' and u.hostname=='haohuo.jinritemai.com' and not u.username
                   and not u.password and u.port in (None,443) and u.path=='/ecommerce/trade/detail/index.html'
                   and len(ids)==1 and re.fullmatch(r'[0-9]{19}',ids[0]))
        except ValueError:continue
        if valid and href not in [r['url'] for r in observed]:observed.append({'product_id':ids[0],'url':href})
    identities={r['product_id'] for r in observed}
    single=len(identities)==1
    return {'product_id':observed[0]['product_id'] if single else 'dom_'+hashlib.md5(title.encode()).hexdigest()[:12],
            'product_url':observed[0]['url'] if single else '',
            'observed_product_links':observed,
            'link_evidence_status':'observed_single_product' if single else 'multiple_products_in_card' if identities else 'missing_observed_link'}
