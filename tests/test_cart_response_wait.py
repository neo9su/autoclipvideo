"""Exercise real cart submission function against a delayed/absent platform response."""
import ast,asyncio,logging
from pathlib import Path
from types import SimpleNamespace
import pytest
from publish_cart_flow import CartOutcomeUnclear,ProductLinkUnavailable
source=(Path(__file__).parents[1]/'backend/publisher_douyin.py').read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_attach_product')
async def no_sleep(*a):pass
async def evidence(*a):return 'cart-evidence.json'
ns=dict(asyncio=SimpleNamespace(sleep=no_sleep),logger=logging.getLogger('test'),CartOutcomeUnclear=CartOutcomeUnclear,ProductLinkUnavailable=ProductLinkUnavailable,_capture_upload_diagnostics=evidence)
exec(compile(ast.Module(body=[node],type_ignores=[]),'cart','exec'),ns)
class Locator:
    def __init__(self,page,selector):self.page=page;self.selector=selector
    @property
    def first(self):return self
    async def wait_for(self,**kw):
        if kw.get('timeout')==30000:
            self.page.waited=True
            if self.page.missing:raise TimeoutError()
    async def scroll_into_view_if_needed(self):pass
    async def click(self,**kw):
        if self.selector=='add':self.page.clicks+=1
    async def fill(self,value):pass
    async def clear(self):pass
    async def get_attribute(self,name):return None
    async def is_visible(self,**kw):
        return self.selector=='add' or ('编辑商品' in self.selector and self.page.waited and not self.page.missing)
    async def input_value(self):return '商品短名'
class Page:
    def __init__(self,missing=False):self.missing=missing;self.waited=False;self.clicks=0
    def locator(self,selector):return Locator(self,selector)
    def get_by_text(self,*a,**kw):return Locator(self,'add')
@pytest.mark.asyncio
async def test_delayed_dialog_waited_for_without_second_submission():
    p=Page();await ns['_attach_product'](p,'https://example.test/product','商品')
    assert p.waited and p.clicks==1
@pytest.mark.asyncio
async def test_absent_response_saves_evidence_and_stops():
    p=Page(True)
    with pytest.raises(CartOutcomeUnclear,match='cart-evidence.json'):
        await ns['_attach_product'](p,'https://example.test/product','商品')
    assert p.clicks==1
