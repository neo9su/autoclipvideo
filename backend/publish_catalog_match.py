"""Name-based cart candidates, including explicitly confirmed spoken aliases."""
from urllib.parse import urlsplit, parse_qs
try:
    from .product_link_edit import validate_url
except ImportError:
    from product_link_edit import validate_url


def search_term(group, query=''):
    text=str(query or group.get('wig_model') or group.get('label') or '').strip().lower()
    return '氧气' if '氧气' in text else str(query or '').strip().lower()


def match_candidates(group, products, query=''):
    term=search_term(group,query)
    if not term:return []
    matches=[];seen=set();room=group.get('room_id')
    for item in products:
        row=dict(item)
        if not row.get('enabled') or (room and row.get('room_id') not in (room,None,0,'')):continue
        # A stray keyword on another hairstyle is not name evidence.
        if term not in str(row.get('product_name') or '').lower():continue
        try:url=validate_url(row.get('product_url') or '')
        except ValueError:continue
        if not url:continue
        parsed=urlsplit(url);pid=parse_qs(parsed.query).get('id',[''])[0]
        key=(parsed.netloc.lower(),pid) if pid else url
        if key in seen:continue
        seen.add(key);row['product_url']=url;matches.append(row)
    return sorted(matches,key=lambda p:p['id'])
