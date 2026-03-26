"""
画质增强服务 — 部署在 Windows GPU 服务器 (端口 8879)

依赖：
    pip install fastapi uvicorn httpx aiofiles

realesrgan-ncnn-vulkan 可执行文件放在同目录或 PATH 中：
    https://github.com/xinntao/Real-ESRGAN/releases  (windows 版)
    解压后将 realesrgan-ncnn-vulkan.exe 和 models/ 目录放到本脚本旁边

启动：
    python enhance_service.py
或：
    uvicorn enhance_service:app --host 0.0.0.0 --port 8879
"""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s enhance: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("enhance.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── 路径配置 ──────────────────────────────────────────────────────────────────

BASE_DIR   = Path(__file__).parent
ESRGAN_EXE = os.environ.get("ESRGAN_EXE", str(BASE_DIR / "realesrgan-ncnn-vulkan.exe"))
MODELS_DIR = os.environ.get("ESRGAN_MODELS", str(BASE_DIR / "models"))
WORK_DIR   = Path(os.environ.get("ENHANCE_WORK_DIR", BASE_DIR / "enhance_jobs"))
FFMPEG_EXE = os.environ.get("FFMPEG_EXE", "ffmpeg")

# 是否有 Whisper/GPU 转录任务正在运行（通过轮询本机转录服务接口得知）
TRANSCRIBE_SERVICE_URL = os.environ.get("TRANSCRIBE_SERVICE_URL", "http://localhost:8877")

# ── 模型映射 ──────────────────────────────────────────────────────────────────

MODELS = {
    "general":   "realesrgan-x4plus",       # 通用，真实场景最佳
    "portrait":  "realesrgan-x4plus",       # 人像（同模型，参数不同）
    "product":   "realesrgan-x4plus",       # 产品细节
    "anime":     "realesrgan-x4plus-anime", # 动漫/卡通
}

DENOISE_HQDN3D = {
    "low":    "hqdn3d=0:0:3:3",
    "medium": "hqdn3d=2:1:4:3",
    "high":   "hqdn3d=4:3:6:4",
}

# ── 作业状态存储（内存，服务重启后丢失） ────────────────────────────────────────

_jobs: Dict[str, dict] = {}
_job_lock = asyncio.Lock()

# ── 并发控制 ──────────────────────────────────────────────────────────────────

MAX_CONCURRENT = int(os.environ.get("ENHANCE_MAX_CONCURRENT", "1"))
_sem = asyncio.Semaphore(MAX_CONCURRENT)


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

async def _gpu_is_busy() -> bool:
    """检查转录服务是否正在使用 GPU（Whisper 运行时画质增强让步）"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{TRANSCRIBE_SERVICE_URL}/health")
            data = r.json()
            return data.get("gpu_busy", False)
    except Exception:
        return False


def _tile_size(busy: bool) -> int:
    """GPU 忙时用小 tile 节省 VRAM；空闲时全速"""
    return 256 if busy else 0   # 0 = 自动


async def _run(cmd: list, job_id: str, step_label: str) -> bool:
    """运行子进程，记录 stderr，更新作业日志"""
    logger.info(f"[{job_id}] {step_label}: {' '.join(str(c) for c in cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[-500:]
        logger.error(f"[{job_id}] {step_label} failed rc={proc.returncode}: {err}")
        _jobs[job_id]["error"] = f"{step_label} failed: {err}"
        return False
    return True


def _set(job_id: str, **kwargs):
    if job_id in _jobs:
        _jobs[job_id].update(kwargs)


# ── 核心处理流程 ───────────────────────────────────────────────────────────────

async def _process_image(job_id: str, src: Path, out: Path, model: str, scale: int, tile: int):
    """图片超分：单次 realesrgan 调用"""
    _set(job_id, status="running", pct=10, msg="AI 超分处理中")
    cmd = [
        ESRGAN_EXE,
        "-i", str(src),
        "-o", str(out),
        "-n", model,
        "-s", str(scale),
    ]
    if tile > 0:
        cmd += ["-t", str(tile)]
    if not await _run(cmd, job_id, "esrgan-image"):
        return False
    _set(job_id, pct=100, status="done", msg="完成")
    return True


async def _process_video(
    job_id: str,
    src: Path,
    out: Path,
    model: str,
    scale: int,
    tile: int,
    target_w: int,
    target_h: int,
    denoise: str,
    preview_only: bool,
):
    """
    视频增强流程：
      1. ffmpeg 抽帧（含降噪）
      2. realesrgan-ncnn-vulkan 批量超分
      3. ffmpeg 重组 + 缩放至目标分辨率
    """
    work = WORK_DIR / job_id
    frames_in  = work / "frames_in"
    frames_out = work / "frames_out"
    frames_in.mkdir(parents=True, exist_ok=True)
    frames_out.mkdir(parents=True, exist_ok=True)

    # ── 1. 提取帧（preview_only 只取前 5 秒）────────────────────────────────
    _set(job_id, pct=5, msg="提取视频帧")
    vf_denoise = DENOISE_HQDN3D.get(denoise, "")
    vf_filter  = vf_denoise if vf_denoise else "null"
    extract_cmd = [
        FFMPEG_EXE, "-y",
        "-i", str(src),
    ]
    if preview_only:
        extract_cmd += ["-t", "5"]
    extract_cmd += [
        "-vf", vf_filter,
        "-q:v", "1",
        str(frames_in / "frame_%06d.jpg"),
    ]
    if not await _run(extract_cmd, job_id, "extract-frames"):
        return False

    frame_files = sorted(frames_in.glob("frame_*.jpg"))
    total_frames = len(frame_files)
    if total_frames == 0:
        _set(job_id, error="未能提取到帧")
        return False
    logger.info(f"[{job_id}] 共 {total_frames} 帧")

    # ── 2. realesrgan 批量超分 ────────────────────────────────────────────
    _set(job_id, pct=10, msg=f"AI 超分（共 {total_frames} 帧）")
    esrgan_cmd = [
        ESRGAN_EXE,
        "-i", str(frames_in),
        "-o", str(frames_out),
        "-n", model,
        "-s", str(scale),
        "-f", "jpg",
    ]
    if tile > 0:
        esrgan_cmd += ["-t", str(tile)]

    # realesrgan-ncnn-vulkan 本身没有进度回调，启动后轮询输出帧数估算进度
    proc = await asyncio.create_subprocess_exec(
        *esrgan_cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    while proc.returncode is None:
        await asyncio.sleep(2)
        done = len(list(frames_out.glob("frame_*.jpg")))
        pct  = int(10 + (done / max(total_frames, 1)) * 75)
        _set(job_id, pct=pct, msg=f"AI 超分 {done}/{total_frames} 帧")
        try:
            proc.poll()
        except Exception:
            pass
    await proc.wait()
    if proc.returncode != 0:
        _set(job_id, error="realesrgan 超分失败")
        return False

    # ── 3. 重组视频 + 缩放至目标分辨率 ───────────────────────────────────
    _set(job_id, pct=88, msg="重组视频")

    # 获取原视频帧率和音频
    probe = await asyncio.create_subprocess_exec(
        FFMPEG_EXE, "-i", str(src),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, probe_err = await probe.communicate()
    fps = "25"
    for line in probe_err.decode(errors="replace").splitlines():
        if "fps" in line and "tbr" not in line:
            for tok in line.split(","):
                tok = tok.strip()
                if tok.endswith(" fps"):
                    fps = tok.split()[0]
                    break

    scale_vf = f"scale={target_w}:{target_h}:flags=lanczos"
    assemble_cmd = [
        FFMPEG_EXE, "-y",
        "-framerate", fps,
        "-i", str(frames_out / "frame_%06d.jpg"),
    ]
    if not preview_only:
        assemble_cmd += ["-i", str(src), "-map", "0:v", "-map", "1:a?"]
    assemble_cmd += [
        "-vf", scale_vf,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p",
    ]
    if not preview_only:
        assemble_cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    assemble_cmd.append(str(out))

    if not await _run(assemble_cmd, job_id, "assemble"):
        return False

    _set(job_id, pct=100, status="done", msg="完成")
    return True


async def _do_enhance(job_id: str):
    """实际增强任务，在信号量保护下执行"""
    job   = _jobs[job_id]
    work  = WORK_DIR / job_id
    src   = work / job["src_filename"]
    ext   = src.suffix.lower()
    is_img = ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff"}

    model_key    = job.get("model", "general")
    model        = MODELS.get(model_key, MODELS["general"])
    target_res   = job.get("target_res", "1080p")
    denoise      = job.get("denoise", "medium")
    preview_only = job.get("preview_only", False)

    # 目标分辨率
    res_map = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}
    target_w, target_h = res_map.get(target_res, (1920, 1080))

    # 输出路径
    suffix  = "_preview" if preview_only else "_enhanced"
    out_ext = ".jpg" if is_img else ".mp4"
    out_name = src.stem + suffix + out_ext
    out     = work / out_name
    _jobs[job_id]["out_filename"] = out_name

    try:
        async with _sem:
            # ── 等待 GPU 空闲（Vulkan 和 CUDA 共用显存，必须错开） ────────────
            wait_rounds = 0
            while True:
                busy = await _gpu_is_busy()
                if not busy:
                    break
                wait_rounds += 1
                if wait_rounds == 1:
                    logger.info(f"[{job_id}] GPU 正在转录，等待空闲再开始增强…")
                _set(job_id, status="running", pct=2,
                     msg=f"等待 GPU 空闲（已等 {wait_rounds * 5}s）…")
                await asyncio.sleep(5)
            # GPU 空闲，tile=0（自动，全速）
            tile = 0
            logger.info(f"[{job_id}] GPU 空闲，开始增强 tile={tile}")

            _set(job_id, status="running", pct=5, msg="准备中")
            if is_img:
                ok = await _process_image(job_id, src, out, model, scale=4, tile=tile)
            else:
                ok = await _process_video(
                    job_id, src, out, model, scale=4, tile=tile,
                    target_w=target_w, target_h=target_h,
                    denoise=denoise, preview_only=preview_only,
                )
        if not ok and _jobs[job_id].get("status") != "done":
            _set(job_id, status="error")
    except Exception as e:
        logger.exception(f"[{job_id}] 处理异常: {e}")
        _set(job_id, status="error", error=str(e))


# ── FastAPI 应用 ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"画质增强服务启动 ESRGAN={ESRGAN_EXE} WORK={WORK_DIR}")
    yield


app = FastAPI(title="画质增强服务", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    running = sum(1 for j in _jobs.values() if j.get("status") == "running")
    queued  = sum(1 for j in _jobs.values() if j.get("status") == "queued")
    return {"status": "ok", "running": running, "queued": queued}


@app.post("/enhance-jobs", status_code=201)
async def create_enhance_job(
    file:         UploadFile = File(...),
    model:        str = Form("general"),      # general / portrait / product / anime
    target_res:   str = Form("1080p"),        # 720p / 1080p / 4k
    denoise:      str = Form("medium"),       # low / medium / high
    preview_only: bool = Form(False),         # True = 仅处理前 5 秒
):
    job_id = str(uuid.uuid4())
    work   = WORK_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)

    # 保存上传文件
    safe_name = Path(file.filename or "upload").name
    dest = work / safe_name
    async with aiofiles.open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)

    _jobs[job_id] = {
        "job_id":       job_id,
        "status":       "queued",
        "pct":          0,
        "msg":          "排队中",
        "src_filename": safe_name,
        "out_filename": None,
        "model":        model,
        "target_res":   target_res,
        "denoise":      denoise,
        "preview_only": preview_only,
        "created_at":   time.time(),
        "error":        None,
    }

    asyncio.create_task(_do_enhance(job_id))
    logger.info(f"[{job_id}] 新任务: file={safe_name} model={model} res={target_res} preview={preview_only}")
    return {"job_id": job_id}


@app.get("/enhance-jobs/{job_id}")
def get_enhance_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {k: v for k, v in job.items() if k != "error" or job.get("status") == "error"}


@app.get("/enhance-jobs/{job_id}/download")
def download_result(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Job not done yet")
    out = WORK_DIR / job_id / job["out_filename"]
    if not out.exists():
        raise HTTPException(status_code=404, detail="Output file missing")
    return FileResponse(str(out), filename=job["out_filename"])


@app.delete("/enhance-jobs/{job_id}")
def delete_enhance_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    work = WORK_DIR / job_id
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    del _jobs[job_id]
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("ENHANCE_PORT", "8879"))
    logger.info(f"启动端口 {port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
