"""Review the browser owned by the publishing coroutine, including SYSTEM sessions."""
import asyncio
import secrets
import time
from dataclasses import dataclass, field
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from publish_product_links import ProductLinkUnavailable

class PublishReviewRequired(ProductLinkUnavailable):
    """Needs a human status check; never automatically repeat a publish attempt."""


def confirmation_sent(task_id):
    review = SESSIONS.get(int(task_id))
    return bool(review and review.requested)


router = APIRouter()
SESSIONS = {}


@dataclass
class Review:
    page: object
    title: str
    product_ids: list
    ready: bool = False
    requested: bool = False
    clicked: bool = False
    token: str = ''
    captured: float = 0
    message: str = '正在准备视频、文案和挂车'
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    event: asyncio.Event = field(default_factory=asyncio.Event)


def register_review(page, task):
    SESSIONS[int(task['id'])] = Review(page, task.get('title') or '', task.get('product_ids') or [])


def close_review(task_id):
    SESSIONS.pop(int(task_id), None)


def get_review(task_id):
    review = SESSIONS.get(int(task_id))
    if review is None or review.page.is_closed():
        raise HTTPException(409, '该任务当前没有可操作的发布页面；请查看任务最终状态')
    return review


async def wait_for_review(page, task_id, check_passed, timeout=1800):
    review = get_review(task_id)
    review.ready = True
    review.message = ('平台检测通过，请查看截图并确认商品后发布' if check_passed else
                      '平台检测结果不明确，请检查页面提示、视频和挂车后决定是否发布')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.is_closed():
            raise PublishReviewRequired('发布页面已关闭，未确认成功')
        if '/content/manage' in page.url:
            return
        if review.event.is_set():
            async with review.lock:
                # Exactly one click. Never retry an ambiguous browser submission.
                review.clicked = True
                review.ready = False
                review.message = '已发送发布点击，等待抖音确认；请勿重复提交'
                button = page.get_by_role('button', name='发布', exact=True)
                if await button.count() != 1 or not await button.is_enabled():
                    raise PublishReviewRequired('发布按钮不唯一或不可用，未点击；请检查页面')
                try:
                    await button.click(timeout=10000)
                except Exception as exc:
                    raise PublishReviewRequired('发布点击结果不明确，请先核对作品列表，勿重复发布') from exc
            return
        await asyncio.sleep(0.5)
    raise PublishReviewRequired('等待网页确认发布超时，未自动点击发布')


@router.get('/api/publish-review')
async def list_reviews():
    return [dict(id=key, title=value.title, product_ids=value.product_ids,
                 ready=value.ready and not value.requested, message=value.message,
                 clicked=value.clicked) for key,value in SESSIONS.items() if not value.page.is_closed()]


@router.get('/api/publish-review/{task_id}/screenshot')
async def screenshot(task_id: int):
    review = get_review(task_id)
    async with review.lock:
        png = await review.page.screenshot(full_page=True, timeout=15000)
        review.token = secrets.token_urlsafe(24) if review.ready and not review.requested else ''
        review.captured = time.monotonic()
        return Response(png, media_type='image/png', headers={
            'Cache-Control':'no-store', 'X-Review-Token':review.token})


class Confirmation(BaseModel):
    token: str


@router.post('/api/publish-review/{task_id}/confirm')
async def confirm(task_id: int, body: Confirmation):
    review = get_review(task_id)
    async with review.lock:
        if not review.ready or review.requested or review.clicked:
            raise HTTPException(409, '任务尚未准备完成或已经提交发布')
        if not review.token or not secrets.compare_digest(body.token, review.token) or time.monotonic()-review.captured > 120:
            raise HTTPException(409, '请先刷新并查看最近两分钟的页面截图')
        review.requested = True
        review.token = ''
        review.event.set()
    return {'id':task_id,'status':'confirmation_queued'}


@router.get('/publish-review', response_class=HTMLResponse)
async def review_page():
    return REVIEW_HTML


REVIEW_HTML = '''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>发布页面确认</title>
<style>body{background:#141414;color:#eee;font:16px system-ui;max-width:1100px;margin:30px auto;padding:16px}button,select{font:inherit;padding:10px;margin:8px 8px 8px 0}button:disabled{opacity:.4}img{width:100%;border:1px solid #555}a{color:#8cc5ff}#msg{white-space:pre-wrap}</style>
<h2>发布页面确认</h2><a href="/">返回平台</a><p>直接查看服务器上的发布页面。确认视频、文案和挂车商品正确后，再点击确认发布。</p>
<select id="tasks"></select><button id="refresh">刷新截图</button><p id="msg"></p>
<label><input type="checkbox" id="checked">我已查看本次截图，确认视频、文案和挂车商品正确，并检查平台提示</label><br>
<button id="submit" disabled>确认发布这一个作品</button><p id="empty"></p><img id="shot" hidden>
<script>
const tasks=document.querySelector('#tasks'),msg=document.querySelector('#msg'),shot=document.querySelector('#shot'),checked=document.querySelector('#checked'),submit=document.querySelector('#submit');let rows=[],token='',loadedId='',busy=false,url='';
function enabled(){submit.disabled=busy||!checked.checked||!token||loadedId!==tasks.value||!rows.find(x=>String(x.id)===tasks.value)?.ready}
async function list(){const r=await fetch('/api/publish-review',{cache:'no-store'});if(!r.ok)throw Error('无法读取任务');rows=await r.json();const old=tasks.value;tasks.replaceChildren();for(const t of rows){const o=document.createElement('option');o.value=t.id;o.textContent=t.id+' · '+t.title;tasks.append(o)}if(rows.some(x=>String(x.id)===old))tasks.value=old;document.querySelector('#empty').textContent=rows.length?'':'当前没有运行中的发布页面。请返回平台查看任务状态；失败任务可重试。';msg.textContent=rows.find(x=>String(x.id)===tasks.value)?.message||'';enabled()}
async function capture(){token='';checked.checked=false;loadedId='';shot.hidden=true;enabled();const id=tasks.value;if(!id)return;const r=await fetch('/api/publish-review/'+id+'/screenshot',{cache:'no-store'});if(!r.ok)throw Error((await r.json()).detail||'截图失败');const blob=await r.blob();if(tasks.value!==id)return;if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(blob);shot.src=url;shot.hidden=false;token=r.headers.get('X-Review-Token');loadedId=id;enabled()}
tasks.onchange=()=>capture().catch(e=>msg.textContent=e.message);checked.onchange=enabled;document.querySelector('#refresh').onclick=()=>capture().catch(e=>msg.textContent=e.message);
submit.onclick=async()=>{if(submit.disabled)return;busy=true;enabled();try{const r=await fetch('/api/publish-review/'+loadedId+'/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});token='';if(!r.ok)throw Error((await r.json()).detail||'提交失败');msg.textContent='确认已送达，正在等待抖音发布结果。请勿重复创建任务。'}catch(e){msg.textContent=e.message+'；请先核对任务状态，不要重复提交。'}finally{enabled()}};
list().then(capture).catch(e=>msg.textContent=e.message);setInterval(()=>list().catch(e=>msg.textContent=e.message),5000);
</script></html>'''
