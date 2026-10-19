import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from publish_cart_flow import attach_selected_products,ProductLinkUnavailable

@pytest.mark.asyncio
async def test_known_unavailable_candidate_does_not_hide_other_successful_links():
    calls=[]
    async def attach(page,link,short_title):
        calls.append(link)
        if link=='bad':raise ProductLinkUnavailable('未搜索到对应商品')
    result=await attach_selected_products(None,['bad','good1','good2'],['a','b','c'],attach)
    assert calls==['bad','good1'] and result['attached']==[1]
    assert result['failed'][0]['name']=='a'

@pytest.mark.asyncio
async def test_no_success_never_allows_publish_and_ambiguous_error_is_not_skipped():
    async def unavailable(*args,**kwargs):raise ProductLinkUnavailable('无效')
    with pytest.raises(ProductLinkUnavailable,match='均未能挂车'):
        await attach_selected_products(None,['bad'],[],unavailable)
    async def uncertain(*args,**kwargs):raise RuntimeError('未确认挂车结果')
    with pytest.raises(RuntimeError,match='未确认'):
        await attach_selected_products(None,['uncertain','good'],[],uncertain)

@pytest.mark.asyncio
async def test_first_success_stops_before_later_error():
    calls=[]
    async def attach(page,link,short_title):
        calls.append(link)
        if link=='later_error':raise RuntimeError('must not be attempted')
    result=await attach_selected_products(None,['good','later_error'],[],attach)
    assert calls==['good'] and result['attached']==[0]

@pytest.mark.asyncio
async def test_uncertain_cart_is_not_retried_with_another_link():
    from publish_cart_flow import CartOutcomeUnclear
    calls=[]
    async def attach(page,link,short_title):
        calls.append(link);raise CartOutcomeUnclear('需要核对现场')
    with pytest.raises(CartOutcomeUnclear):
        await attach_selected_products(None,['uncertain','good'],[],attach)
    assert calls==['uncertain']
