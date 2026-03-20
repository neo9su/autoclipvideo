"""
Douyin live stream URL detection.

yt-dlp does not support live.douyin.com URLs.
This module fetches the live page HTML directly and extracts
the embedded FLV/HLS stream URLs.

Flow:
  1. GET https://live.douyin.com/{room_id}  → get ttwid cookie + HTML
  2. Regex-extract flv_pull_url from embedded JSON
  3. Return stream URL (or None if room is offline)
"""
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
}

# Shared cookie store (ttwid persists across calls within a process)
_cookies: dict = {}


def _extract_room_id(url: str) -> Optional[str]:
    m = re.search(r"live\.douyin\.com/(\d+)", url)
    return m.group(1) if m else None


def _parse_stream_url(html: str) -> Optional[str]:
    """
    Extract an FLV stream URL from the Douyin live page HTML.
    The page embeds JSON with \\u0026-escaped ampersands.
    Prefer lower-quality streams (smaller, more stable for recording).
    """
    # Pattern: "https://pull-xxx.douyincdn.com/...flv?..."
    # The URL is JSON-string-escaped: & becomes \\u0026
    pattern = r'"(https://pull-[^"]*?\.flv\?[^"]*?)"'
    matches = re.findall(pattern, html)
    if not matches:
        # Try hls fallback
        pattern_hls = r'"(https://pull-[^"]*?\.m3u8\?[^"]*?)"'
        matches = re.findall(pattern_hls, html)

    if not matches:
        return None

    # Unescape \u0026 → & and \\/ → /
    url = matches[0]
    url = url.replace("\\u0026", "&").replace("\\/", "/")
    return url


async def get_stream_url(room_url: str) -> Optional[str]:
    """
    Return the live FLV stream URL for a Douyin live room,
    or None if the room is offline / not found.
    """
    room_id = _extract_room_id(room_url)
    if not room_id:
        logger.error(f"Cannot extract room_id from URL: {room_url}")
        return None

    target_url = f"https://live.douyin.com/{room_id}"
    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            cookies=_cookies,
            follow_redirects=True,
            timeout=20.0,
        ) as client:
            resp = await client.get(target_url)

        # Persist any new cookies (ttwid, etc.) for next call
        _cookies.update(dict(resp.cookies))

        if resp.status_code != 200:
            logger.warning(f"Douyin live page returned {resp.status_code} for {room_id}")
            return None

        stream_url = _parse_stream_url(resp.text)
        if stream_url:
            logger.debug(f"[{room_id}] Stream URL found: {stream_url[:80]}…")
        else:
            logger.debug(f"[{room_id}] No stream URL in page → offline")

        return stream_url

    except Exception as e:
        logger.error(f"Error fetching Douyin live page for {room_id}: {e}")
        return None


async def check_live_status(room_url: str) -> bool:
    """Return True if the room is currently live."""
    url = await get_stream_url(room_url)
    return url is not None
