"""
Douyin (TikTok CN) publisher via Playwright browser automation.
Upload page: https://creator.douyin.com/creator-micro/content/upload
"""
import asyncio
import json
import logging
import os
import re
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

        AUTH_COOKIE_NAMES = {"sessionid", "uid_tt", "sid_guard"}

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--window-size=1200,800", "--window-position=100,100"]
            )
            try:
                ctx = await browser.new_context(viewport={"width": 1200, "height": 800})
                page = await ctx.new_page()
                await page.bring_to_front()
                await page.goto(LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
                logger.info("Browser opened — waiting for user to log in (max 5 min)...")

                loop = asyncio.get_running_loop()
                deadline = loop.time() + 300
                cookies = []
                while loop.time() < deadline:
                    cookies = await ctx.cookies()
                    cookie_names = {c["name"] for c in cookies}
                    if AUTH_COOKIE_NAMES.issubset(cookie_names):
                        logger.info("Auth cookies detected, login successful")
                        break
                    await asyncio.sleep(2)
                else:
                    logger.warning("Login timed out — no auth cookies received")
                    return False

                with open(cookie_file, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                logger.info(f"Cookies saved to {cookie_file}")

                # Notify user and wait for them to close the browser (max 2 min)
                try:
                    await page.evaluate(
                        "() => { document.title = '✅ 登录成功 — 可以关闭此窗口'; }"
                    )
                    await page.evaluate(
                        "() => { document.body.insertAdjacentHTML('afterbegin',"
                        "\"<div style='position:fixed;top:0;left:0;right:0;background:#52c41a;"
                        "color:#fff;text-align:center;padding:12px;font-size:18px;z-index:99999'>"
                        "✅ 登录成功，Cookie 已保存，可以关闭此窗口</div>\"); }"
                    )
                except Exception:
                    pass
                logger.info("Login successful — waiting for user to close the browser (max 2 min)...")
                try:
                    await page.wait_for_event("close", timeout=120000)
                except Exception:
                    pass  # timeout or already closed — both are fine

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
            # Semi-automatic mode: visible browser with optimized startup
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage", 
                    "--disable-gpu",
                    "--disable-extensions",
                    "--disable-background-timer-throttling",
                    "--disable-background-networking",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-breakpad",
                    "--disable-component-extensions-with-background-pages",
                    "--disable-features=TranslateUI,VizDisplayCompositor",
                    "--max-old-space-size=1024",
                    "--memory-pressure-off",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor,UseChromeOSDirectVideoDecoder",
                    "--fast-start",
                    "--disable-background-mode"
                ]
            )
            # Pre-grant geolocation permission to suppress the browser permission dialog
            ctx = await browser.new_context(
                permissions=["geolocation"],
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            await _load_cookies(ctx, account_cookie)
            page = await ctx.new_page()
            await page.bring_to_front()

            try:
                # 1. Navigate to upload page
                await progress("正在打开发布页面...")
                await page.goto(UPLOAD_URL, timeout=30000, wait_until="domcontentloaded")
                # wait for React/SPA to hydrate — upload page is a JS-rendered SPA
                try:
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass  # networkidle timeout is non-fatal
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
                # Try to find file input; on new Douyin UI it may need a click trigger first
                file_input = page.locator('input[type="file"]').first
                try:
                    await file_input.wait_for(state="attached", timeout=30000)
                except Exception:
                    # Fallback: click the upload area to trigger dynamic input creation
                    logger.info("input[type=file] not found directly, trying click trigger...")
                    upload_area = page.locator(
                        '[class*="upload-area"], [class*="upload-btn"], [class*="drag"], '
                        '[class*="Upload"], .upload-inner, [data-e2e*="upload"]'
                    ).first
                    try:
                        await upload_area.wait_for(state="visible", timeout=10000)
                        await upload_area.click()
                        await asyncio.sleep(1)
                    except Exception:
                        logger.warning("upload area not found either, proceeding anyway")
                    await file_input.wait_for(state="attached", timeout=60000)
                await file_input.set_input_files(video_path)
                logger.info(f"Video file set: {video_path} ({file_size_mb:.1f} MB)")

                # 3. Wait for upload/processing to complete
                # Strategy: wait for the title input to become visible — it only appears
                # after Douyin finishes uploading + transcoding the video.
                # Concurrently show elapsed-time updates in the banner every 10s.
                await progress("视频上传中，等待平台处理...")
                _TITLE_SEL = 'textarea[placeholder*="标题"], input[placeholder*="标题"]'
                upload_max = max(600, int(file_size_mb * 5))  # ~5s per MB, min 10 min
                logger.info(f"Waiting up to {upload_max}s for upload+processing ({file_size_mb:.0f} MB)")

                async def _upload_ticker(page, max_sec):
                    """Update banner every 10s with elapsed time until cancelled."""
                    loop = asyncio.get_running_loop()
                    start = loop.time()
                    while True:
                        elapsed = int(loop.time() - start)
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
                title = task.get("title") or ""
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
                desc = task.get("description") or ""
                tags_str = task.get("tags") or ""
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
                            await desc_el.focus()
                            await desc_el.type(desc, delay=10)
                        if tags:
                            await progress("正在添加话题标签...")
                            for tag in tags:
                                await desc_el.focus()
                                await desc_el.type(f" #{tag}", delay=30)
                                await asyncio.sleep(0.8)
                                suggestion = page.locator('[class*="topic-item"], [class*="mention-item"]').first
                                if await suggestion.is_visible():
                                    await suggestion.click()
                                    await asyncio.sleep(0.3)
                                # Close any remaining suggestion dropdown after each tag
                                await page.keyboard.press("Escape")
                                await asyncio.sleep(0.2)
                        logger.info(f"Description + {len(tags)} tags filled")
                        # After all tags: click a neutral spot to fully dismiss
                        # the suggestion dropdown before scrolling further
                        await _dismiss_overlays(page)
                    except Exception as e:
                        logger.warning(f"Description/tags fill failed: {e}")

                # 6. Attach products via 购物车 → 粘贴商品链接 (max 5)
                #    Skipped for "无车发布" tasks (no_cart=True)
                product_ids = (task.get("_product_douyin_ids") or [])[:5]
                product_names = (task.get("_product_names") or [])
                if product_ids and not task.get("no_cart"):
                    await progress(f"正在添加购物车商品链接（共 {len(product_ids)} 件）...")
                    await _show_banner(page, f"正在自动选择购物车并添加商品链接（共 {len(product_ids)} 件），请勿操作…", "system")
                    # Ensure all floating dropdowns/tooltips (hashtag suggestions,
                    # 共创 tooltip, etc.) are gone before interacting with 添加标签
                    await _dismiss_overlays(page)
                    await _ensure_shopping_cart_tag(page)
                    for i, pid in enumerate(product_ids):
                        name = product_names[i] if i < len(product_names) else ""
                        await _attach_product(page, pid, short_title=name)

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
                auto_ok = await _wait_for_quick_check(page, max_wait=900)

                if auto_ok:
                    await progress("✅ 检测通过，正在自动点击发布…")
                    await _show_banner(page, "检测通过 ✅  正在自动发布，请勿操作…", "system")
                    await _click_publish_button(page)
                    logger.info(f"[task {task_id}] Auto-publish button clicked")
                else:
                    # Check if publish button is already visible (quick-check may be indeterminate)
                    publish_btn = page.locator('button:has-text("发布")').last
                    btn_visible = False
                    try:
                        btn_visible = await publish_btn.is_visible(timeout=3000)
                    except Exception:
                        pass

                    if btn_visible:
                        await progress("检测状态不明确，发布按钮可见，直接自动发布...")
                        await _show_banner(page, "检测状态不明确，发布按钮已可见 — 正在自动发布，请勿操作…", "system")
                        await _click_publish_button(page)
                        logger.info(f"[task {task_id}] Auto-publish button clicked (quick-check indeterminate but btn visible)")
                    else:
                        # Fall back to user handoff
                        await progress("⚠️ 检测未通过或超时，请手动确认后点击【发布】")
                        await _show_banner(
                            page,
                            "⚠️ 检测未通过或仍在检测中，请手动检查后点击【发布】按钮",
                            "warning",
                        )
                        logger.info(f"[task {task_id}] Auto-publish skipped, waiting for user (up to 15 min)…")

                # Handle possible scan-to-verify popup after clicking publish
                await _handle_scan_verify(page, progress)

                # Wait for success redirect (up to 15 min)
                try:
                    await page.wait_for_url("**/content/manage**", timeout=900000)
                except Exception as e:
                    # Check if page was closed or navigated away unexpectedly
                    try:
                        current_url = page.url
                    except Exception:
                        current_url = "(page closed)"
                    if "content/manage" in current_url:
                        pass  # Already there
                    else:
                        raise RuntimeError(
                            f"等待发布跳转超时（15分钟），发布未完成。当前URL={current_url}"
                        ) from e

                if "content/manage" not in page.url:
                    raise RuntimeError(
                        f"等待超时（15分钟），发布未完成。当前URL={page.url}"
                    )
                logger.info(f"Publish confirmed via URL redirect: {page.url}")

                await progress("✓ 发布成功")
                logger.info(f"Publish finished for task {task_id}, url={page.url}")
                return page.url

            finally:
                # Save refreshed cookies back to file before closing
                try:
                    refreshed = await ctx.cookies()
                    if refreshed and account_cookie:
                        with open(account_cookie, "w", encoding="utf-8") as _f:
                            json.dump(refreshed, _f, ensure_ascii=False, indent=2)
                        logger.info(f"Cookies refreshed and saved to {account_cookie} ({len(refreshed)} cookies)")
                except Exception as e:
                    logger.warning(f"Cookie refresh save error: {e}")
                try:
                    await browser.close()
                except Exception as e:
                    logger.warning(f"Browser close error: {e}")
                    # Force-kill only the browser process we spawned
                    try:
                        import psutil, os as _os
                        browser_pid = browser.process.pid if hasattr(browser, "process") and browser.process else None
                        if browser_pid:
                            try:
                                psutil.Process(browser_pid).kill()
                            except psutil.NoSuchProcess:
                                pass
                    except Exception:
                        pass


async def _lock_input(page):
    """Inject a full-screen transparent overlay that swallows all user mouse/keyboard events.
    Playwright dispatches events via CDP directly to elements, so automation is unaffected.
    Called before each automated step; removed by _unlock_input when user action is needed."""
    js = """
    (() => {
        if (document.getElementById('__rf_lock__')) return;
        const el = document.createElement('div');
        el.id = '__rf_lock__';
        el.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:999998;cursor:not-allowed;';
        const stop = e => { e.stopPropagation(); e.stopImmediatePropagation(); };
        ['click','mousedown','mouseup','mousemove','keydown','keyup','keypress',
         'pointerdown','pointerup','pointermove','wheel','touchstart','touchend']
            .forEach(t => el.addEventListener(t, stop, true));
        document.body.appendChild(el);
    })();
    """
    try:
        await page.evaluate(js)
    except Exception:
        pass


async def _unlock_input(page):
    """Remove the input-blocking overlay so the user can interact with the page."""
    try:
        await page.evaluate("const el=document.getElementById('__rf_lock__'); if(el) el.remove();")
    except Exception:
        pass


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


async def _dismiss_overlays(page):
    """
    Close all floating layers that block subsequent interactions:
      - Hashtag/mention suggestion dropdowns
      - The '添加共创' informational tooltip
      - Any open combobox listbox

    Strategy for 共创 tooltip:
      1. Click '?' icon near '添加共创' label (mirroring the manual close gesture)
      2. Remove any remaining floating element whose text contains known markers
    Repeats up to 3 times until nothing floatable remains.

    NOTE: position:fixed elements have offsetParent===null, so we use
    getBoundingClientRect() for proper visibility detection.
    """
    # Step A: click the '?' icon adjacent to '添加共创' to close the tooltip
    # (this mirrors the user's manual workaround: click '?' → click blank × 3)
    for _ in range(3):
        clicked_q = await page.evaluate("""() => {
            // Walk all text nodes looking for '添加共创'
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                if (node.textContent.trim() !== '添加共创') continue;
                // Search sibling/ancestor area for a '?' icon or help button
                let el = node.parentElement;
                for (let i = 0; i < 6; i++) {
                    if (!el) break;
                    // Look for question-mark SVG wrappers or icon buttons
                    const candidates = el.querySelectorAll(
                        '[class*="question"], [class*="help"], [class*="icon"], ' +
                        '[class*="tip"], svg, [role="button"], button'
                    );
                    for (const c of candidates) {
                        const t = c.textContent.trim();
                        // Only click small elements (not the label itself)
                        const rect = c.getBoundingClientRect();
                        if (rect.width < 40 && rect.height < 40 && rect.width > 0) {
                            c.click();
                            return true;
                        }
                    }
                    el = el.parentElement;
                }
            }
            return false;
        }""")
        if clicked_q:
            await asyncio.sleep(0.2)
            try:
                await page.mouse.click(10, 10)
            except Exception:
                pass
            await asyncio.sleep(0.2)

    # Step B: Escape key + DOM cleanup
    for attempt in range(3):
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.15)

        removed = await page.evaluate("""() => {
            let count = 0;

            // 1. Remove floating elements containing 共创 tooltip markers.
            //    Use getBoundingClientRect (works for position:fixed elements too).
            const coCreateMarkers = [
                '邀请多人共同完成作品', '共创投稿邀请', '共创者身份', '共创作品说明'
            ];
            document.querySelectorAll('div, section, aside, [role="tooltip"], [class*="tooltip"], [class*="popover"]').forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;   // truly invisible
                if (rect.height > window.innerHeight * 0.8) return;   // whole-page element
                if (coCreateMarkers.some(m => el.textContent.includes(m))) {
                    el.remove();
                    count++;
                }
            });

            // 2. Hide open listboxes / suggestion dropdowns
            document.querySelectorAll(
                '[role="listbox"], [role="tooltip"], [class*="popover"], [class*="dropdown-menu"]'
            ).forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    el.style.display = 'none';
                    count++;
                }
            });

            return count;
        }""")

        # 3. Click a page-level safe spot to blur any focused input
        try:
            await page.mouse.click(10, 10)
        except Exception:
            pass
        await asyncio.sleep(0.25)

        if removed == 0:
            break
        logger.info(f"_dismiss_overlays attempt {attempt+1}: removed/closed {removed} layer(s)")

    await asyncio.sleep(0.2)


async def _load_cookies(ctx, cookie_file: str):
    with open(cookie_file, encoding="utf-8") as f:
        cookies = json.load(f)
    await ctx.add_cookies(cookies)


async def _read_tag_dropdown_value(page) -> str:
    """Read the current text of the 添加标签 dropdown. Returns '' on failure."""
    return await page.evaluate("""() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node, labelEl = null;
        while ((node = walker.nextNode())) {
            if (node.textContent.trim() === '添加标签') {
                labelEl = node.parentElement;
                break;
            }
        }
        if (!labelEl) return '';
        let el = labelEl;
        for (let i = 0; i < 8; i++) {
            el = el.parentElement;
            if (!el) break;
            const sel = el.querySelector(
                '[role="combobox"], [class*="Select"], [class*="select-trigger"],' +
                '[class*="selector"], [class*="semi-select"]'
            );
            if (sel) return sel.textContent.trim();
        }
        return '';
    }""") or ''


async def _open_and_select_cart(page) -> bool:
    """
    Open the 添加标签 dropdown via JS and click the 购物车 option.
    Returns True if the click was issued, False if the dropdown couldn't be opened.
    """
    result = await page.evaluate("""() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node, labelEl = null;
        while ((node = walker.nextNode())) {
            if (node.textContent.trim() === '添加标签') {
                labelEl = node.parentElement;
                break;
            }
        }
        if (!labelEl) return 'label_not_found';
        let el = labelEl;
        for (let i = 0; i < 8; i++) {
            el = el.parentElement;
            if (!el) break;
            const trigger = el.querySelector(
                '[role="combobox"], [class*="Select"], [class*="select-trigger"],' +
                '[class*="selector"], [class*="semi-select"]'
            );
            if (trigger) { trigger.click(); return 'clicked'; }
        }
        return 'trigger_not_found';
    }""")
    logger.info(f"_open_and_select_cart dropdown open: {result}")
    if result != 'clicked':
        return False

    await asyncio.sleep(0.5)

    # Click the 购物车 option
    option = page.get_by_role("option", name="购物车", exact=True)
    if await option.count() == 0:
        option = page.locator('li, [role="option"]').filter(has_text=re.compile(r'^购物车$'))
    try:
        await option.first.wait_for(state="visible", timeout=4000)
        box = await option.first.bounding_box()
        logger.info(f"购物车 option bounding_box: {box}")
        await option.first.click()
    except Exception as e:
        logger.warning(f"Could not click 购物车 option: {e}")
        return False

    await asyncio.sleep(0.6)
    return True


async def _ensure_shopping_cart_tag(page):
    """
    Ensure '购物车' is selected in the 添加标签 dropdown before adding product links.

    Verification: the product-link input (placeholder '粘贴商品链接') only appears
    when 购物车 is active — its visibility is the single source of truth.

    If the dropdown shows a wrong value (e.g. '游戏手柄') after a failed attempt,
    we dismiss overlays and retry, up to MAX_ATTEMPTS times.
    """
    MAX_ATTEMPTS = 3
    link_input = page.locator('input[placeholder*="粘贴商品链接"]')

    for attempt in range(MAX_ATTEMPTS):
        # ── Check current state ──────────────────────────────────────────────
        if await link_input.is_visible():
            logger.info(f"购物车 confirmed (attempt {attempt+1}): link input visible")
            return

        current_val = await _read_tag_dropdown_value(page)
        logger.info(f"Attempt {attempt+1}/{MAX_ATTEMPTS}: dropdown='{current_val}'")

        # ── Clear all overlays before every attempt ──────────────────────────
        await _dismiss_overlays(page)

        # ── Scroll 添加标签 into the upper part of the viewport ─────────────
        # scroll_into_view_if_needed() may leave the element at the very bottom
        # where the 共创 tooltip can still overlap it.  Scrolling to block:"start"
        # places it near the top so the dropdown has clear space below it.
        try:
            scrolled = await page.evaluate("""() => {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while ((node = walker.nextNode())) {
                    if (node.textContent.trim() === '添加标签') {
                        node.parentElement.scrollIntoView({block: 'start', inline: 'nearest', behavior: 'smooth'});
                        return true;
                    }
                }
                return false;
            }""")
            if not scrolled:
                tag_label = page.get_by_text("添加标签", exact=True).first
                await tag_label.scroll_into_view_if_needed()
            await asyncio.sleep(0.6)
        except Exception:
            pass

        # ── Open dropdown and select 购物车 ──────────────────────────────────
        clicked = await _open_and_select_cart(page)
        if not clicked:
            logger.warning(f"Attempt {attempt+1}: could not open dropdown")
            await asyncio.sleep(0.5)
            continue

        # ── Verify: wait for link input to appear (up to 5s) ─────────────────
        try:
            await link_input.wait_for(state="visible", timeout=5000)
            new_val = await _read_tag_dropdown_value(page)
            logger.info(f"Attempt {attempt+1} succeeded: dropdown='{new_val}', input visible")
            return
        except Exception:
            new_val = await _read_tag_dropdown_value(page)
            logger.warning(
                f"Attempt {attempt+1} failed: dropdown='{new_val}', input not visible — retrying"
            )
            await asyncio.sleep(0.5)

    logger.error(f"_ensure_shopping_cart_tag: failed after {MAX_ATTEMPTS} attempts")


async def _wait_for_quick_check(page, max_wait: int = 900) -> bool:
    """
    Poll 快速检测 panel until a definitive result is reached.

    States:
      - "正在检测中" visible            → still running, keep waiting
      - "作品未见异常" + "封面检测通过" → PASS, return True
      - known error text visible         → FAIL, return False
      - none of the above               → indeterminate, return False (user intervention)

    max_wait: maximum seconds to wait while "正在检测中" is still showing (default 15 min).
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


async def _handle_scan_verify(page, progress=None) -> bool:
    """
    After clicking publish, Douyin may show a phone scan-to-verify QR dialog.
    If detected, show a banner asking user to scan and wait up to 5 minutes
    for the dialog to disappear before proceeding.

    Returns True if scan was detected and completed, False if not needed.
    """
    # Common selectors for the scan-to-verify modal
    SCAN_SELECTORS = [
        ':text("手机扫码验证")',
        ':text("扫码验证")',
        ':text("安全验证")',
        ':text("请扫码验证")',
        '[class*="verify"][class*="qr"]',
        '[class*="scan"][class*="modal"]',
    ]
    # Wait up to 4 seconds to see if scan dialog appears
    scan_visible = False
    for sel in SCAN_SELECTORS:
        try:
            loc = page.locator(sel).first
            if await loc.is_visible(timeout=1500):
                scan_visible = True
                logger.info(f"Scan-to-verify dialog detected: {sel}")
                break
        except Exception:
            continue

    if not scan_visible:
        return False

    # Notify user
    msg = "📱 抖音要求手机扫码验证，请打开抖音 APP 扫描二维码完成验证…"
    if progress:
        await progress(msg)
    await _show_banner(page, msg, "warning")
    logger.info("Waiting for scan-to-verify dialog to be dismissed (up to 5 min)…")

    # Wait for all scan selectors to disappear (up to 5 min)
    for _ in range(100):  # 100 × 3s = 5 min
        await asyncio.sleep(3)
        still_visible = False
        for sel in SCAN_SELECTORS:
            try:
                if await page.locator(sel).first.is_visible(timeout=500):
                    still_visible = True
                    break
            except Exception:
                continue
        if not still_visible:
            logger.info("Scan-to-verify dialog dismissed, continuing…")
            if progress:
                await progress("✅ 扫码验证完成，继续等待发布跳转…")
            await _show_banner(page, "✅ 扫码验证完成，等待发布跳转…", "system")
            return True

    logger.warning("Scan-to-verify dialog still visible after 5 min — proceeding anyway")
    return True


async def _click_btn_by_text(page, text: str, timeout: int = 3000) -> bool:
    """Click the first visible element whose exact text matches. Returns True if clicked."""
    try:
        el = page.locator(f':text-is("{text}")').first
        if await el.is_visible(timeout=timeout):
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            box = await el.bounding_box()
            if box:
                await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            else:
                await el.click()
            return True
    except Exception:
        pass
    return False


async def _dismiss_cover_promo_popup(page) -> bool:
    """
    检测并关闭「设置横封面获更多流量」推广弹窗。
    弹窗特征：包含唯一文字「暂不设置」。
    点击弹窗内的「设置横封面」按钮关闭。
    返回 True 表示弹窗已处理，False 表示弹窗未出现。
    """
    try:
        skip_btn = page.locator(':text-is("暂不设置")').first
        if not await skip_btn.is_visible(timeout=3500):
            return False
        # 弹窗确认按钮：与「暂不设置」同级的「设置横封面」
        # 先尝试同容器定位，再 fallback 到页面最后一个同名元素
        promo_confirm = page.locator(':text-is("暂不设置")').locator('xpath=..').locator(':text-is("设置横封面")')
        if await promo_confirm.count() == 0:
            promo_confirm = page.locator(':text-is("暂不设置")').locator('xpath=../..').locator(':text-is("设置横封面")')
        if await promo_confirm.count() == 0:
            promo_confirm = page.locator(':text-is("设置横封面")').last
        box = await promo_confirm.bounding_box()
        if box:
            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        else:
            await promo_confirm.click()
        logger.info("推广弹窗已关闭：点击「设置横封面」")
        await asyncio.sleep(1.2)
        return True
    except Exception as e:
        logger.debug(f"推广弹窗处理（非致命）: {e}")
        return False


async def _set_cover(page):
    """
    Auto-set cover.

    Douyin cover modal entry points (2026-03+):
      - 有挂车流程：页面上有「选择封面」按钮
      - 无挂车流程：页面底部有「设置横封面」按钮（无「选择封面」）
    两种入口点击后都会打开封面 modal，随后可能出现推广弹窗。

    完整流程：
      1. 点击入口按钮（「选择封面」或「设置横封面」）
      2. 等待封面 modal 出现
      3. 如弹窗已出现 → 关闭弹窗
      4. 选择推荐封面帧（best-effort）
      5. 点击 modal 底部「设置横封面」确认按钮（如存在）
         → 此按钮可能再次触发推广弹窗 → 再次关闭
      6. 点击「完成」
    """
    try:
        # 1. 找入口按钮：优先「选择封面」，无则用「设置横封面」
        entry_clicked = False
        for entry_text in ("选择封面", "设置横封面"):
            try:
                btn = page.locator(f':text-is("{entry_text}")').first
                await btn.wait_for(state="visible", timeout=4000)
                await btn.scroll_into_view_if_needed()
                await btn.click()
                logger.info(f"封面入口：点击「{entry_text}」")
                entry_clicked = True
                break
            except Exception:
                continue
        if not entry_clicked:
            logger.warning("_set_cover: 未找到封面入口按钮，跳过")
            return
        await asyncio.sleep(1.5)

        # 2. 等待封面 modal 出现（竖封面 / 横封面 tab 任一可见）
        modal_indicator = page.locator(':text("设置竖封面"), :text("设置横封面")').first
        await modal_indicator.wait_for(state="visible", timeout=8000)
        await asyncio.sleep(0.8)

        # 3. 处理 modal 打开时即出现的推广弹窗
        await _dismiss_cover_promo_popup(page)

        # 4. 选择第一个推荐封面帧（best-effort；通常第一帧已自动选中）
        recommend_selectors = [
            ':text("推荐") ~ div img',
            ':text("推荐") + div img',
            ':text("推荐") ~ ul li:first-child',
            ':text("智能推荐") ~ div img',
            ':text("智能推荐") ~ ul li:first-child',
            '[class*="recommend"] [class*="item"]:first-child',
            '[class*="recommend"] [class*="frame"]:first-child',
        ]
        for sel in recommend_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    box = await el.bounding_box()
                    if box:
                        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    else:
                        await el.click()
                    await asyncio.sleep(0.4)
                    logger.info(f"封面帧已选择 via: {sel}")
                    break
            except Exception:
                continue

        # 5. 点击 modal 底部确认按钮（「设置横封面」或「设置模板封面」）
        #    新流程：此按钮点击后会再次触发推广弹窗
        for btn_text in ("设置横封面", "设置模板封面"):
            try:
                btn = page.locator(f'button:has-text("{btn_text}")').last
                if not await btn.is_visible(timeout=2000):
                    continue
                box = await btn.bounding_box()
                if box:
                    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                else:
                    await btn.click()
                logger.info(f"点击底部确认按钮：「{btn_text}」")
                await asyncio.sleep(1.2)
                # 处理点击后再次出现的推广弹窗
                await _dismiss_cover_promo_popup(page)
                break
            except Exception:
                continue

        # 6. 点击「完成」
        done_btn = page.locator('button:has-text("完成")').last
        await done_btn.wait_for(state="visible", timeout=8000)
        await done_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        box = await done_btn.bounding_box()
        if box:
            await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        else:
            await done_btn.click()
        await asyncio.sleep(1)
        logger.info("Cover set (智能推荐 第1帧)")

    except Exception as e:
        logger.warning(f"Cover set failed (non-fatal, user can set manually): {e}")
        try:
            close = page.locator('[aria-label="Close"], [aria-label="关闭"], button:has-text("×")').first
            if await close.is_visible(timeout=1500):
                await close.click()
        except Exception:
            pass


async def _find_sibling_button(anchor_locator, button_text: str):
    """
    Walk up the DOM from anchor_locator, searching each ancestor level for any
    element (button, span, div, a) whose trimmed text matches button_text exactly.
    Returns the first matching Playwright Locator, or None.
    """
    xpath_up = ""
    pattern = re.compile(rf"^{re.escape(button_text)}$")
    # Search button, span, div, a — Douyin uses span/div for input-suffix actions
    tags = ["button", "span", "div", "a"]
    for levels in range(1, 8):
        xpath_up += "/.."
        try:
            container = anchor_locator.locator(f"xpath={xpath_up}")
            for tag in tags:
                el = container.locator(tag).filter(has_text=pattern)
                if await el.count() > 0:
                    logger.info(f"_find_sibling_button: '{button_text}' found as <{tag}> at {levels} level(s) up")
                    return el.first
        except Exception:
            pass
    return None


async def _attach_product(page, product_link: str, short_title: str = ""):
    """
    Add one product: fill link input → click '添加链接' (anchored to same container)
    → handle 编辑商品 dialog.  JS fallback if first click misses.
    """
    try:
        # 1. Fill the product link input
        link_input = page.locator(
            'input[placeholder*="粘贴商品链接"], input[placeholder*="商品链接"]'
        ).first
        await link_input.wait_for(state="visible", timeout=8000)
        await link_input.scroll_into_view_if_needed()
        await asyncio.sleep(0.3)
        await link_input.click()
        await asyncio.sleep(0.1)
        await link_input.fill(product_link)
        await asyncio.sleep(1.0)

        # 2. Locate "添加链接" — it is a span/div suffix inside the input wrapper,
        #    NOT a <button>.  Use get_by_text first (fastest), then DOM-walk fallback.
        add_btn = page.get_by_text("添加链接", exact=True).first
        btn_visible = False
        try:
            btn_visible = await add_btn.is_visible(timeout=2000)
        except Exception:
            pass

        if not btn_visible:
            add_btn = await _find_sibling_button(link_input, "添加链接")

        if add_btn is None:
            logger.warning(f"添加链接 element not found for: {product_link}")
            await link_input.clear()
            return

        # 3. Wait up to 5 s for the element to become enabled / not greyed-out
        #    Douyin validates the link asynchronously — stays disabled until done
        enabled = False
        for _ in range(25):
            try:
                el_class = await add_btn.get_attribute("class") or ""
                is_disabled   = await add_btn.get_attribute("disabled")
                aria_disabled = await add_btn.get_attribute("aria-disabled")
                # "disabled" in class covers both <button disabled> and styled spans
                if (is_disabled is None and aria_disabled != "true"
                        and "disabled" not in el_class and "gray" not in el_class):
                    enabled = True
                    break
            except Exception:
                pass
            await asyncio.sleep(0.2)

        if not enabled:
            logger.warning(f"添加链接 still disabled after 5 s — invalid link: {product_link}")
            await link_input.clear()
            return

        # 4. Scroll into view → fresh bounding box → page.mouse.click (trusted events)
        await add_btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.4)
        box = await add_btn.bounding_box()
        logger.info(f"添加链接 bounding_box: {box}")
        if box:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            await page.mouse.move(cx, cy)
            await asyncio.sleep(0.15)
            await page.mouse.click(cx, cy)
        else:
            await add_btn.click()
        await asyncio.sleep(1.2)

        # 5. Verify click landed: expect 编辑商品 dialog or a product-added indicator
        edit_visible = await page.locator(':text("编辑商品")').first.is_visible()
        if not edit_visible:
            logger.info("No dialog after first click — trying JS fallback")
            js_ok = await page.evaluate("""() => {
                const input = document.querySelector(
                    'input[placeholder*="粘贴商品链接"], input[placeholder*="商品链接"]'
                );
                if (!input) return false;
                // Walk up and search any element type (span/div/button/a)
                let el = input.parentElement;
                for (let i = 0; i < 8; i++) {
                    if (!el) break;
                    for (const node of el.querySelectorAll('button, span, div, a')) {
                        if (node.textContent.trim() === '添加链接') {
                            node.scrollIntoView({block: 'center'});
                            node.click();
                            return true;
                        }
                    }
                    el = el.parentElement;
                }
                return false;
            }""")
            logger.info(f"JS fallback result: {js_ok}")
            await asyncio.sleep(1.2)

        # 6. Check for "未搜索到对应商品" error dialog
        error_dialog = page.locator(':text("未搜索到对应商品")').first
        if await error_dialog.is_visible(timeout=3000):
            logger.warning(f"Product not found / unsupported link: {product_link}")
            ok_btn = page.locator('button:has-text("确定")').first
            if await ok_btn.is_visible(timeout=2000):
                await ok_btn.click()
                await asyncio.sleep(0.5)
            try:
                await link_input.click()
                await link_input.clear()
            except Exception:
                pass
            return

        # 7. Handle 编辑商品 dialog
        edit_dialog = page.locator(':text("编辑商品")').first
        if await edit_dialog.is_visible(timeout=5000):
            logger.info("编辑商品 dialog appeared")
            short_input = page.locator(
                'input[placeholder*="短标题"], input[placeholder*="商品短标题"]'
            ).first
            if await short_input.is_visible(timeout=2000):
                await short_input.click()
                current_val = await short_input.input_value()
                if not current_val.strip():
                    await short_input.fill((short_title or "精选假发")[:10])
                    await asyncio.sleep(0.3)
            done_btn = page.locator('button:has-text("完成编辑")').first
            await done_btn.wait_for(state="visible", timeout=5000)
            await done_btn.click()
            await asyncio.sleep(1)
            logger.info(f"编辑商品 confirmed for {product_link}")
        else:
            logger.info(f"Product added (no dialog): {product_link}")

    except Exception as e:
        logger.warning(f"_attach_product failed ({product_link}): {e}")
        try:
            for btn_text in ["取消", "关闭"]:
                btn = page.locator(f'button:has-text("{btn_text}")').first
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    break
        except Exception:
            pass
