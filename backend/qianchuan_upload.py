"""Qianchuan learning material upload API.

Provides a safe upload endpoint for reference videos and auxiliary materials
(mp4/mov/webm video, jpg/png images, mp3/wav audio, srt subtitles).

## Security

- Filenames are sanitised with a UUID prefix; no client-supplied paths accepted.
- Upload directory is scoped under ``UPLOAD_ROOT``; path traversal is prevented.
- MIME type and extension are validated against an allowlist.
- Per-request size limit enforced before writing to disk.
- Duplicate filenames never overwrite an existing upload (UUID prefix).

## Task Lifecycle

After upload a background analysis task is spawned and returns a ``job_id``.
Callers poll ``GET /api/v2/qianchuan/upload/{job_id}`` to track progress
through ``queued → running → succeeded/failed``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

UPLOAD_ROOT = os.environ.get(
    "QIANCHUAN_UPLOAD_DIR",
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "qianchuan_uploads")),
)

MAX_VIDEO_SIZE_BYTES = int(os.environ.get("QIANCHUAN_MAX_VIDEO_SIZE", str(500 * 1024 * 1024)))  # 500 MiB
MAX_AUX_SIZE_BYTES = int(os.environ.get("QIANCHUAN_MAX_AUX_SIZE", str(50 * 1024 * 1024)))  # 50 MiB
MAX_FILES_PER_REQUEST = 10

ALLOWED_VIDEO_EXTENSIONS: Set[str] = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
ALLOWED_IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ALLOWED_AUDIO_EXTENSIONS: Set[str] = {".mp3", ".wav", ".aac", ".ogg", ".flac"}
ALLOWED_TEXT_EXTENSIONS: Set[str] = {".srt", ".vtt", ".ass", ".json"}

ALLOWED_EXTENSIONS: Set[str] = (
    ALLOWED_VIDEO_EXTENSIONS
    | ALLOWED_IMAGE_EXTENSIONS
    | ALLOWED_AUDIO_EXTENSIONS
    | ALLOWED_TEXT_EXTENSIONS
)

ALLOWED_MIME_TYPES: Set[str] = {
    "video/mp4", "video/quicktime", "video/webm", "video/x-matroska", "video/x-msvideo",
    "image/jpeg", "image/png", "image/bmp", "image/webp",
    "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac", "audio/ogg", "audio/flac",
    "text/plain", "application/octet-stream",
    "application/x-subrip", "text/vtt",
}

# Status constants
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

# ── Router ───────────────────────────────────────────────────────────────────

qianchuan_upload_router = APIRouter(prefix="/api/v2/qianchuan", tags=["qianchuan-upload"])

# ── In-memory job store (shared across requests) ─────────────────────────────

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = asyncio.Lock()

# ── Tracking set to prevent duplicate submissions ────────────────────────────

_recent_uploads: Set[str] = set()
_uploads_lock = asyncio.Lock()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _safe_filename(original: str | None) -> str:
    """Produce a safe, collision-resistant filename from user-supplied input.

    Uses a UUID prefix so that (a) path traversal is impossible and
    (b) two uploads of ``video.mp4`` from different users never collide.
    """
    if not original:
        original = "upload.bin"

    # Extract extension: last dot-separated component, restricted to known chars
    stem, _, ext = original.rpartition(".")
    ext = re.sub(r"[^\w]", "", ext).lower()
    if not ext or ext not in {
        e.lstrip(".") for e in ALLOWED_EXTENSIONS
    }:
        ext = "bin"

    safe_stem = re.sub(r"[^\w\-]", "_", stem)[:64]
    return f"{uuid.uuid4().hex[:12]}_{safe_stem}.{ext}"


def _validate_extension(filename: str, allowlist: Set[str]) -> bool:
    ext = Path(filename).suffix.lower()
    return ext in allowlist


def _classify_file_type(filename: str) -> str:
    """Return ``'video'``, ``'image'``, ``'audio'``, ``'text'``, or ``'other'``."""
    ext = Path(filename).suffix.lower()
    if ext in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    if ext in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if ext in ALLOWED_AUDIO_EXTENSIONS:
        return "audio"
    if ext in ALLOWED_TEXT_EXTENSIONS:
        return "text"
    return "other"


def _validate_mime(content_type: str | None) -> bool:
    """Check that the Content-Type header looks acceptable.

    We accept ``application/octet-stream`` as a fallback because many
    browsers and curl send it for unknown file types.
    """
    if not content_type:
        return True  # defer to extension check
    ct = content_type.split(";")[0].strip().lower()
    return ct in ALLOWED_MIME_TYPES


def _ensure_upload_root() -> str:
    """Create the upload root directory if it does not exist.

    Returns the absolute, normalised path.
    """
    root = os.path.abspath(os.path.normpath(UPLOAD_ROOT))
    os.makedirs(root, exist_ok=True)
    return root


def _is_path_safe(root: str, target: str) -> bool:
    """Prevent path-traversal by ensuring *target* is inside *root*."""
    try:
        real_root = os.path.realpath(root)
        real_target = os.path.realpath(os.path.join(root, target))
        return os.path.commonpath([real_root]) == os.path.commonpath([real_root, real_target])
    except (ValueError, OSError):
        return False


def _reject_invalid_filename(filename: str) -> None:
    """Raise HTTPException if *filename* looks like a path traversal attempt."""
    if not filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    if len(filename) > 255:
        raise HTTPException(status_code=400, detail="文件名不能超过 255 个字符")
    if ".." in filename or "/" in filename or "\\" in filename or "\0" in filename:
        raise HTTPException(status_code=400, detail="文件名包含非法字符")
    if not _validate_extension(filename, ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {Path(filename).suffix}. 支持的格式: "
            + ", ".join(sorted(e.lstrip(".") for e in ALLOWED_EXTENSIONS)),
        )


# ── Job store helpers ───────────────────────────────────────────────────────


def _create_job(job_id: str, uploads: List[Dict[str, Any]]) -> Dict[str, Any]:
    job = {
        "job_id": job_id,
        "status": STATUS_QUEUED,
        "uploads": uploads,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "analysis_dir": None,
    }
    _jobs[job_id] = job
    return job


async def _update_job(job_id: str, **fields) -> None:
    async with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


# ── Analysis task ───────────────────────────────────────────────────────────


async def _run_learning_analysis(job_id: str, video_path: str, auxiliary: List[str]) -> None:
    """Background task: run analysis on uploaded reference materials."""
    await _update_job(job_id, status=STATUS_RUNNING, started_at=time.time())

    try:
        from qianchuan_learning import analyze_video, score_quality, serialize_analysis

        # prepare a minimal analysis directory structure if just a video was uploaded
        analysis_dir = os.path.dirname(video_path)

        result = await analyze_video(analysis_dir)
        serialized = serialize_analysis(result)

        quality = score_quality(result)

        await _update_job(
            job_id,
            status=STATUS_SUCCEEDED,
            finished_at=time.time(),
            result={
                "analysis": serialized,
                "quality": {
                    "overall": quality.overall,
                    "validated": quality.validated,
                    "dimensions": {
                        "visual": quality.visual.score,
                        "audio": quality.audio.score,
                        "semantic": quality.semantic.score,
                        "structural": quality.structural.score,
                        "conversion": quality.conversion.score,
                    },
                    "suggestions": (
                        quality.visual.suggestions
                        + quality.audio.suggestions
                        + quality.semantic.suggestions
                        + quality.structural.suggestions
                        + quality.conversion.suggestions
                    ),
                },
                "material_errors": result.material_errors,
            },
            analysis_dir=analysis_dir,
        )
    except Exception as exc:
        logger.exception("Qianchuan upload analysis failed for job %s", job_id)
        await _update_job(
            job_id,
            status=STATUS_FAILED,
            finished_at=time.time(),
            error=str(exc)[:2000],
        )


# ── API Routes ───────────────────────────────────────────────────────────────


@qianchuan_upload_router.get("/upload-status")
async def get_upload_service_status():
    """Return upload service health (no auth required)."""
    root = _ensure_upload_root()
    return {
        "service": "qianchuan-upload",
        "available": True,
        "upload_root": root,
        "max_video_size_bytes": MAX_VIDEO_SIZE_BYTES,
        "max_aux_size_bytes": MAX_AUX_SIZE_BYTES,
        "max_files_per_request": MAX_FILES_PER_REQUEST,
        "allowed_extensions": sorted(e.lstrip(".") for e in ALLOWED_EXTENSIONS),
    }


@qianchuan_upload_router.post("/upload")
async def upload_qianchuan_materials(
    file: UploadFile = File(..., description="Reference video (required)"),
    auxiliary: List[UploadFile] = File(default_factory=list, description="Optional auxiliary materials"),
    label: Optional[str] = Form(default=None, max_length=200),
    trigger_analysis: bool = Form(default=True),
):
    """Upload Qianchuan learning reference materials.

    At least one video file is required.  Auxiliary files (images, audio,
    SRT subtitles) are optional.

    Returns a ``job_id`` that can be polled via
    ``GET /api/v2/qianchuan/upload/{job_id}``.
    """
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="必须上传至少一个参考视频")

    _reject_invalid_filename(file.filename)
    if not _validate_mime(file.content_type):
        raise HTTPException(status_code=415, detail=f"不支持的媒体类型: {file.content_type}")

    if not _validate_extension(file.filename, ALLOWED_VIDEO_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"主文件必须是视频格式 (mp4/mov/webm/mkv/avi)，收到: {Path(file.filename).suffix}",
        )

    # size validation for the main video
    if file.size is not None and file.size > MAX_VIDEO_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"视频文件超过大小限制 ({MAX_VIDEO_SIZE_BYTES // (1024*1024)} MiB)",
        )

    total_files = 1 + len(auxiliary)
    if total_files > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"最多同时上传 {MAX_FILES_PER_REQUEST} 个文件",
        )

    # Validate auxiliary files
    for aux in auxiliary:
        if not aux.filename:
            raise HTTPException(status_code=400, detail="辅助文件名不能为空")
        _reject_invalid_filename(aux.filename)
        if not _validate_mime(aux.content_type):
            raise HTTPException(status_code=415, detail=f"不支持的辅助文件类型: {aux.content_type}")
        if aux.size is not None and aux.size > MAX_AUX_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"辅助文件超过大小限制 ({MAX_AUX_SIZE_BYTES // (1024*1024)} MiB)",
            )

    # Ensure upload root
    root = _ensure_upload_root()

    # Create a job-scoped subdirectory
    job_id = uuid.uuid4().hex[:16]
    job_dir = os.path.join(root, job_id)
    os.makedirs(job_dir, exist_ok=True)

    uploaded: List[Dict[str, Any]] = []

    try:
        # Save main video
        safe_name = _safe_filename(file.filename)
        video_path = os.path.join(job_dir, safe_name)
        if not _is_path_safe(root, os.path.join(job_id, safe_name)):
            raise HTTPException(status_code=400, detail="文件名不安全")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")

        if len(content) > MAX_VIDEO_SIZE_BYTES:
            raise HTTPException(status_code=413, detail=f"视频文件超过大小限制")

        with open(video_path, "wb") as f:
            f.write(content)

        file_type = _classify_file_type(file.filename)
        uploaded.append({
            "filename": safe_name,
            "original_name": file.filename,
            "type": file_type,
            "size_bytes": len(content),
            "path": video_path,
        })
        logger.info("Qianchuan upload saved video: %s (%d bytes) → %s", file.filename, len(content), video_path)

        # Save auxiliary files
        for aux in auxiliary:
            aux_content = await aux.read()
            if not aux_content:
                continue

            if len(aux_content) > MAX_AUX_SIZE_BYTES:
                raise HTTPException(status_code=413, detail=f"辅助文件 {aux.filename} 超过大小限制")

            aux_safe = _safe_filename(aux.filename)
            aux_path = os.path.join(job_dir, aux_safe)
            if not _is_path_safe(root, os.path.join(job_id, aux_safe)):
                raise HTTPException(status_code=400, detail=f"辅助文件名不安全: {aux.filename}")

            with open(aux_path, "wb") as f:
                f.write(aux_content)

            aux_type = _classify_file_type(aux.filename)
            uploaded.append({
                "filename": aux_safe,
                "original_name": aux.filename,
                "type": aux_type,
                "size_bytes": len(aux_content),
                "path": aux_path,
            })
            logger.info("Qianchuan upload saved auxiliary: %s (%d bytes) → %s", aux.filename, len(aux_content), aux_path)

    except HTTPException:
        # Clean up partial uploads on validation failure
        for item in uploaded:
            try:
                os.remove(item["path"])
            except OSError:
                pass
        try:
            os.rmdir(job_dir)
        except OSError:
            pass
        raise
    except Exception as exc:
        logger.exception("Unexpected error during qianchuan upload")
        for item in uploaded:
            try:
                os.remove(item["path"])
            except OSError:
                pass
        try:
            os.rmdir(job_dir)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"上传失败: {str(exc)[:500]}")

    # Create job record
    job = _create_job(job_id, uploaded)

    # Trigger background analysis if requested
    if trigger_analysis:
        aux_paths = [u["path"] for u in uploaded if u["type"] != "video"]
        asyncio.create_task(_run_learning_analysis(job_id, video_path, aux_paths))
    else:
        job["status"] = STATUS_SUCCEEDED

    return JSONResponse(
        status_code=201,
        content={
            "job_id": job_id,
            "status": job["status"],
            "uploads": [
                {
                    "filename": u["filename"],
                    "original_name": u["original_name"],
                    "type": u["type"],
                    "size_bytes": u["size_bytes"],
                }
                for u in uploaded
            ],
            "label": label,
        },
    )


@qianchuan_upload_router.get("/upload/{job_id}")
async def get_upload_job_status(job_id: str):
    """Poll the status of a qianchuan upload/analysis job.

    Returns the current status (``queued``, ``running``, ``succeeded``,
    ``failed``) along with results when available.

    Parameters
    ----------
    job_id : str
        Job ID returned by ``POST /api/v2/qianchuan/upload``.
    """
    if not re.fullmatch(r"[a-f0-9]{16}", job_id):
        raise HTTPException(status_code=400, detail="无效的 job_id")

    async with _jobs_lock:
        job = _jobs.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Job 不存在或已过期")

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "result": job.get("result"),
        "error": job.get("error"),
        "uploads": [
            {
                "filename": u["filename"],
                "original_name": u["original_name"],
                "type": u["type"],
                "size_bytes": u["size_bytes"],
            }
            for u in job.get("uploads", [])
        ],
        "analysis_dir": job.get("analysis_dir"),
    }


@qianchuan_upload_router.delete("/upload/{job_id}")
async def delete_upload_job(job_id: str):
    """Delete an upload job and its associated files."""
    if not re.fullmatch(r"[a-f0-9]{16}", job_id):
        raise HTTPException(status_code=400, detail="无效的 job_id")

    async with _jobs_lock:
        job = _jobs.pop(job_id, None)

    if job is None:
        raise HTTPException(status_code=404, detail="Job 不存在或已过期")

    # Clean up files
    for upload_item in job.get("uploads", []):
        try:
            path = upload_item.get("path")
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            logger.warning("Failed to remove upload file %s: %s", upload_item.get("path"), exc)

    # Try to remove the job directory
    if job.get("uploads"):
        first_path = job["uploads"][0].get("path")
        if first_path:
            job_dir = os.path.dirname(first_path)
            try:
                os.rmdir(job_dir)
            except OSError:
                pass  # directory may not be empty

    return {"job_id": job_id, "deleted": True}
