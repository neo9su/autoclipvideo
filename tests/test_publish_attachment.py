"""Offline page fixtures; never start a browser or submit a real publication."""
import ast
import asyncio
import logging
from pathlib import Path

import pytest

from backend.publish_product_links import ProductLinkUnavailable, resolve_publish_products
from scripts.patch_publish_attachment import patch


class Element:
    def __init__(self, page, kind): self.page, self.kind = page, kind
    @property
    def first(self): return self
    async def wait_for(self, **kwargs):
        if self.kind == 'edit' and kwargs.get('state') == 'hidden' and self.page.mode == 'stuck_dialog':
            raise RuntimeError('fixture: dialog still visible')
    async def scroll_into_view_if_needed(self): pass
    async def click(self): pass
    async def clear(self): pass
    async def input_value(self): return ''
    async def fill(self, value):
        if self.page.mode == 'fill_error': raise RuntimeError('fixture: input lost')
        self.page.filled = value
    async def bounding_box(self): return None
    async def get_attribute(self, key):
        return 'disabled' if self.page.mode == 'disabled' and key == 'class' else None
    async def is_visible(self, **kwargs):
        if self.kind == 'add': return self.page.mode != 'missing_button'
        if self.kind == 'error': return self.page.mode == 'not_found'
        if self.kind == 'edit': return self.page.mode in ('success', 'stuck_dialog')
        return True


class Page:
    def __init__(self, mode): self.mode, self.filled = mode, None
    def locator(self, selector):
        kind = 'edit' if '编辑商品' in selector else 'error' if '未搜索到对应商品' in selector else 'other'
        return Element(self, kind)
    def get_by_text(self, *args, **kwargs): return Element(self, 'add')
    async def evaluate(self, *args): return False


def load_attach(source):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_attach_product')
    async def sleep(seconds): pass
    async def sibling(*args): return None
    # Isolated asyncio object avoids changing the test runner/event loop.
    class Async:
        pass
    Async.sleep = staticmethod(sleep)
    scope = dict(asyncio=Async, logger=logging.getLogger('attachment-test'),
                 _find_sibling_button=sibling, ProductLinkUnavailable=ProductLinkUnavailable)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'attachment-fixture', 'exec'), scope)
    return scope['_attach_product']


@pytest.mark.parametrize('mode', ['missing_button','disabled','not_found','fill_error','no_dialog','stuck_dialog'])
def test_attachment_failure_propagates(mode):
    attach = load_attach((Path(__file__).parents[1] / 'backend/publisher_douyin.py').read_text())
    with pytest.raises(RuntimeError):
        asyncio.run(attach(Page(mode), 'https://example.invalid/item', '测试假发'))


def test_dialog_completion_path():
    attach = load_attach((Path(__file__).parents[1] / 'backend/publisher_douyin.py').read_text())
    page = Page('success')
    asyncio.run(attach(page, 'https://example.invalid/item', '测试假发'))
    assert page.filled == '测试假发'


def test_selection_over_five_is_not_silently_truncated():
    products = [dict(id=i, product_url=f'https://example.invalid/{i}', product_name='同名') for i in range(1,7)]
    with pytest.raises(ProductLinkUnavailable, match='最多挂车5'):
        resolve_publish_products(dict(product_ids='1,2,3,4,5,6'), products)
    assert len(resolve_publish_products(dict(product_ids='1,2,3,4,5'), products)['links']) == 5


def test_patch_refuses_already_patched_source():
    source = (Path(__file__).parents[1] / 'backend/publisher_douyin.py').read_text()
    with pytest.raises(ValueError): patch(source)
