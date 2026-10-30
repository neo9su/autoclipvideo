"""Stage a targeted scheduler patch without overwriting unrelated production code."""
from pathlib import Path
import argparse


def patch(source):
    start=source.index('        # Resolve product links (product_url preferred, fallback to product_id)')
    end=source.index('        url = await publisher.publish(task_ctx, video_path)',start)
    source=source[:start]+'''        if platform == "douyin" and resolved_products["links"]:
            task_ctx["_product_douyin_ids"] = resolved_products["links"]
            task_ctx["_product_names"] = resolved_products["names"]

'''+source[end:]
    anchor='        publisher = _get_publisher(platform)\n'
    if source.count(anchor)!=1:raise ValueError('Publisher setup drifted')
    source=source.replace(anchor,'''        resolved_products = {"links": [], "names": []}
        if platform == "douyin":
            if task.get("no_cart") in (True, 1, "1"):
                resolved_products = resolve_publish_products(task, [])
            else:
                async with aio_connect() as product_db:
                    product_db.row_factory = aiosqlite.Row
                    async with product_db.execute("SELECT id, product_id, product_name, product_url FROM products") as cur:
                        catalogue = [dict(row) for row in await cur.fetchall()]
                resolved_products = resolve_publish_products(task, catalogue)

'''+anchor,1)
    anchor='from notifier import notify\n'
    if source.count(anchor)!=1:raise ValueError('Import anchor drifted')
    source=source.replace(anchor,anchor+'from publish_product_links import ProductLinkUnavailable, resolve_publish_products\n',1)
    anchor='        is_retryable = not any(kw in err_msg for kw in non_retryable)'
    if source.count(anchor)!=1:raise ValueError('Retry handler drifted')
    source=source.replace(anchor,'        is_retryable = not isinstance(e, ProductLinkUnavailable) and not any(kw in err_msg for kw in non_retryable)',1)
    compile(source,'publish_scheduler.py','exec')
    return source


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    with a.output.open('x',encoding='utf-8') as f:f.write(patch(a.source.read_text(encoding='utf-8')))
