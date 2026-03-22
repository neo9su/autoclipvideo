"""
Douyin (TikTok CN) publisher via Playwright browser automation.
Upload page: https://creator.douyin.com/creator-micro/content/upload
"""
import asyncio
import json
import logging
import os
from typing import Optional

from publisher_base import BasePublisher

logger = logging.getLogger(__name__)

UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
LOGIN_URL = "https://creator.douyin.com"
COOKIES_DIR = os.path.expanduser("~/.douyin-publisher/cookies")


class DouyinPublisher(BasePublisher):

    async def login_check(self, account: dict) -> bool:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright not installed; run: pip install playwright && playwright install chromium")
            return False

        cookie_file = account.get("cookie_file")
        if not cookie_file or not os.path.exists(cookie_file):
            return False

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            await _load_cookies(ctx, cookie_file)
            page = await ctx.new_page()
            await page.goto("https://creator.douyin.com/creator-micro/home", timeout=20000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            logged_in = "login" not in page.url and "passport" not in page.url
            await browser.close()
            return logged_in

    async def login_interactive(self, account: dict, cookie_file: str) -> bool:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("playwright not installed")
            return False

        os.makedirs(os.path.dirname(cookie_file), exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            try:
                ctx = await browser.new_context()
                page = await ctx.new_page()
                await page.goto(LOGIN_URL, timeout=30000)
                logger.info("Browser opened — waiting for user to log in (max 5 min)...")
                try:
                    await page.wait_for_url(
                        lambda url: "passport" not in url and "login" not in url,
                        timeout=300000,
                    )
                except Exception:
                    logger.warning("Login timed out or was cancelled")
                    return False
                cookies = await ctx.cookies()
                with open(cookie_file, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                logger.info(f"Cookies saved to {cookie_file}")
                return True
            except Exception as e:
                logger.error(f"Login browser error: {e}")
                return False

    async def publish(self, task: dict, video_path: str) -> str:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError("playwright not installed; run: pip install playwright && playwright install chromium")

        account_cookie = task.get("_cookie_file")
        if not account_cookie or not os.path.exists(account_cookie):
            raise RuntimeError(f"Cookie file missing: {account_cookie}")

        if not os.path.exists(video_path):
            raise RuntimeError(f"Video file missing: {video_path}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            await _load_cookies(ctx, account_cookie)
            page = await ctx.new_page()

            try:
                # 1. Navigate to upload page
                await page.goto(UPLOAD_URL, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=20000)

                if "login" in page.url or "passport" in page.url:
                    raise RuntimeError("Not logged in — cookie may have expired")

                # 2. Upload video file
                file_input = page.locator('input[type="file"]').first
                await file_input.set_input_files(video_path)
                logger.info(f"Video file set: {video_path}")

                # 3. Wait for upload/processing to complete (progress bar disappears)
                await page.wait_for_selector(
                    '.progress-bar, [class*="upload-progress"]',
                    state="hidden",
                    timeout=300000,
                )
                logger.info("Video upload/processing complete")

                # 4. Fill title
                title = task.get("title", "")
                if title:
                    title_sel = 'textarea[placeholder*="标题"], input[placeholder*="标题"], .title-input textarea'
                    title_el = page.locator(title_sel).first
                    await title_el.clear()
                    await title_el.fill(title[:30])

                # 5. Fill description
                desc = task.get("description", "")
                if desc:
                    desc_sel = '.DraftEditor-root, [contenteditable="true"], textarea[placeholder*="描述"]'
                    desc_el = page.locator(desc_sel).first
                    await desc_el.click()
                    await desc_el.fill(desc)

                # 6. Add hashtag topics from tags field
                tags_str = task.get("tags", "")
                if tags_str:
                    tags = [t.strip().lstrip("#") for t in tags_str.split(",") if t.strip()]
                    for tag in tags[:10]:
                        # Type # + tag to trigger topic suggestion popup
                        await page.keyboard.type(f" #{tag}")
                        await asyncio.sleep(0.8)
                        # Confirm first suggestion if popup appears
                        suggestion = page.locator('[class*="topic-item"], [class*="mention-item"]').first
                        if await suggestion.is_visible():
                            await suggestion.click()

                # 7. Attach product (小黄车) if product_id specified
                product_id_str = task.get("_product_douyin_id")
                if product_id_str:
                    await _attach_product(page, product_id_str)

                # 8. Publish
                publish_btn = page.locator('button:has-text("发布"), button:has-text("提交发布")').first
                await publish_btn.click()

                # 9. Wait for success
                await page.wait_for_selector(
                    '[class*="success"], :text("发布成功")',
                    timeout=60000,
                )
                logger.info(f"Published successfully for task {task.get('id')}")

                # Try to get published URL
                published_url = page.url
                return published_url

            finally:
                await browser.close()


async def _load_cookies(ctx, cookie_file: str):
    with open(cookie_file, encoding="utf-8") as f:
        cookies = json.load(f)
    await ctx.add_cookies(cookies)


async def _attach_product(page, product_id: str):
    """Search and attach a 小黄车 product by its Douyin product ID."""
    try:
        # Click 添加小黄车 button
        cart_btn = page.locator('button:has-text("小黄车"), [class*="product-btn"]').first
        if await cart_btn.is_visible(timeout=5000):
            await cart_btn.click()
            await asyncio.sleep(1)

            # Search by product ID
            search_input = page.locator('input[placeholder*="商品"], input[placeholder*="搜索"]').first
            await search_input.fill(product_id)
            await asyncio.sleep(1)

            # Select first result
            result = page.locator('[class*="product-item"], [class*="goods-item"]').first
            if await result.is_visible(timeout=5000):
                await result.click()
                # Confirm
                confirm_btn = page.locator('button:has-text("确定"), button:has-text("添加")').first
                if await confirm_btn.is_visible(timeout=3000):
                    await confirm_btn.click()
                logger.info(f"Product {product_id} attached")
    except Exception as e:
        logger.warning(f"Failed to attach product {product_id}: {e}")
