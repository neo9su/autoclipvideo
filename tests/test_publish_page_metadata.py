"""Execute the real metadata-entry block against offline page controls."""
import asyncio
import logging
from pathlib import Path
import textwrap
import types

import pytest


def load_entry(page, task, phases):
    source=(Path(__file__).parents[1]/'backend/publisher_douyin.py').read_text()
    start=source.index('                # 4. Fill title')
    end=source.index('                # 6. Attach products',start)
    snippet=textwrap.dedent(source[start:end])
    async def noop(*args,**kwargs): pass
    async def next_phase(): phases.append('cart/publish')
    scope=dict(asyncio=types.SimpleNamespace(sleep=noop),logger=logging.getLogger('page-metadata'),
               progress=noop,_show_banner=noop,_dismiss_overlays=noop,next_phase=next_phase)
    exec('async def run(task,page):\n'+textwrap.indent(snippet,'    ')+'\n    await next_phase()\n',scope)
    return scope['run'](task,page)


class Element:
    def __init__(self,page,kind):self.page,self.kind=page,kind
    @property
    def first(self):return self
    async def wait_for(self,**kwargs):pass
    async def scroll_into_view_if_needed(self):pass
    async def focus(self):pass
    async def clear(self):self.page.values[self.kind]=''
    async def click(self,**kwargs):pass
    async def fill(self,value):
        if self.kind=='title' and self.page.mode=='title_error':raise RuntimeError('fixture title lost')
        if self.kind=='title' and self.page.mode=='silent_title':return
        self.page.values[self.kind]=value
    async def input_value(self):return self.page.values[self.kind]
    async def type(self,value,**kwargs):
        if self.page.mode=='description_error':raise RuntimeError('fixture description lost')
        if value.startswith(' #') and self.page.mode=='tag_error':raise RuntimeError('fixture tag failed')
        self.page.values[self.kind]+=value
    async def is_visible(self):return False


class Page:
    def __init__(self,mode):
        self.mode=mode;self.values={'title':'旧标题','description':'旧的其他发型描述'}
        async def press(key):pass
        self.keyboard=types.SimpleNamespace(press=press)
    def locator(self,selector):
        kind='title' if selector.startswith('textarea') else 'suggestion' if 'topic-item' in selector else 'description'
        return Element(self,kind)


@pytest.mark.parametrize('mode',['title_error','description_error','tag_error','silent_title'])
def test_metadata_entry_failure_never_reaches_cart(mode):
    page=Page(mode);phases=[]
    with pytest.raises(RuntimeError):
        asyncio.run(load_entry(page,dict(title='新标题',description='本款描述',tags='假发'),phases))
    assert phases==[]


@pytest.mark.parametrize('description,tags',[('本款描述','假发,发型'),('','假发'),('本款描述','')])
def test_metadata_replaces_old_description_and_preserves_requested_content(description,tags):
    page=Page('success');phases=[]
    asyncio.run(load_entry(page,dict(title='新标题',description=description,tags=tags),phases))
    assert page.values['title']=='新标题'
    assert page.values['description']==description+''.join(' #'+tag for tag in tags.split(',') if tag)
    assert phases==['cart/publish']
