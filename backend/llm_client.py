"""
Shared LLM client with global semaphore.

All LLM calls in this project go through `llm_post()` to ensure:
1. Only 1 concurrent request to the proxy (proxy is single-threaded / limited)
2. Consistent timeout (180s — proxy may take ~20-90s for complex prompts)
3. Automatic retry with backoff on 429/502/503/timeout
"""
import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

# ── Config (from .env, mirrored from each module) ────────────────────────────
_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://10.190.0.214:8080/v1")
_LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-orx-KEuLek0QWDFoRupT9szOR_KvJ4V0pTsP")
LLM_MODEL = os.getenv("LLM_MODEL", "us.anthropic.claude-sonnet-4-6")

# ── Global semaphore: 1 concurrent LLM request at a time ─────────────────────
# The proxy (local-openrouter-gateway) is effectively single-threaded;
# concurrent requests cause 502. All callers must acquire this lock.
_LLM_SEM: asyncio.Semaphore | None = None


def get_llm_sem() -> asyncio.Semaphore:
    """Return (lazily creating) the global LLM semaphore."""
    global _LLM_SEM
    if _LLM_SEM is None:
        _LLM_SEM = asyncio.Semaphore(3)
    return _LLM_SEM


async def llm_post(
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int = 2000,
    temperature: float = 0.7,
    retries: int = 3,
    timeout: float = 180.0,
) -> str | None:
    """
    POST to /v1/chat/completions with global semaphore + retry.

    Returns the assistant message text, or None on failure.
    """
    payload = {
        "model": model or LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {_LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{_LLM_BASE_URL}/chat/completions"
    sem = get_llm_sem()

    async with sem:
        for attempt in range(1, retries + 1):
            try:
                # trust_env=False: prevent system proxy from intercepting internal LAN traffic
                async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]

                if resp.status_code in (429, 500, 502, 503) and attempt < retries:
                    wait = 10 * attempt
                    logger.warning(
                        f"LLM {resp.status_code} (attempt {attempt}/{retries}), retry in {wait}s"
                    )
                    await asyncio.sleep(wait)
                    continue

                logger.error(
                    f"LLM error {resp.status_code}: {resp.text[:300]}"
                )
                return None

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < retries:
                    wait = 10 * attempt
                    logger.warning(
                        f"LLM transient error ({e}) attempt {attempt}/{retries}, retry in {wait}s"
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"LLM failed after {retries} attempts: {e}")
                    return None

            except Exception as e:
                logger.error(f"LLM unexpected error: {e}")
                return None

    return None  # should not reach
