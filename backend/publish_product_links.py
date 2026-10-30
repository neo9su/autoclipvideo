"""Resolve cart inputs from stored URLs; never manufacture a URL from an ID."""
try:
    from .product_link_edit import validate_url
except ImportError:
    from product_link_edit import validate_url


class ProductLinkUnavailable(RuntimeError):
    """Needs catalogue/user correction, not an automatic network retry."""


def _id(value):
    text=str(value).strip()
    if not text.isascii() or not text.isdigit() or int(text)<=0:
        raise ProductLinkUnavailable('商品选择无效，请在发布页面重新选择商品')
    return int(text)


def _url(value):
    try:
        result=validate_url(value)
    except ValueError:
        result=''
    if not result:raise ProductLinkUnavailable('商品链接缺失或无效，请在商品库填写正确链接后重试')
    return result


def resolve_publish_products(task, products):
    if task.get('no_cart') in (True,1,'1'):
        return {'links':[],'names':[]}
    rows=[dict(p) for p in products]
    raw=task.get('product_ids')
    if raw:
        if isinstance(raw,str):
            selected=[_id(x) for x in raw.split(',') if x.strip()]
        elif isinstance(raw,(list,tuple)):
            selected=[_id(x) for x in raw]
        else:raise ProductLinkUnavailable('商品选择无效，请在发布页面重新选择商品')
        if not selected:raise ProductLinkUnavailable('请选择需要挂车的商品，或明确选择无车发布')
    elif task.get('product_id') is not None:
        selected=[_id(task['product_id'])]
    else:
        selected=[]
    links=[];names=[]
    if selected:
        by_id={p['id']:p for p in rows}
        for identity in dict.fromkeys(selected):
            p=by_id.get(identity)
            if p is None:raise ProductLinkUnavailable(f'商品#{identity}已不存在，请重新选择商品')
            link=_url(p.get('product_url'))
            if link not in links:links.append(link);names.append(p.get('product_name') or '')
    else:
        legacy=str(task.get('product_douyin_id') or '').strip()
        if legacy.startswith(('https://','http://')):
            links=[_url(legacy)];names=['']
        elif legacy:
            matches=[p for p in rows if str(p.get('product_id') or '')==legacy]
            options={_url(p.get('product_url')) for p in matches}
            if len(options)!=1:
                raise ProductLinkUnavailable('旧发布任务无法确定商品链接，请在发布页面重新选择商品')
            link=options.pop();links=[link];names=[next(p.get('product_name') or '' for p in matches if _url(p.get('product_url'))==link)]
        else:raise ProductLinkUnavailable('请选择需要挂车的商品，或明确选择无车发布')
    if len(links)>10:
        raise ProductLinkUnavailable('一次最多挂车10个商品，请减少商品选择后重试')
    return {'links':links,'names':names}
