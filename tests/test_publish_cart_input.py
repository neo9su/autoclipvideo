import sys
from pathlib import Path
import pytest
import aiosqlite
from fastapi import HTTPException
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from publish_cart_input import needs_cart_input,resume_in_db
from publish_product_links import ProductLinkUnavailable
from publish_review import PublishReviewRequired


def test_only_cart_errors_wait_not_uncertain_publish():
    assert needs_cart_input(ProductLinkUnavailable('all failed'))
    assert not needs_cart_input(PublishReviewRequired('already clicked'))
    assert not needs_cart_input(RuntimeError('upload'))

@pytest.mark.asyncio
async def test_resume_is_explicit_preserves_content_and_rejects_duplicate():
    async with aiosqlite.connect(':memory:') as db:
        await db.executescript("CREATE TABLE products(id INTEGER,product_name TEXT,product_url TEXT); CREATE TABLE publish_tasks(id INTEGER,status TEXT,product_ids TEXT,product_id INTEGER,no_cart INTEGER,retry_count INTEGER,error_msg TEXT,title TEXT,video_path TEXT); INSERT INTO products VALUES(875,'test','https://example.invalid/good'); INSERT INTO publish_tasks VALUES(1,'waiting_input','1',1,0,2,'bad','title','video.mp4');")
        await resume_in_db(db,1,[875])
        r=await (await db.execute('SELECT * FROM publish_tasks')).fetchone()
        assert r['status']=='pending' and r['product_ids']=='875'
        assert r['title']=='title' and r['video_path']=='video.mp4' and r['retry_count']==0
        with pytest.raises(HTTPException) as e: await resume_in_db(db,1,[875])
        assert e.value.status_code==409

@pytest.mark.asyncio
async def test_bad_link_keeps_waiting_and_eleven_rejected():
    async with aiosqlite.connect(':memory:') as db:
        await db.executescript("CREATE TABLE products(id INTEGER,product_name TEXT,product_url TEXT); CREATE TABLE publish_tasks(id INTEGER,status TEXT); INSERT INTO products VALUES(875,'test',''); INSERT INTO publish_tasks VALUES(1,'waiting_input');")
        with pytest.raises(HTTPException) as e:await resume_in_db(db,1,[875])
        assert e.value.status_code==400
        assert (await (await db.execute('SELECT status FROM publish_tasks')).fetchone())[0]=='waiting_input'
        await db.rollback()
        with pytest.raises(HTTPException):await resume_in_db(db,1,list(range(1,12)))
