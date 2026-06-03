"""
Douyin live stream URL detection.

yt-dlp does not support live.douyin.com URLs.
This module fetches the live page HTML directly and extracts
the embedded FLV/HLS stream URLs.

Flow:
  1. GET https://live.douyin.com/{room_id}  → get ttwid cookie + HTML
  2. Try webcast API for structured quality dict (ORIGIN/UHD/HD1/SD1/LD1)
  3. Fall back to regex-extract flv_pull_url from embedded HTML JSON
  4. Return highest-quality stream URL (or None if room is offline)

For ORIGIN quality, set env var DOUYIN_COOKIE_FILE to a Playwright cookie
JSON file path (e.g. ~/.douyin-publisher/cookies/douyin_1.json).
If unset, the first available file in that directory is used automatically.
"""
import glob
import json
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://live.douyin.com/",
}

# Shared cookie store (ttwid persists across calls within a process)
_cookies: dict = {}

# Auth cookies loaded from a Playwright cookie file for ORIGIN quality access
_auth_cookies: dict = {}
_auth_cookies_loaded = False


def _load_auth_cookies() -> dict:
    """
    Load Douyin auth cookies from a Playwright cookie JSON file.
    Tries DOUYIN_COOKIE_FILE env var first, then auto-discovers the first
    available file in ~/.douyin-publisher/cookies/douyin_*.json.
    Returns a flat {name: value} dict suitable for httpx.
    """
    global _auth_cookies, _auth_cookies_loaded
    if _auth_cookies_loaded:
        return _auth_cookies

    _auth_cookies_loaded = True
    cookie_file = os.environ.get("DOUYIN_COOKIE_FILE", "")
    if not cookie_file:
        pattern = os.path.expanduser("~/.douyin-publisher/cookies/douyin_*.json")
        candidates = sorted(glob.glob(pattern))
        cookie_file = candidates[0] if candidates else ""

    if not cookie_file or not os.path.exists(cookie_file):
        logger.debug("[stream] No auth cookie file found; will use guest quality")
        return {}

    try:
        with open(cookie_file, encoding="utf-8") as f:
            cookies_list = json.load(f)  # Playwright format: [{name, value, ...}]
        _auth_cookies = {c["name"]: c["value"] for c in cookies_list if "name" in c and "value" in c}
        logger.info(f"[stream] Loaded {len(_auth_cookies)} auth cookies from {cookie_file}")
    except Exception as e:
        logger.warning(f"[stream] Failed to load auth cookies from {cookie_file}: {e}")
    return _auth_cookies


def _extract_room_id(url: str) -> Optional[str]:
    m = re.search(r"live\.douyin\.com/(\d+)", url)
    return m.group(1) if m else None


def _parse_live_status(html: str) -> Optional[int]:
    """
    Extract explicit room status from page state.
    Returns 0 (offline/not started), 1 (live), 2 (ended), or None if not found.
    """
    # Current Douyin format: self.__pace_f stores state as escaped JSON.
    # Room status is always paired with status_str field.
    m = re.search(r'\\"status\\":(\d+),\\"status_str\\":\\"', html)
    if m:
        return int(m.group(1))
    # Legacy fallback: window.__INIT_PROPS__ (older Douyin page format)
    m2 = re.search(r'window\.__INIT_PROPS__\s*=\s*(\{.*?\});', html, re.DOTALL)
    if m2:
        try:
            data = json.loads(m2.group(1))
            status = (data.get("roomStore", {})
                          .get("roomInfo", {})
                          .get("room", {})
                          .get("status"))
            if status is not None:
                return int(status)
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
    return None


def _parse_stream_url(html: str) -> Optional[str]:
    """
    Extract the highest-quality FLV stream URL from the Douyin live page HTML.
    The page embeds JSON with \\u0026-escaped ampersands.
    Quality preference: origin > uhd > hd > sd > ld (highest → lowest).
    """
    pattern = r'"(https://pull-[^"]*?\.flv\?[^"]*?)"'
    matches = re.findall(pattern, html)
    if not matches:
        pattern_hls = r'"(https://pull-[^"]*?\.m3u8\?[^"]*?)"'
        matches = re.findall(pattern_hls, html)

    if not matches:
        return None

    # Decode escape sequences for all candidates
    candidates = [m.replace("\\u0026", "&").replace("\\/", "/") for m in matches]

    # Sort by quality: origin > uhd > hd > sd > ld; unknown scores 0
    _QUALITY_RANK = {"origin": 5, "uhd": 4, "hd": 3, "sd": 2, "ld": 1}

    def _quality_score(url: str) -> int:
        url_lower = url.lower()
        for q, rank in _QUALITY_RANK.items():
            if q in url_lower:
                return rank
        return 0

    best = max(candidates, key=_quality_score)
    logger.debug(f"Stream quality selected: score={_quality_score(best)} url={best[:80]}…")
    return best


async def _fetch_page(room_id: str) -> Optional[str]:
    """Fetch the Douyin live page HTML, persisting cookies across calls."""
    target_url = f"https://live.douyin.com/{room_id}"
    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            cookies=_cookies,
            follow_redirects=True,
            timeout=20.0,
            trust_env=False,  # 不读系统代理，避免代理未启动时连接失败
        ) as client:
            resp = await client.get(target_url)
        _cookies.update(dict(resp.cookies))
        if resp.status_code != 200:
            logger.warning(f"Douyin live page returned {resp.status_code} for {room_id}")
            return None
        return resp.text
    except Exception as e:
        logger.error(f"Error fetching Douyin live page for {room_id}: {e}")
        return None


_WEBCAST_API = "https://live.douyin.com/webcast/room/web/enter/"
_WEBCAST_PARAMS = {
    "aid": "6383",
    "app_name": "douyin_web",
    "live_id": "1",
    "device_platform": "web",
    "language": "zh-CN",
    "enter_from": "web_live",
    "cookie_enabled": "true",
    "screen_width": "1920",
    "screen_height": "1080",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Chrome",
    "browser_version": "120.0.0.0",
}

# Quality priority for webcast API flv_pull_url keys (higher = better)
_WEBCAST_QUALITY_RANK = {"ORIGIN": 6, "FULL_HD1": 5, "UHD": 4, "HD1": 3, "SD1": 2, "LD1": 1}


async def _fetch_webcast_stream(room_id: str) -> Optional[str]:
    """
    Call the Douyin webcast API to get a structured quality dict.
    Returns the highest-quality FLV URL available, or None on failure.
    With auth cookies, ORIGIN quality is available; without, LD1 only.
    """
    auth = _load_auth_cookies()
    combined_cookies = {**_cookies, **auth}  # auth overrides ttwid if present
    params = {**_WEBCAST_PARAMS, "web_rid": room_id}
    headers = {**_HEADERS, "Accept": "application/json, text/plain, */*"}
    try:
        async with httpx.AsyncClient(
            headers=headers,
            cookies=combined_cookies,
            follow_redirects=True,
            timeout=15.0,
            trust_env=False,  # 不读系统代理
        ) as client:
            resp = await client.get(_WEBCAST_API, params=params)
        if resp.status_code != 200:
            logger.debug(f"[{room_id}] Webcast API returned {resp.status_code}")
            return None
        data = resp.json()
    except Exception as e:
        logger.debug(f"[{room_id}] Webcast API error: {e}")
        return None

    # Navigate: data.data[0].stream_url.flv_pull_url
    try:
        room_list = data.get("data", {}).get("data") or []
        if not room_list:
            return None
        flv_map: dict = room_list[0].get("stream_url", {}).get("flv_pull_url", {})
        if not flv_map:
            return None
    except (AttributeError, IndexError, TypeError):
        return None

    # Pick highest quality available
    best_key = max(flv_map.keys(), key=lambda k: _WEBCAST_QUALITY_RANK.get(k, 0))
    best_url = flv_map[best_key]
    quality_score = _WEBCAST_QUALITY_RANK.get(best_key, 0)
    logger.info(f"[{room_id}] Webcast API: quality={best_key}({quality_score}) url={best_url[:80]}…")
    return best_url


async def get_stream_url(room_url: str) -> Optional[str]:
    """
    Return the live FLV stream URL for a Douyin live room,
    or None if the room is offline / not found.

    Tries the webcast API first (supports ORIGIN/UHD/HD1/SD1/LD1 quality dict);
    falls back to HTML regex extraction if the API call fails or returns nothing.
    """
    room_id = _extract_room_id(room_url)
    if not room_id:
        logger.error(f"Cannot extract room_id from URL: {room_url}")
        return None

    # Fetch HTML first to acquire ttwid cookie (needed by webcast API)
    html = await _fetch_page(room_id)

    # Try webcast API for structured quality selection
    stream_url = await _fetch_webcast_stream(room_id)
    if stream_url:
        return stream_url

    # Fall back to regex parsing of embedded HTML JSON
    if html is None:
        return None
    stream_url = _parse_stream_url(html)
    if stream_url:
        logger.debug(f"[{room_id}] HTML fallback: url={stream_url[:80]}…")
        return stream_url

    # No stream URL → offline. Log status for debugging.
    status = _parse_live_status(html)
    logger.debug(f"[{room_id}] No stream URL found → offline (status={status})")
    return None


async def check_live_status(room_url: str) -> bool:
    """Return True if the room is currently live."""
    room_id = _extract_room_id(room_url)
    if not room_id:
        return False

    html = await _fetch_page(room_id)
    if html is None:
        return False

    status = _parse_live_status(html)
    if status is not None:
        return status == 1

    # Fallback: stream URL presence as proxy for live status
    return _parse_stream_url(html) is not None
