"""Try each explicitly selected related product; never ignore an ambiguous result."""
try:
    from .publish_product_links import ProductLinkUnavailable
except ImportError:
    from publish_product_links import ProductLinkUnavailable


class CartOutcomeUnclear(ProductLinkUnavailable):
    """Stop the task without retrying another link after an ambiguous click."""


async def attach_selected_products(page, links, names, attach):
    attached=[];failed=[]
    for index,link in enumerate(links):
        name=names[index] if index<len(names) else ''
        try:
            await attach(page,link,short_title=name)
        except CartOutcomeUnclear:
            raise
        except ProductLinkUnavailable as exc:
            failed.append({'index':index,'name':name,'reason':str(exc)})
        else:
            attached.append(index)
            # One confirmed cart item satisfies the task; later candidates cannot undo it.
            return {'attached':attached,'failed':failed}
    if not attached:
        raise ProductLinkUnavailable('所选商品链接均未能挂车，请检查商品链接及账号权限；未执行发布')
    return {'attached':attached,'failed':failed}
