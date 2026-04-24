"""
画质增强作业管理 — Mac 后端

通过 HTTP 与 GPU 服务器上的 enhance_service.py (端口 8879) 通信。
提供作业提交、进度查询、结果下载接口给 main.py 调用。
"""

import asyncio
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

ENHANCE_SERVICE_URL = os.environ.get("ENHANCE_SERVICE_URL", "http://10.190.0.203:8877")


async def is_enhance_service_available() -> bool:
    try:
        async with aiohttp.ClientSession() as c:
            async with c.get(f"{ENHANCE_SERVICE_URL}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                return r.status == 200
    except Exception:
        return False


async def submit_enhance_job(
    filepath: str,
    model: str = "general",
    target_res: str = "1080p",
    denoise: str = "medium",
    preview_only: bool = False,
) -> Optional[str]:
    """
    上传文件到 GPU 增强服务，返回 job_id，失败返回 None。
    preview_only=True 时只处理前 5 秒（用于预览对比）。
    """
    filename = os.path.basename(filepath)
    try:
        form = aiohttp.FormData()
        form.add_field("model",        model)
        form.add_field("target_res",   target_res)
        form.add_field("denoise",      denoise)
        form.add_field("preview_only", str(preview_only).lower())
        with open(filepath, "rb") as f:
            form.add_field("file", f, filename=filename, content_type=_mime(filename))
            async with aiohttp.ClientSession() as c:
                async with c.post(
                    f"{ENHANCE_SERVICE_URL}/enhance-jobs",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=600),
                ) as resp:
                    if resp.status == 201:
                        body = await resp.json()
                        job_id = body["job_id"]
                        logger.info(f"Enhance job submitted: {job_id} file={filename}")
                        return job_id
                    text = await resp.text()
                    logger.warning(f"Enhance submit failed: {resp.status} {text[:200]}")
    except Exception as e:
        logger.warning(f"Enhance submit error: {e}")
    return None


async def get_enhance_job_status(job_id: str) -> Optional[dict]:
    """查询增强作业状态。返回 None 表示服务不可达；返回含 status='error' 表示作业丢失/失败。"""
    try:
        async with aiohttp.ClientSession() as c:
            async with c.get(
                f"{ENHANCE_SERVICE_URL}/enhance-jobs/{job_id}",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status == 200:
                    return await r.json()
                if r.status == 404:
                    # Job lost (service restarted) — treat as error so poll loop exits
                    logger.warning(f"Enhance job {job_id} not found on service (404) — service may have restarted")
                    return {"status": "error", "error": "作业记录丢失（服务已重启）"}
    except Exception as e:
        logger.debug(f"Enhance status error {job_id}: {e}")
    return None


async def download_enhance_result(job_id: str, dest_path: str) -> bool:
    """从 GPU 服务下载增强结果到本地路径"""
    try:
        async with aiohttp.ClientSession() as c:
            async with c.get(
                f"{ENHANCE_SERVICE_URL}/enhance-jobs/{job_id}/download",
                timeout=aiohttp.ClientTimeout(total=300),
            ) as r:
                if r.status != 200:
                    logger.warning(f"Enhance download failed {job_id}: {r.status}")
                    return False
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as f:
                    async for chunk in r.content.iter_chunked(1024 * 1024):
                        f.write(chunk)
        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 0
    except Exception as e:
        logger.warning(f"Enhance download error {job_id}: {e}")
        return False


async def delete_enhance_job(job_id: str) -> bool:
    """通知 GPU 服务删除作业文件"""
    try:
        async with aiohttp.ClientSession() as c:
            async with c.delete(
                f"{ENHANCE_SERVICE_URL}/enhance-jobs/{job_id}",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                return r.status == 200
    except Exception:
        return False


def _mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext in {".mp4", ".mov", ".avi", ".mkv"}:
        return "video/mp4"
    return "application/octet-stream"
