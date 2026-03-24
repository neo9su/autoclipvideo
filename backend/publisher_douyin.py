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

        AUTH_COOKIE_NAMES = {"sessionid", "uid_tt", "user_unique_id", "sid_guard"}

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            try:
                ctx = await browser.new_context()
                page = await ctx.new_page()
                await page.goto(LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
                logger.info("Browser opened — waiting for user to log in (max 5 min)...")

                deadline = asyncio.get_event_loop().time() + 300
                cookies = []
                while asyncio.get_event_loop().time() < deadline:
                    cookies = await ctx.cookies()
                    if {c["name"] for c in cookies} & AUTH_COOKIE_NAMES:
                        logger.info("Auth cookies detected, login successful")
                        break
                    await asyncio.sleep(2)
                else:
                    logger.warning("Login timed out — no auth cookies received")
                    return False

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

        progress = task.get("_progress_fn") or (lambda msg: asyncio.sleep(0))
        task_id = task.get("id", "unknown")

        async with async_playwright() as p:
            # Semi-automatic mode: visible browser so user can review and click 发布 manually
            browser = await p.chromium.launch(headless=False)
            # Pre-grant geolocation permission to suppress the browser permission dialog
            ctx = await browser.new_context(permissions=["geolocation"])
            await _load_cookies(ctx, account_cookie)
            page = await ctx.new_page()
            await page.bring_to_front()

            try:
                # 1. Navigate to upload page
                await progress("正在打开发布页面...")
                await page.goto(UPLOAD_URL, timeout=60000, wait_until="domcontentloaded")
                await _show_banner(page, "正在检查登录状态…", "system")

                if "login" in page.url or "passport" in page.url:
                    raise RuntimeError("Not logged in — cookie may have expired")
                qr_visible = await page.locator('[class*="qrcode"], [class*="login-qr"], :text("扫码登录")').first.is_visible()
                if qr_visible:
                    raise RuntimeError("Not logged in — login QR code detected, please re-login")

                # 1b. Dismiss draft continuation banner
                await _show_banner(page, "正在处理草稿弹窗…", "system")
                try:
                    abandon_btn = page.locator('button:has-text("放弃"), button:has-text("不继续"), button:has-text("取消草稿")').first
                    await abandon_btn.wait_for(state="visible", timeout=5000)
                    await abandon_btn.click()
                    await asyncio.sleep(1)
                    logger.info("Dismissed draft continuation dialog")
                except Exception:
                    pass

                # 1c. Dismiss onboarding tooltips
                await _dismiss_tooltips(page)

                # 2. Upload video file
                await progress("正在上传视频文件...")
                file_size_mb = os.path.getsize(video_path) / 1024 / 1024
                await _show_banner(page, f"正在上传视频文件（{file_size_mb:.0f} MB），请勿操作浏览器…", "system")
                file_input = page.locator('input[type="file"]').first
                await file_input.wait_for(state="attached", timeout=60000)
                await file_input.set_input_files(video_path)
                logger.info(f"Video file set: {video_path} ({file_size_mb:.1f} MB)")

                # 3. Wait for upload/processing to complete
                # Strategy: wait for the title input to become visible — it only appears
                # after Douyin finishes uploading + transcoding the video.
                # Concurrently show elapsed-time updates in the banner every 10s.
                await progress("视频上传中，等待平台处理...")
                _TITLE_SEL = 'textarea[placeholder*="标题"], input[placeholder*="标题"]'
                upload_max = max(300, int(file_size_mb * 3))  # ~3s per MB, min 5 min
                logger.info(f"Waiting up to {upload_max}s for upload+processing ({file_size_mb:.0f} MB)")

                async def _upload_ticker(page, max_sec):
                    """Update banner every 10s with elapsed time until cancelled."""
                    start = asyncio.get_event_loop().time()
                    while True:
                        elapsed = int(asyncio.get_event_loop().time() - start)
                        await _show_banner(
                            page,
                            f"视频上传 & 平台转码中，请耐心等待，勿操作浏览器… 已等待 {elapsed}s / 预计最长 {max_sec}s",
                            "system",
                        )
                        await asyncio.sleep(10)

                ticker = asyncio.create_task(_upload_ticker(page, upload_max))
                try:
                    # Primary: title field visible = form ready
                    await page.wait_for_selector(_TITLE_SEL, state="visible", timeout=upload_max * 1000)
                    logger.info("Title field visible — upload & processing complete")
                except Exception:
                    logger.warning("Title field not detected within timeout; proceeding anyway")
                finally:
                    ticker.cancel()

                await progress("视频处理完成")

                await _dismiss_tooltips(page)

                # 4. Fill title
                title = task.get("title", "")
                if title:
                    await progress("正在填写标题...")
                    await _show_banner(page, "正在自动填写标题，请勿操作…", "system")
                    title_sel = 'textarea[placeholder*="标题"], input[placeholder*="标题"], .title-input textarea'
                    title_el = page.locator(title_sel).first
                    try:
                        await title_el.wait_for(state="visible", timeout=10000)
                        await title_el.clear()
                        await title_el.fill(title[:30])
                        logger.info(f"Title filled: {title[:30]}")
                    except Exception as e:
                        logger.warning(f"Title fill failed: {e}")

                # 5. Fill description + hashtags (max 5 tags)
                desc = task.get("description", "")
                tags_str = task.get("tags", "")
                tags = [t.strip().lstrip("#") for t in tags_str.split(",") if t.strip()][:5]

                if desc or tags:
                    await progress("正在填写描述...")
                    await _show_banner(page, "正在自动填写描述和话题标签，请勿操作…", "system")
                    desc_sel = (
                        '[data-placeholder="添加作品简介"], '
                        '[contenteditable="true"][class*="editor-comp-publish"], '
                        '[contenteditable="true"][class*="caption"], '
                        'div[contenteditable="true"]'
                    )
                    desc_el = page.locator(desc_sel).first
                    try:
                        await desc_el.wait_for(state="visible", timeout=10000)
                        await desc_el.scroll_into_view_if_needed()
                        await desc_el.click(force=True)
                        await asyncio.sleep(0.3)
                        if desc:
                            await desc_el.type(desc, delay=10)
                        if tags:
                            await progress("正在添加话题标签...")
                            for tag in tags:
                                await page.keyboard.type(f" #{tag}")
                                await asyncio.sleep(0.8)
                                suggestion = page.locator('[class*="topic-item"], [class*="mention-item"]').first
                                if await suggestion.is_visible():
                                    await suggestion.click()
                                    await asyncio.sleep(0.3)
                        logger.info(f"Description + {len(tags)} tags filled")
                    except Exception as e:
                        logger.warning(f"Description/tags fill failed: {e}")

                # 6. Attach products via 购物车 → 粘贴商品链接 (max 5)
                product_ids = (task.get("_product_douyin_ids") or [])[:5]
                if product_ids:
                    await progress(f"正在添加购物车商品链接（共 {len(product_ids)} 件）...")
                    await _show_banner(page, f"正在自动选择购物车并添加商品链接（共 {len(product_ids)} 件），请勿操作…", "system")
                    await _ensure_shopping_cart_tag(page)
                    for pid in product_ids:
                        await _attach_product(page, pid)

                await _dismiss_tooltips(page)

                # 7. Set cover: 选择封面 → 设置横封面 → 完成
                await progress("正在自动设置封面...")
                await _show_banner(page, "正在自动设置横封面，请勿操作…", "system")
                await _set_cover(page)

                # 8. Scroll to bottom so 发布 button is visible
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)

                # 9. Wait for quick-check results, then auto-publish if all clear
                await progress("正在等待快速检测结果…")
                await _show_banner(page, "正在等待快速检测（检测中请耐心等待）…", "system")
                auto_ok = await _wait_for_quick_check(page, max_wait=300)

                if auto_ok:
                    await progress("✅ 检测通过，正在自动点击发布…")
                    await _show_banner(page, "检测通过 ✅  正在自动发布，请勿操作…", "system")
                    await _click_publish_button(page)
                    logger.info(f"[task {task_id}] Auto-publish button clicked")
                else:
                    # Fall back to user handoff
                    await progress("⚠️ 检测未通过或超时，请手动确认后点击【发布】")
                    await _show_banner(
                        page,
                        "⚠️ 检测未通过或仍在检测中，请手动检查后点击【发布】按钮",
                        "warning",
                    )
                    logger.info(f"[task {task_id}] Auto-publish skipped, waiting for user (up to 15 min)…")

                # Race: success redirect vs page close
                success_task = asyncio.create_task(
                    page.wait_for_url("**/content/manage**", timeout=900000)
                )
                close_task = asyncio.create_task(page.wait_for_event("close", timeout=900000))

                done, pending = await asyncio.wait(
                    [success_task, close_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

                if close_task in done:
                    raise RuntimeError("浏览器页面已被关闭，发布未完成")

                if "content/manage" not in page.url:
                    raise RuntimeError(
                        f"等待超时（15分钟），发布未完成。当前URL={page.url}"
                    )
                logger.info(f"Publish confirmed via URL redirect: {page.url}")

                await progress("✓ 发布成功")
                logger.info(f"Publish finished for task {task_id}, url={page.url}")
                return page.url

            finally:
                await browser.close()


async def _show_banner(page, message: str, mode: str = "system"):
    """
    Inject / update a floating status banner on the page.
    mode='system'  → grey/blue  "系统操作中，请勿操作"
    mode='user'    → green      "请您操作"
    mode='warning' → orange     警告
    """
    colors = {
        "system":  {"bg": "#1a1a2e", "border": "#4a90d9", "text": "#d0e8ff", "dot": "#4a90d9"},
        "user":    {"bg": "#0d2b1a", "border": "#2ecc71", "text": "#b8ffda", "dot": "#2ecc71"},
        "warning": {"bg": "#2b1a00", "border": "#f39c12", "text": "#ffe0a0", "dot": "#f39c12"},
    }
    c = colors.get(mode, colors["system"])
    label = {"system": "🤖 系统操作中，请勿操作", "user": "👆 请您操作", "warning": "⚠️ 注意"}.get(mode, "")
    js = f"""
    (() => {{
        let el = document.getElementById('__rf_banner__');
        if (!el) {{
            el = document.createElement('div');
            el.id = '__rf_banner__';
            el.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; z-index: 999999;
                padding: 10px 20px; display: flex; align-items: center; gap: 12px;
                font-family: -apple-system, sans-serif; font-size: 14px;
                box-shadow: 0 2px 12px rgba(0,0,0,0.4);
                transition: background 0.3s, border-color 0.3s;
            `;
            document.body.prepend(el);
        }}
        el.style.background = '{c["bg"]}';
        el.style.borderBottom = '2px solid {c["border"]}';
        el.style.color = '{c["text"]}';
        el.innerHTML = `
            <span style="display:inline-block;width:10px;height:10px;border-radius:50%;
                background:{c["dot"]};flex-shrink:0;
                box-shadow:0 0 6px {c["dot"]}"></span>
            <strong style="flex-shrink:0">{label}</strong>
            <span style="opacity:0.9">{message}</span>
        `;
    }})();
    """
    try:
        await page.evaluate(js)
    except Exception:
        pass  # page may be navigating


async def _dismiss_tooltips(page):
    """Dismiss any onboarding/feature-intro tooltips that block interaction."""
    for _ in range(5):
        try:
            btn = page.locator(
                'button:has-text("我知道了"), button:has-text("知道了"), '
                'button:has-text("好的"), button:has-text("关闭")'
            ).first
            await btn.wait_for(state="visible", timeout=1500)
            await btn.click()
            await asyncio.sleep(0.4)
            logger.info("Dismissed tooltip/onboarding overlay")
        except Exception:
            break


async def _load_cookies(ctx, cookie_file: str):
    with open(cookie_file, encoding="utf-8") as f:
        cookies = json.load(f)
    await ctx.add_cookies(cookies)


async def _ensure_shopping_cart_tag(page):
    """
    In 扩展信息 → 添加标签, ensure "购物车" is selected.
    Scrolls to the section once, then selects without further page movement.
    """
    try:
        label = page.get_by_text("添加标签", exact=False).first
        await label.scroll_into_view_if_needed()
        await asyncio.sleep(0.5)

        dropdown = page.locator(
            '[class*="select"]:near(:text("添加标签")), '
            '[class*="dropdown"]:near(:text("添加标签"))'
        ).first
        current_text = (await dropdown.text_content() or "").strip()
        if "购物车" in current_text:
            logger.info("购物车 already selected")
            return

        await dropdown.click()
        await asyncio.sleep(0.5)

        # Exact match to avoid selecting 小程序/话题 etc.
        option = page.get_by_role("option", name="购物车")
        if await option.count() == 0:
            option = page.locator(
                'li:text-is("购物车"), '
                '[class*="option"]:text-is("购物车"), '
                '[class*="item"]:text-is("购物车")'
            ).first
        await option.wait_for(state="visible", timeout=5000)
        await option.click()
        await asyncio.sleep(0.5)

        # Verify selection succeeded
        current_text = (await dropdown.text_content() or "").strip()
        logger.info(f"购物车 dropdown selected, current value: {current_text}")
    except Exception as e:
        logger.warning(f"Could not select 购物车 dropdown: {e}")


async def _wait_for_quick_check(page, max_wait: int = 300) -> bool:
    """
    Poll 快速检测 panel until a definitive result is reached.

    States:
      - "正在检测中" visible            → still running, keep waiting
      - "作品未见异常" + "封面检测通过" → PASS, return True
      - known error text visible         → FAIL, return False
      - none of the above               → indeterminate, return False (user intervention)

    max_wait: maximum seconds to wait while "正在检测中" is still showing (default 5 min).
    """
    PASS_CONTENT  = "作品未见异常"
    PASS_COVER    = "封面检测通过"
    IN_PROGRESS   = "正在检测中"
    ERROR_TEXTS   = ["作品存在违规", "封面存在问题", "检测不通过", "内容违规"]

    elapsed = 0
    while elapsed < max_wait:
        try:
            content_ok  = await page.locator(f':text("{PASS_CONTENT}")').first.is_visible()
            cover_ok    = await page.locator(f':text("{PASS_COVER}")').first.is_visible()
            in_progress = await page.locator(f':text("{IN_PROGRESS}")').first.is_visible()

            if content_ok and cover_ok:
                logger.info("Quick check passed: 作品未见异常 + 封面检测通过")
                return True

            for err in ERROR_TEXTS:
                if await page.locator(f':text("{err}")').first.is_visible():
                    logger.warning(f"Quick check failed: {err}")
                    return False

            if in_progress:
                logger.debug(f"Quick check still running ({elapsed}s elapsed), waiting…")
                await asyncio.sleep(3)
                elapsed += 3
                continue

            # No progress indicator and no pass/fail → indeterminate
            logger.warning("Quick check: no recognisable state — deferring to user")
            return False

        except Exception as e:
            logger.debug(f"Quick check poll error: {e}")
            await asyncio.sleep(3)
            elapsed += 3

    logger.warning(f"Quick check still running after {max_wait}s — deferring to user")
    return False


async def _click_publish_button(page):
    """Click the main 发布 submit button (not the nav tab)."""
    # The submit button is the last red 发布 button in the form area
    btn = page.locator('button:has-text("发布")').last
    await btn.wait_for(state="visible", timeout=10000)
    await btn.scroll_into_view_if_needed()
    await asyncio.sleep(0.3)
    await btn.click()
    await asyncio.sleep(1)

    # Douyin sometimes shows "建议设封面后再发布" — dismiss and click again
    try:
        cover_warn = page.locator(':text("建议设封面后再发布")').first
        if await cover_warn.is_visible(timeout=3000):
            logger.info("Cover warning banner detected, clicking 发布 again")
            await btn.click()
            await asyncio.sleep(1)
    except Exception:
        pass


async def _set_cover(page):
    """
    Auto-set cover: click 选择封面 → switch to 设置横封面 tab → click 完成.

    Modal layout:
      Top tabs:   [设置竖封面]  [设置横封面]
      Bottom bar: [封面检测] ... [设置竖封面 / 完成 (red)]
    """
    try:
        # 1. Click the first visible "选择封面" button (竖封面 or 横封面 — either opens the modal)
        cover_btn = page.locator(':text-is("选择封面")').first
        await cover_btn.scroll_into_view_if_needed()
        await cover_btn.wait_for(state="visible", timeout=8000)
        await cover_btn.click()
        await asyncio.sleep(1.2)

        # 2. Wait for cover modal (confirm it opened)
        modal_indicator = page.locator(':text("设置竖封面"), :text("设置横封面")').first
        await modal_indicator.wait_for(state="visible", timeout=8000)

        # 3. Click "设置横封面" tab at the top of the modal
        hori_tab = page.locator(':text-is("设置横封面")').first
        await hori_tab.wait_for(state="visible", timeout=5000)
        await hori_tab.click()
        await asyncio.sleep(1)

        # 4. Click "完成" — the red button bottom-right of the modal
        # Use last() since multiple "完成" texts may exist; the modal's is last/visible
        done_btn = page.locator('button:has-text("完成")').last
        await done_btn.wait_for(state="visible", timeout=5000)
        await done_btn.click()
        await asyncio.sleep(1)
        logger.info("Cover set (横封面 4:3)")

    except Exception as e:
        logger.warning(f"Cover set failed (non-fatal, user can set manually): {e}")
        # Try to close the modal if it's still open
        try:
            close = page.locator('[aria-label="Close"], [aria-label="关闭"], button:has-text("×")').first
            if await close.is_visible(timeout=1500):
                await close.click()
        except Exception:
            pass


async def _attach_product(page, product_link: str, short_title: str = ""):
    """
    Add one product via inline input → 添加链接 button → handle 编辑商品 dialog.

    UI layout (inline, no popup needed):
      [购物车 ▼] [粘贴商品链接 input .................] [添加链接]

    Flow:
      1. Fill the inline "粘贴商品链接" input with the link
      2. Click "添加链接" button
      3. Check if "添加链接" is disabled (invalid link) → clear and return
      4. Wait for "编辑商品" dialog → fill 商品短标题 → click "完成编辑"
    """
    try:
        # 1. Find inline input and fill it
        link_input = page.locator(
            'input[placeholder*="粘贴商品链接"], '
            'input[placeholder*="商品链接"]'
        ).first
        await link_input.wait_for(state="visible", timeout=8000)
        await link_input.click()
        await asyncio.sleep(0.2)
        await link_input.fill(product_link)
        await asyncio.sleep(0.8)  # allow link validation to run

        # 2. Check if 添加链接 button is enabled before clicking
        add_btn = page.locator(':text-is("添加链接")').first
        await add_btn.wait_for(state="visible", timeout=5000)
        is_disabled = await add_btn.get_attribute("disabled")
        aria_disabled = await add_btn.get_attribute("aria-disabled")
        btn_class = await add_btn.get_attribute("class") or ""
        if is_disabled is not None or aria_disabled == "true" or "disabled" in btn_class:
            logger.warning(f"Product link invalid — 添加链接 disabled: {product_link}")
            await link_input.clear()
            return

        await add_btn.click()
        await asyncio.sleep(1.5)

        # 3. Check for "未搜索到对应商品" error dialog (invalid/unsupported link)
        error_dialog = page.locator(':text("未搜索到对应商品")').first
        if await error_dialog.is_visible(timeout=3000):
            logger.warning(f"Product not found / unsupported link: {product_link}")
            ok_btn = page.locator('button:has-text("确定")').first
            if await ok_btn.is_visible(timeout=2000):
                await ok_btn.click()
                await asyncio.sleep(0.5)
            # Clear input and skip this product
            try:
                await link_input.click()
                await link_input.clear()
            except Exception:
                pass
            return

        # 4. Handle "编辑商品" dialog that may appear after clicking 添加链接
        edit_dialog = page.locator(':text("编辑商品")').first
        if await edit_dialog.is_visible(timeout=5000):
            logger.info("编辑商品 dialog appeared")

            # Fill 商品短标题 if empty (required field, max 10 chars)
            short_input = page.locator(
                'input[placeholder*="短标题"], input[placeholder*="商品短标题"]'
            ).first
            if await short_input.is_visible(timeout=2000):
                await short_input.click()
                current_val = await short_input.input_value()
                if not current_val.strip():
                    title_10 = (short_title or "精选假发")[:10]
                    await short_input.fill(title_10)
                    await asyncio.sleep(0.3)

            # Click 完成编辑
            done_btn = page.locator('button:has-text("完成编辑")').first
            await done_btn.wait_for(state="visible", timeout=5000)
            await done_btn.click()
            await asyncio.sleep(1)
            logger.info(f"编辑商品 dialog confirmed for {product_link}")
        else:
            logger.info(f"Product added (no 编辑商品 dialog): {product_link}")

    except Exception as e:
        logger.warning(f"Failed to add product link {product_link}: {e}")
        # Try to close any open dialog before continuing
        try:
            for btn_text in ["取消", "关闭"]:
                btn = page.locator(f'button:has-text("{btn_text}")').first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    break
        except Exception:
            pass
