import asyncio
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from publish_cart_flow import attach_selected_products,ProductLinkUnavailable,CartOutcomeUnclear

@pytest.mark.asyncio
async def test_attempts_every_selected_item_despite_mixed_failures():
    calls=[]
    async def attach(page,link,short_title):
        calls.append((link,short_title))
        if link=='unavailable':raise ProductLinkUnavailable('下架')
        if link=='uncertain':raise CartOutcomeUnclear('未确认')
        if link=='error':raise RuntimeError('页面异常')
    links=['good1','unavailable','uncertain','error','good2']
    result=await attach_selected_products(None,links,['a','b','c','d','e'],attach)
    assert [x[0] for x in calls]==links
    assert result['attached']==[0,4]
    assert [x['index'] for x in result['failed']]==[1,2,3]
    assert [x['name'] for x in result['failed']]==['b','c','d']
    assert [x['reason'] for x in result['failed']]==['下架','未确认','页面异常']

@pytest.mark.asyncio
async def test_all_failed_attempts_all_before_stopping_publish():
    calls=[]
    async def attach(page,link,short_title):
        calls.append(link)
        if link=='uncertain':raise CartOutcomeUnclear('未知结果')
        raise ProductLinkUnavailable('不可用')
    with pytest.raises(ProductLinkUnavailable,match='均未能挂车'):
        await attach_selected_products(None,['bad','uncertain','bad2'],[],attach)
    assert calls==['bad','uncertain','bad2']

@pytest.mark.asyncio
async def test_one_success_survives_later_failures():
    calls=[]
    async def attach(page,link,short_title):
        calls.append(link)
        if link!='good':raise RuntimeError('失败')
    result=await attach_selected_products(None,['good','bad','bad2'],[],attach)
    assert calls==['good','bad','bad2']
    assert result['attached']==[0] and len(result['failed'])==2

@pytest.mark.asyncio
async def test_task_cancellation_still_stops_work():
    async def attach(*args,**kwargs):raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await attach_selected_products(None,['one','two'],[],attach)
