"""Separate editable cart URLs from product identity during automatic editing."""
from prepare_remote_audio_deploy import build as backup_runner


def build():
    plan=[(r'C:\Users\neo\douyin_backend\backend\api_v2.py',[
        ('if not isinstance(product, dict) or not str(product.get("product_url") or "").startswith(("http://", "https://")):',
         'if not isinstance(product, dict):'),
        ('if not match.get("ok") or not product_context or not product_context.get("product_url"):',
         'if not match.get("ok") or not product_context:'),
        ('商品链接或商品强匹配不足，拒绝自动续跑','商品匹配不足，无法确定当前商品'),
    ])]
    body=backup_runner().split('\n',1)[1].replace("'remote-audio-'", "'unlinked-product-edit-'")
    return 'PLAN = '+repr(plan)+'\n'+body


if __name__=='__main__':
    print(build())
