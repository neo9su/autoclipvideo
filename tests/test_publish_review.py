import ast,asyncio,secrets,time
from dataclasses import dataclass,field
from pathlib import Path
from types import SimpleNamespace
import pytest

class HTTPException(Exception):
    def __init__(self,status_code,detail):self.status_code=status_code;self.detail=detail

src=(Path(__file__).parents[1]/'backend/publish_review.py').read_text()
tree=ast.parse(src)
keep={'PublishReviewRequired','Review','register_review','close_review','get_review','wait_for_review','confirm','screenshot','observe_result'}
nodes=[n for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in keep]
for n in nodes:n.decorator_list=[] if not isinstance(n,ast.ClassDef) else n.decorator_list
nodes=[n for n in nodes if n.name!='Review']
ns=dict(asyncio=asyncio,secrets=secrets,time=time,HTTPException=HTTPException,Confirmation=object,
        ProductLinkUnavailable=RuntimeError,Review=None,SESSIONS={},Response=lambda content,**kw:SimpleNamespace(content=content,**kw))
review=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Review')
exec(compile(ast.Module(body=[review],type_ignores=[]),'review','exec'),dict(ns,dataclass=dataclass,field=field),ns)
exec(compile(ast.Module(body=nodes,type_ignores=[]),'review','exec'),ns)

class Page:
    url='https://creator.douyin.com/creator-micro/content/upload'
    clicks=0
    def is_closed(self):return False
    def get_by_role(self,*a,**kw):return self
    async def count(self):return 1
    async def is_enabled(self):return True
    async def click(self,**kw):self.clicks+=1
    async def screenshot(self,**kw):return b'png'

@pytest.mark.asyncio
async def test_confirmation_requires_current_screenshot_and_is_single_use():
    p=Page();ns['register_review'](p,{'id':1,'title':'夺回'})
    r=ns['get_review'](1);r.ready=True
    with pytest.raises(HTTPException):await ns['confirm'](1,SimpleNamespace(token='bad'))
    await ns['screenshot'](1);token=r.token
    await ns['confirm'](1,SimpleNamespace(token=token))
    with pytest.raises(HTTPException):await ns['confirm'](1,SimpleNamespace(token=token))
    await ns['wait_for_review'](p,1,False,1)
    assert p.clicks==1
    await ns['screenshot'](1)  # verification screenshots still available after click
    assert not r.token
    ns['close_review'](1)

@pytest.mark.asyncio
async def test_stale_or_unready_confirm_rejected_and_timeout_never_clicks():
    p=Page();ns['register_review'](p,{'id':2})
    await ns['screenshot'](2);r=ns['get_review'](2)
    assert not r.token  # A screenshot taken during upload cannot authorize a later publish.
    with pytest.raises(HTTPException):await ns['confirm'](2,SimpleNamespace(token=r.token))
    r.ready=True;await ns['screenshot'](2);r.captured-=121
    with pytest.raises(HTTPException):await ns['confirm'](2,SimpleNamespace(token=r.token))
    with pytest.raises(RuntimeError,match='超时'):await ns['wait_for_review'](p,2,False,0)
    assert p.clicks==0
    ns['close_review'](2)

@pytest.mark.asyncio
async def test_ambiguous_browser_click_is_not_repeated():
    class BrokenPage(Page):
        async def click(self,**kw):
            self.clicks+=1
            raise TimeoutError('browser did not acknowledge')
    p=BrokenPage();ns['register_review'](p,{'id':3})
    r=ns['get_review'](3);r.ready=True
    await ns['screenshot'](3)
    await ns['confirm'](3,SimpleNamespace(token=r.token))
    with pytest.raises(ns['PublishReviewRequired'],match='结果不明确'):
        await ns['wait_for_review'](p,3,True,1)
    assert p.clicks==1
    with pytest.raises(HTTPException):await ns['confirm'](3,SimpleNamespace(token=''))
    ns['close_review'](3)

@pytest.mark.asyncio
async def test_unavailable_button_is_not_recorded_as_clicked():
    class Disabled(Page):
        async def is_enabled(self):return False
    p=Disabled();ns['register_review'](p,{'id':4});r=ns['get_review'](4);r.event.set()
    with pytest.raises(ns['PublishReviewRequired'],match='未点击'):await ns['wait_for_review'](p,4,True,1)
    assert not r.clicked and r.phase=='not_clicked' and p.clicks==0
    ns['close_review'](4)

@pytest.mark.asyncio
async def test_result_requires_platform_redirect_and_stall_is_reported():
    p=Page();ns['register_review'](p,{'id':5});r=ns['get_review'](5)
    r.clicked=True;r.click_started=time.monotonic()-61
    await ns['observe_result'](r)
    assert r.phase=='needs_check' and '60秒' in r.message
    p.url='https://creator.douyin.com/creator-micro/content/manage'
    await ns['observe_result'](r)
    assert r.phase=='platform_confirmed'
    ns['close_review'](5)
