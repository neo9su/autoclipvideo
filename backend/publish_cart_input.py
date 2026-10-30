"""Durable cart correction queue; resumption requires explicit user input."""
import json
import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from db import aio_connect
from publish_product_links import ProductLinkUnavailable, resolve_publish_products

router = APIRouter()


def needs_cart_input(exc):
    # A publish click with an uncertain outcome must never enter a retry flow.
    from publish_review import PublishReviewRequired
    return isinstance(exc, ProductLinkUnavailable) and not isinstance(exc, PublishReviewRequired)


@router.get('/api/publish-cart-input')
async def waiting_tasks():
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id,title,error_msg,product_ids,product_id FROM publish_tasks WHERE status='waiting_input' ORDER BY id") as cur:
            return [dict(row) for row in await cur.fetchall()]


class CartInput(BaseModel):
    product_ids: list[int]


async def resume_in_db(db, task_id, ids):
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > 10 or any(i <= 0 for i in ids):
        raise HTTPException(400, '请选择1至10件商品库商品ID')
    db.row_factory = aiosqlite.Row
    await db.execute('BEGIN IMMEDIATE')
    async with db.execute('SELECT * FROM publish_tasks WHERE id=?', (task_id,)) as cur:
        task = await cur.fetchone()
    if not task or task['status'] != 'waiting_input':
        raise HTTPException(409, '任务不在等待补充商品状态，请刷新查看，勿重复提交')
    async with db.execute('SELECT * FROM products WHERE id IN ('+','.join('?' for _ in ids)+')', ids) as cur:
        products = [dict(r) for r in await cur.fetchall()]
    try:
        resolve_publish_products({'product_ids': ids}, products)
    except ProductLinkUnavailable as exc:
        raise HTTPException(400, str(exc)) from exc
    await db.execute("UPDATE publish_tasks SET product_ids=?,product_id=?,no_cart=0,status='pending',retry_count=0,error_msg=NULL WHERE id=? AND status='waiting_input'",
                     (','.join(map(str,ids)),ids[0],task_id))
    await db.commit()
    return {'id':task_id,'status':'pending'}


@router.post('/api/publish-cart-input/{task_id}/resume')
async def resume(task_id: int, body: CartInput):
    async with aio_connect() as db:
        return await resume_in_db(db,task_id,body.product_ids)


@router.get('/publish-cart-input', response_class=HTMLResponse)
async def input_page():
    return HTML


@router.get('/publish-cart-input.js')
async def input_banner():
    return Response("""(()=>{async function update(){try{const r=await fetch('/api/publish-cart-input',{cache:'no-store'});if(!r.ok)return;const rows=await r.json();let e=document.getElementById('cart-input-notice');if(!rows.length){e?.remove();return}if(!e){e=document.createElement('a');e.id='cart-input-notice';e.href='/publish-cart-input';e.target='_blank';e.style.cssText='display:block;position:sticky;top:0;z-index:10001;background:#613b08;color:white;padding:12px;text-align:center';document.body.prepend(e)}e.textContent=rows.length+' 个发布任务等待补充挂车商品，点击处理（不会自动重试）'}catch{}}update();setInterval(update,15000)})();""",media_type='application/javascript',headers={'Cache-Control':'no-store'})

HTML = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>补充挂车商品</title>
<style>body{background:#141414;color:#eee;font:18px system-ui;max-width:1000px;margin:30px auto;padding:20px}a{color:#8cc5ff}article{border:1px solid #98631c;padding:20px;margin:20px 0}input,button{font:inherit;padding:10px;margin:8px}input{width:70%}p{white-space:pre-wrap}</style>
<h1>等待补充挂车商品</h1><a href="/frontend/">返回平台商品库</a> · <a href="/frontend/publish-review.html">发布确认页</a>
<p>任务的视频、文案和标签已保留。请先在商品库修正链接，或输入替换商品的商品库ID（逗号分隔，最多10件）。点击继续后，系统重新准备原任务；挂车仍不成功时会再次等待，不会直接发布无车视频。</p>
<button onclick="load()">刷新</button><p id="msg"></p><div id="tasks"></div>
<script>
async function load(){try{const r=await fetch('/api/publish-cart-input',{cache:'no-store'});if(!r.ok)throw Error('读取失败，请刷新重试');const rows=await r.json();const box=document.querySelector('#tasks');box.replaceChildren();document.querySelector('#msg').textContent=rows.length?'':'当前没有等待补充商品的任务';for(const t of rows){const a=document.createElement('article'),h=document.createElement('h3'),p=document.createElement('p'),i=document.createElement('input'),b=document.createElement('button'),m=document.createElement('p');h.textContent='#'+t.id+' '+t.title;p.textContent=t.error_msg;i.value=Array.isArray(t.product_ids)?t.product_ids.join(','):(t.product_ids||t.product_id||'');i.placeholder='商品库ID，例如875,683';b.textContent='使用这些商品继续原任务';b.onclick=async()=>{b.disabled=true;try{const parts=i.value.trim().split(/[,，\s]+/);if(!parts.every(x=>/^\d+$/.test(x)))throw Error('请输入有效的商品库ID');const r=await fetch('/api/publish-cart-input/'+t.id+'/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_ids:parts.map(Number)})});if(!r.ok)throw Error((await r.json()).detail||'提交失败');m.textContent='已恢复原任务，请返回发布页查看进度';i.disabled=true}catch(e){m.textContent=e.message;b.disabled=false}};a.append(h,p,i,b,m);box.append(a)}}catch(e){document.querySelector('#msg').textContent=e.message}}load();
</script></html>'''
