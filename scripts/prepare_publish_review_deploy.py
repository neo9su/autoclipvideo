"""Patch only publishing ownership and review endpoints, preserving remote differences."""
import ast,sys
from pathlib import Path
from prepare_2k_deploy import raw_replacements
from prepare_remote_audio_deploy import build as backup_runner


def patch_publisher(source):
    node=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.AsyncFunctionDef) and n.name=='publish')
    lines=source.splitlines(keepends=True);old=''.join(lines[node.lineno-1:node.end_lineno]);body=old
    start=body.index('                if auto_ok:\n');end=body.index('                # Handle possible scan-to-verify',start)
    body=body[:start]+'''                await progress("请打开平台的发布页面确认入口，查看截图后确认发布")
                await wait_for_review(page, task_id, auto_ok)

'''+body[end:]
    anchor='            page = await ctx.new_page()\n'
    assert body.count(anchor)==1
    body=body.replace(anchor,anchor+'            register_review(page, task)\n')
    anchor='            finally:\n                # Save refreshed cookies'
    assert body.count(anchor)==1
    body=body.replace(anchor,'            except Exception as exc:\n                if confirmation_sent(task_id):\n                    raise PublishReviewRequired("已确认发布但结果尚未核实，请先核对作品列表，勿重复发布：" + str(exc)) from exc\n                raise\n            finally:\n                close_review(task_id)\n                # Save refreshed cookies')
    lines[node.lineno-1:node.end_lineno]=[body];source=''.join(lines)
    return 'from publish_review import register_review, close_review, wait_for_review, confirmation_sent, PublishReviewRequired\n'+source


def patch_main(source):
    anchor='app = FastAPI(title="Douyin Recorder", lifespan=lifespan)'
    assert source.count(anchor)==1
    return source.replace(anchor,anchor+'\nfrom publish_review import router as publish_review_router\napp.include_router(publish_review_router)')


def build(main,publisher):
    root=Path(__file__).parents[1]
    plan=[]
    for name,old,new in [('main.py',main,patch_main(main.replace('\r\n','\n'))),('publisher_douyin.py',publisher,patch_publisher(publisher.replace('\r\n','\n')))]:
        compile(new,name,'exec');plan.append((str(Path(r'C:\Users\neo\douyin_backend\backend')/name),raw_replacements(old,new)))
    module=(root/'backend/publish_review.py').read_text()
    # New module has its own drift-checked rollback entry.
    pre='''from pathlib import Path
module_path=Path(r'C:\\Users\\neo\\douyin_backend\\backend\\publish_review.py')
assert not module_path.exists() or module_path.read_bytes().replace(b'\\r\\n',b'\\n') == b'# pending review deployment\\n', 'Review module already exists; inspect before deploy'
module_path.write_bytes(b'# pending review deployment\\n')
'''
    plan.append((r'C:\Users\neo\douyin_backend\backend\publish_review.py',[('# pending review deployment\n',module)]))
    body=backup_runner().split('\n',1)[1].replace("        old=old.replace('\\n',newline);new=new.replace('\\n',newline)", '        pass').replace('remote-audio-','publish-review-').replace('Code restored; restart backend and GPU only when idle. No database changed.','Code restored; restart only the backend to reload. No database changed.')
    return pre+'PLAN = '+repr(plan)+'\n'+body
