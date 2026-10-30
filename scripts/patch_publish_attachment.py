"""Patch only confirmed cart failure handling; preserve production browser setup."""
import argparse
from pathlib import Path


def patch(source):
    replacements = [
        ('from publisher_base import BasePublisher\n', 'from publisher_base import BasePublisher\nfrom publish_product_links import ProductLinkUnavailable\n'),
        ('                product_ids = (task.get("_product_douyin_ids") or [])[:5]',
         '                product_ids = task.get("_product_douyin_ids") or []\n                if len(product_ids) > 5 and not task.get("no_cart"):\n                    raise ProductLinkUnavailable("一次最多挂车5个商品，请减少商品选择后重试")'),
        ('            logger.warning(f"添加链接 element not found for: {product_link}")\n            await link_input.clear()\n            return',
         '            await link_input.clear()\n            raise RuntimeError("商品挂车失败：未找到添加链接入口，请检查发布页面")'),
        ('            logger.warning(f"添加链接 still disabled after 5 s — invalid link: {product_link}")\n            await link_input.clear()\n            return',
         '            await link_input.clear()\n            raise ProductLinkUnavailable("商品链接未通过发布页面校验，请检查链接及账号挂车权限")'),
        ('            logger.warning(f"Product not found / unsupported link: {product_link}")',
         '            logger.warning("Product not found / unsupported link")'),
        ('            return\n\n        # 7. Handle 编辑商品 dialog',
         '            raise ProductLinkUnavailable("发布页面未搜索到对应商品，请修改商品链接或检查账号挂车权限")\n\n        # 7. Handle 编辑商品 dialog'),
        ('            await done_btn.click()\n            await asyncio.sleep(1)\n            logger.info(f"编辑商品 confirmed for {product_link}")\n        else:\n            logger.info(f"Product added (no dialog): {product_link}")',
         '            await done_btn.click()\n            await edit_dialog.wait_for(state="hidden", timeout=8000)\n            logger.info("编辑商品 dialog completed")\n        else:\n            raise RuntimeError("未确认商品挂车结果：未出现编辑商品确认，请检查发布页面后重试")'),
        ('        logger.warning(f"_attach_product failed ({product_link}): {e}")',
         '        logger.warning("商品挂车未完成 (%s)", type(e).__name__)'),
    ]
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError('Attachment source drifted: '+before.splitlines()[0])
        source = source.replace(before, after, 1)
    # The handler is the final function in both current production and repository.
    if not source.rstrip().endswith('        except Exception:\n            pass'):
        raise ValueError('Attachment handler tail drifted')
    source = source.rstrip() + '\n        raise\n'
    compile(source, 'publisher_douyin.py', 'exec')
    return source


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    with args.output.open('x',encoding='utf-8') as output:output.write(patch(args.source.read_text(encoding='utf-8-sig')))
