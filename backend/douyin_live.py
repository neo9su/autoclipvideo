"""
Douyin live stream URL detection.

yt-dlp does not support live.douyin.com URLs.
This module fetches the live page HTML directly and extracts
the embedded FLV/HLS stream URLs.

Flow:
  1. GET https://live.douyin.com/{room_id}  → get ttwid cookie + HTML
  2. Parse self.__pace_f escaped JSON for explicit room status (0/1/2)
  3. Regex-extract flv_pull_url from embedded JSON
  4. Return stream URL (or None if room is offline)
"""
import json
import logging
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
    Extract an FLV stream URL from the Douyin live page HTML.
    The page embeds JSON with \\u0026-escaped ampersands.
    Prefer lower-quality streams (smaller, more stable for recording).
    """
    pattern = r'"(https://pull-[^"]*?\.flv\?[^"]*?)"'
    matches = re.findall(pattern, html)
    if not matches:
        pattern_hls = r'"(https://pull-[^"]*?\.m3u8\?[^"]*?)"'
        matches = re.findall(pattern_hls, html)

    if not matches:
        return None

    url = matches[0]
    url = url.replace("\\u0026", "&").replace("\\/", "/")
    return url


async def _fetch_page(room_id: str) -> Optional[str]:
    """Fetch the Douyin live page HTML, persisting cookies across calls."""
    target_url = f"https://live.douyin.com/{room_id}"
    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            cookies=_cookies,
            follow_redirects=True,
            timeout=20.0,
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


async def get_stream_url(room_url: str) -> Optional[str]:
    """
    Return the live FLV stream URL for a Douyin live room,
    or None if the room is offline / not found.
    """
    room_id = _extract_room_id(room_url)
    if not room_id:
        logger.error(f"Cannot extract room_id from URL: {room_url}")
        return None

    html = await _fetch_page(room_id)
    if html is None:
        return None

    # Check explicit status first — fast fail if clearly offline
    status = _parse_live_status(html)
    if status is not None:
        logger.debug(f"[{room_id}] __INIT_PROPS__ status={status}")
        if status != 1:
            logger.debug(f"[{room_id}] Room not live (status={status})")
            return None

    stream_url = _parse_stream_url(html)
    if stream_url:
        logger.debug(f"[{room_id}] Stream URL found: {stream_url[:80]}…")
    else:
        if status is None:
            # No status field and no stream URL → assume offline
            logger.debug(f"[{room_id}] No status or stream URL in page → offline")
        else:
            logger.warning(f"[{room_id}] Status=1 but no stream URL found in page")
    return stream_url


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
