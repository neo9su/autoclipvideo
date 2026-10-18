"""Enable fallback across explicitly selected products while preserving remote code."""
from pathlib import Path
import inspect
from prepare_2k_deploy import raw_replacements
from prepare_remote_audio_deploy import build as backup_runner


def build():
    root=Path(__file__).parents[1]
    old_loop='''                    for i, pid in enumerate(product_ids):
                        name = product_names[i] if i < len(product_names) else ""
                        await _attach_product(page, pid, short_title=name)'''
    new_loop='''                    cart_result = await attach_selected_products(page, product_ids, product_names, _attach_product)
                    update_cart_result(task_id, cart_result)
                    await progress(f"已挂车 {len(cart_result['attached'])} 件；{len(cart_result['failed'])} 件链接未通过，详情见发布确认页")'''
    setup='from pathlib import Path\nimport difflib,hashlib\n'+inspect.getsource(raw_replacements)+'\n'
    setup+='OLD_LOOP='+repr(old_loop)+'\nNEW_LOOP='+repr(new_loop)+'\nREVIEW='+repr((root/'backend/publish_review.py').read_text())+'\nCART='+repr((root/'backend/publish_cart_flow.py').read_text())+'\n'
    setup+=r'''
root=Path(r'C:\Users\neo\douyin_backend\backend');p=root/'publisher_douyin.py';raw=p.read_bytes().decode('utf-8');s=raw.replace('\r\n','\n')
assert s.count(OLD_LOOP)==1
s=s.replace(OLD_LOOP,NEW_LOOP)
assert s.count('confirmation_sent, PublishReviewRequired')==1
s='from publish_cart_flow import attach_selected_products\n'+s.replace('confirmation_sent, PublishReviewRequired','confirmation_sent, PublishReviewRequired, update_cart_result')
r=root/'publish_review.py';before=r.read_bytes();assert hashlib.sha256(before).hexdigest()=='59eb8141b914145b3c4cd86e2a0cbf6e863f590ed3b36a15aafe9c1a46e1b8fb', 'Review source drift'
mod=root/'publish_cart_flow.py';assert not mod.exists();mod.write_bytes(b'# pending cart flow deployment\n')
PLAN=[(str(p),raw_replacements(raw,s)),(str(r),raw_replacements(before.decode('utf-8'),REVIEW)),(str(mod),[('# pending cart flow deployment\n',CART)])]
'''
    return setup+backup_runner().split('\n',1)[1].replace('remote-audio-','publish-cart-fallback-').replace("old=old.replace('\\n',newline);new=new.replace('\\n',newline)",'pass').replace('Code restored; restart backend and GPU only when idle. No database changed.','Code restored; restart only backend. No database changed.')


if __name__=='__main__':print(build())
