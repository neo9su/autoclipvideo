"""
画质增强作业管理 — Mac 后端

通过 HTTP 与 GPU 服务器上的 enhance_service.py (端口 8879) 通信。
提供作业提交、进度查询、结果下载接口给 main.py 调用。
"""

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ENHANCE_SERVICE_URL = os.environ.get("ENHANCE_SERVICE_URL", "http://10.190.0.203:8877")
# 上传超时较长（视频可能很大）
_UPLOAD_TIMEOUT  = httpx.Timeout(600.0)
_DEFAULT_TIMEOUT = httpx.Timeout(30.0)


async def is_enhance_service_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{ENHANCE_SERVICE_URL}/health")
            return r.status_code == 200
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
        async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT) as c:
            with open(filepath, "rb") as f:
                resp = await c.post(
                    f"{ENHANCE_SERVICE_URL}/enhance-jobs",
                    files={"file": (filename, f, _mime(filename))},
                    data={
                        "model":        model,
                        "target_res":   target_res,
                        "denoise":      denoise,
                        "preview_only": str(preview_only).lower(),
                    },
                )
        if resp.status_code == 201:
            job_id = resp.json()["job_id"]
            logger.info(f"Enhance job submitted: {job_id} file={filename}")
            return job_id
        logger.warning(f"Enhance submit failed: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Enhance submit error: {e}")
    return None


async def get_enhance_job_status(job_id: str) -> Optional[dict]:
    """查询增强作业状态。返回 None 表示服务不可达；返回含 status='error' 表示作业丢失/失败。"""
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
            r = await c.get(f"{ENHANCE_SERVICE_URL}/enhance-jobs/{job_id}")
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                # Job lost (service restarted) — treat as error so poll loop exits
                logger.warning(f"Enhance job {job_id} not found on service (404) — service may have restarted")
                return {"status": "error", "error": "作业记录丢失（服务已重启）"}
    except Exception as e:
        logger.debug(f"Enhance status error {job_id}: {e}")
    return None


async def download_enhance_result(job_id: str, dest_path: str) -> bool:
    """从 GPU 服务下载增强结果到本地路径"""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as c:
            async with c.stream("GET", f"{ENHANCE_SERVICE_URL}/enhance-jobs/{job_id}/download") as r:
                if r.status_code != 200:
                    logger.warning(f"Enhance download failed {job_id}: {r.status_code}")
                    return False
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as f:
                    async for chunk in r.aiter_bytes(1024 * 1024):
                        f.write(chunk)
        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 0
    except Exception as e:
        logger.warning(f"Enhance download error {job_id}: {e}")
        return False


async def delete_enhance_job(job_id: str) -> bool:
    """通知 GPU 服务删除作业文件"""
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as c:
            r = await c.delete(f"{ENHANCE_SERVICE_URL}/enhance-jobs/{job_id}")
            return r.status_code == 200
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
