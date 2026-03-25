"""
Douyin GPU Transcription + Clip Service
Run on GPU server: uvicorn main:app --host 0.0.0.0 --port 8877
"""
import asyncio
import os
import sqlite3
import uuid

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

_DEFAULT_STORAGE = (
    r"C:\Users\neo\douyin_recordings" if os.name == "nt" else "/data/douyin-recordings"
)
STORAGE_DIR = os.environ.get("STORAGE_DIR", _DEFAULT_STORAGE)
os.makedirs(STORAGE_DIR, exist_ok=True)

DB_PATH = os.path.join(STORAGE_DIR, "jobs.db")

# ── In-memory stores ──────────────────────────────────────────────────────────
_jobs: dict = {}       # transcription jobs
_clip_jobs: dict = {}  # clip jobs
_model = None          # Singleton WhisperModel

# GPU concurrency: one transcription at a time (shares VRAM with ComfyUI)
_gpu_sem: asyncio.Semaphore = asyncio.Semaphore(1)
# NVENC concurrency: 2 concurrent — NVENC is a dedicated hardware unit, no VRAM cost
_clip_sem: asyncio.Semaphore = asyncio.Semaphore(2)

# ── Clip pipeline constants ───────────────────────────────────────────────────
CLIP_W    = 1080
CLIP_H    = 1920
CLIP_FADE = 1.5   # xfade duration (seconds)
SEG_PAD   = 0.5   # seconds of padding before/after each segment


# ── DB helpers ────────────────────────────────────────────────────────────────

def _init_db():
    """Create all tables and reset interrupted jobs."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'processing',
                mp4_path TEXT NOT NULL,
                srt_path TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clip_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'queued',
                phase TEXT DEFAULT 'queued',
                pct INTEGER DEFAULT 0,
                error TEXT,
                output_path TEXT,
                thumb_path TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "UPDATE jobs SET status = 'error', error = 'service restarted' WHERE status = 'processing'"
        )
        conn.execute(
            "UPDATE clip_jobs SET status = 'error', error = 'service restarted' WHERE status IN ('queued', 'processing')"
        )
        conn.commit()


def _load_jobs() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs").fetchall()
    return {r["job_id"]: dict(r) for r in rows}


def _load_clip_jobs() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM clip_jobs").fetchall()
    return {r["job_id"]: dict(r) for r in rows}


def _db_insert_job(job_id: str, mp4_path: str, srt_path: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, mp4_path, srt_path, status) VALUES (?, ?, ?, 'processing')",
            (job_id, mp4_path, srt_path),
        )
        conn.commit()


def _db_update_job(job_id: str, status: str, error: str = None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, error = ? WHERE job_id = ?",
            (status, error, job_id),
        )
        conn.commit()


def _db_insert_clip_job(job_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO clip_jobs (job_id, status, phase, pct) VALUES (?, 'queued', 'queued', 0)",
            (job_id,),
        )
        conn.commit()


def _db_update_clip_job(job_id: str, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE clip_jobs SET {sets} WHERE job_id = ?", vals)
        conn.commit()


def _update_clip_job(job_id: str, **kwargs):
    """Update both in-memory store and DB."""
    job = _clip_jobs.get(job_id)
    if job:
        job.update(kwargs)
    _db_update_clip_job(job_id, **kwargs)


# ── Transcription helpers ─────────────────────────────────────────────────────

def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel("large-v3", device="cuda", compute_type="float16")
    return _model


def _fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def _do_transcribe(job_id: str):
    job = _jobs[job_id]
    mp4_path = job["mp4_path"]
    srt_path = job["srt_path"]
    try:
        model = _get_model()
        segments, info = model.transcribe(
            mp4_path,
            language="zh",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                f.write(f"{i}\n")
                f.write(f"{_fmt_ts(seg.start)} --> {_fmt_ts(seg.end)}\n")
                f.write(f"{seg.text.strip()}\n\n")
        job["status"] = "done"
        _db_update_job(job_id, "done")
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        _db_update_job(job_id, "error", str(e))


async def _run_with_lock(job_id: str):
    async with _gpu_sem:
        await asyncio.to_thread(_do_transcribe, job_id)


# ── NVENC clip pipeline ───────────────────────────────────────────────────────

async def _run_ffmpeg(*cmd) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 and stderr:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "ffmpeg failed rc=%d: %s", proc.returncode,
            stderr[-1000:].decode("utf-8", errors="replace")
        )
    return proc.returncode


async def _nvenc_xfade_merge(seg_files_with_dur: list, out_dir: str):
    """
    Tree-based sequential xfade merge using NVENC.
    seg_files_with_dur: list of (path, duration_seconds)
    Returns path to merged file, or None on failure.
    """
    if not seg_files_with_dur:
        return None
    if len(seg_files_with_dur) == 1:
        return seg_files_with_dur[0][0]

    _counter = [0]

    async def _merge2(f1: str, d1: float, f2: str, d2: float, dst: str):
        off = max(0.0, d1 - CLIP_FADE)
        rc = await _run_ffmpeg(
            "ffmpeg", "-y", "-i", f1, "-i", f2,
            "-filter_complex",
            f"[0:v]settb=1/25[va];[1:v]settb=1/25[vb];"
            f"[va][vb]xfade=transition=dissolve:duration={CLIP_FADE}:offset={off:.3f}[vout];"
            f"[0:a][1:a]acrossfade=d={CLIP_FADE}[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_nvenc", "-b:v", "8M",
            "-c:a", "aac", "-b:a", "128k",
            dst,
        )
        return rc == 0, d1 - CLIP_FADE + d2

    chunks = list(seg_files_with_dur)  # [(path, duration), ...]
    temp_files = set()

    while len(chunks) > 1:
        next_chunks = []
        for i in range(0, len(chunks), 2):
            if i + 1 >= len(chunks):
                next_chunks.append(chunks[i])
            else:
                _counter[0] += 1
                dst = os.path.join(out_dir, f"tree_{_counter[0]}.mp4")
                ok, new_dur = await _merge2(chunks[i][0], chunks[i][1],
                                             chunks[i+1][0], chunks[i+1][1], dst)
                # Clean up inputs that are temp intermediate files
                for f, _ in (chunks[i], chunks[i+1]):
                    if f in temp_files:
                        try:
                            os.remove(f)
                        except Exception:
                            pass
                if not ok:
                    return None
                temp_files.add(dst)
                next_chunks.append((dst, new_dur))
        chunks = next_chunks

    return chunks[0][0] if chunks else None


async def _do_clip_job(job_id: str, mp4_path: str, segments: list, ass_content: str, thumb_seek: float):
    """Full NVENC clip pipeline: preprocess → xfade merge → subtitle burn → thumbnail."""
    out_dir = os.path.join(STORAGE_DIR, "clips", job_id)
    os.makedirs(out_dir, exist_ok=True)

    try:
        _update_clip_job(job_id, status="processing", phase="preprocess", pct=0)

        # Write ASS subtitle file
        ass_path = os.path.join(out_dir, "subs.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        has_subs = "Dialogue:" in ass_content

        n = len(segments)
        _SF = (
            f"scale={CLIP_W}:{CLIP_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={CLIP_W}:{CLIP_H}:(ow-iw)/2:(oh-ih)/2,"
            f"unsharp=5:5:0.6:5:5:0.0"
        )

        # ── Phase 1: preprocess each segment ──────────────────────────────────
        seg_files_with_dur = []
        for i, seg in enumerate(segments):
            seg_out = os.path.join(out_dir, f"seg{i}.mp4")
            start = float(seg["start"])
            end   = float(seg["end"])
            dur   = end - start

            pad_b       = min(SEG_PAD, start)
            pad_a       = SEG_PAD
            audio_start = start - pad_b
            padded_dur  = dur + pad_b + pad_a
            pre         = max(0.0, audio_start - 3.0)
            fs          = audio_start - pre
            fe          = fs + padded_dur

            af = (
                f"atrim={fs:.3f}:{fe:.3f},asetpts=PTS-STARTPTS,"
                "highpass=f=100,"
                "afftdn=nf=-40:nt=w,"
                "anlmdn=s=7:p=0.002:r=0.002:m=15"
            )
            vf = f"trim={fs:.3f}:{fe:.3f},setpts=PTS-STARTPTS,{_SF},fps=25"

            rc = await _run_ffmpeg(
                "ffmpeg", "-y",
                "-ss", f"{pre:.3f}", "-i", mp4_path,
                "-vf", vf, "-af", af,
                "-t", f"{padded_dur + 0.1:.3f}",
                "-c:v", "h264_nvenc", "-b:v", "10M",
                "-c:a", "aac", "-b:a", "128k",
                seg_out,
            )
            if rc != 0 or not os.path.exists(seg_out):
                raise RuntimeError(f"Segment {i} pre-encode failed (rc={rc})")

            seg_files_with_dur.append((seg_out, padded_dur))
            _update_clip_job(job_id, pct=int((i + 1) / n * 40))

        # ── Phase 2: xfade tree merge ──────────────────────────────────────────
        _update_clip_job(job_id, phase="merge", pct=40)
        merged = await _nvenc_xfade_merge(seg_files_with_dur, out_dir)
        if not merged or not os.path.exists(merged):
            raise RuntimeError("xfade merge failed")
        _update_clip_job(job_id, pct=75)

        # ── Phase 3: final encode – subtitle burn + audio normalise ───────────
        _update_clip_job(job_id, phase="final", pct=75)
        final_out = os.path.join(out_dir, "clip.mp4")

        audio_filter = (
            "[0:a]acompressor=threshold=-25dB:ratio=3:attack=5:release=100:makeup=4dB,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"
        )

        if has_subs:
            # Windows path fix: forward slashes + escape drive colon for ffmpeg filter parser
            fwd = ass_path.replace("\\", "/")
            escaped = fwd[:1] + "\\:" + fwd[2:]  # "C:/..." → "C\:/..."
            video_filter = f"[0:v]ass='{escaped}'[vout]"
            filter_complex = f"{audio_filter};{video_filter}"
            vmap, amap = "[vout]", "[aout]"
        else:
            filter_complex = audio_filter
            vmap, amap = "0:v", "[aout]"

        rc = await _run_ffmpeg(
            "ffmpeg", "-y", "-i", merged,
            "-filter_complex", filter_complex,
            "-map", vmap, "-map", amap,
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_nvenc", "-b:v", "10M",
            "-ar", "44100", "-ac", "2",
            "-c:a", "aac", "-b:a", "192k",
            final_out,
        )
        if rc != 0 or not os.path.exists(final_out):
            raise RuntimeError(f"Final encode failed (rc={rc})")

        # ── Phase 4: extract thumbnail frame ──────────────────────────────────
        _update_clip_job(job_id, phase="thumbnail", pct=90)
        thumb_out = os.path.join(out_dir, "thumb.jpg")
        await _run_ffmpeg(
            "ffmpeg", "-y",
            "-ss", f"{max(1.0, thumb_seek):.3f}", "-i", mp4_path,
            "-frames:v", "1",
            "-vf", f"scale={CLIP_W}:{CLIP_H}:force_original_aspect_ratio=decrease,"
                   f"pad={CLIP_W}:{CLIP_H}:(ow-iw)/2:(oh-ih)/2",
            "-q:v", "2", thumb_out,
        )
        thumb_path = thumb_out if os.path.exists(thumb_out) and os.path.getsize(thumb_out) > 0 else None

        _update_clip_job(
            job_id,
            status="done", phase="done", pct=100,
            output_path=final_out,
            thumb_path=thumb_path or "",
        )

    except Exception as e:
        _update_clip_job(job_id, status="error", error=str(e))


async def _run_clip_job(job_id: str, mp4_path: str, segments: list, ass_content: str, thumb_seek: float):
    async with _clip_sem:
        await _do_clip_job(job_id, mp4_path, segments, ass_content, thumb_seek)


# ── Startup ───────────────────────────────────────────────────────────────────

_init_db()
_jobs = _load_jobs()
_clip_jobs = _load_clip_jobs()

app = FastAPI(title="Douyin GPU Service")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    _w = getattr(_gpu_sem, "_waiters", None)
    queued = max(0, len(_w) if _w else 0)
    clip_running = sum(1 for j in _clip_jobs.values() if j.get("status") == "processing")
    return {
        "status": "ok",
        "jobs": len(_jobs),
        "gpu_busy": _gpu_sem.locked(),
        "queue_depth": queued,
        "clip_jobs_running": clip_running,
    }


# ── Transcription endpoints ───────────────────────────────────────────────────

@app.post("/jobs", status_code=201)
async def create_job(
    file: UploadFile = File(...),
    room_id: int = Form(...),
):
    """Receive MP4 file and start transcription."""
    job_id = os.path.splitext(file.filename)[0]
    room_dir = os.path.join(STORAGE_DIR, str(room_id))
    os.makedirs(room_dir, exist_ok=True)

    mp4_path = os.path.join(room_dir, file.filename)
    srt_path = os.path.join(room_dir, job_id + ".srt")

    async with aiofiles.open(mp4_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            await f.write(chunk)

    _jobs[job_id] = {"status": "processing", "mp4_path": mp4_path, "srt_path": srt_path, "error": None}
    _db_insert_job(job_id, mp4_path, srt_path)
    asyncio.create_task(_run_with_lock(job_id))
    return {"job_id": job_id, "status": "processing"}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": job["status"], "error": job.get("error")}


@app.get("/jobs/{job_id}/srt")
async def get_srt(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=404, detail="SRT not ready")
    srt_path = job["srt_path"]
    if not os.path.exists(srt_path):
        raise HTTPException(status_code=404, detail="SRT file missing on disk")
    return FileResponse(srt_path, media_type="text/plain; charset=utf-8",
                        filename=os.path.basename(srt_path))


# ── Clip job endpoints ────────────────────────────────────────────────────────

class ClipJobRequest(BaseModel):
    mp4_filename: str   # filename only — file already at STORAGE_DIR/{room_id}/{mp4_filename}
    room_id: int
    segments: list      # [{start: float, end: float}, ...]
    ass_content: str    # ASS subtitle content (empty string if none)
    thumb_seek: float = 5.0  # timestamp in original mp4 for thumbnail frame


@app.post("/clip-jobs", status_code=201)
async def create_clip_job(req: ClipJobRequest):
    mp4_path = os.path.join(STORAGE_DIR, str(req.room_id), req.mp4_filename)
    if not os.path.exists(mp4_path):
        raise HTTPException(status_code=404, detail=f"MP4 not found on server: {mp4_path}")
    if not req.segments:
        raise HTTPException(status_code=422, detail="segments list is empty")

    job_id = uuid.uuid4().hex[:16]
    _clip_jobs[job_id] = {
        "status": "queued", "phase": "queued", "pct": 0,
        "error": None, "output_path": None, "thumb_path": None,
    }
    _db_insert_clip_job(job_id)
    asyncio.create_task(_run_clip_job(job_id, mp4_path, req.segments, req.ass_content, req.thumb_seek))
    return {"job_id": job_id, "status": "queued"}


@app.get("/clip-jobs/{job_id}")
async def get_clip_job(job_id: str):
    job = _clip_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Clip job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "phase": job.get("phase"),
        "pct": job.get("pct", 0),
        "error": job.get("error"),
    }


@app.get("/clip-jobs/{job_id}/mp4")
async def get_clip_mp4(job_id: str):
    job = _clip_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Clip job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Clip not ready (status={job['status']})")
    path = job.get("output_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Output file missing")
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}_clip.mp4")


@app.get("/clip-jobs/{job_id}/thumb")
async def get_clip_thumb(job_id: str):
    job = _clip_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Clip job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Clip not ready")
    path = job.get("thumb_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    return FileResponse(path, media_type="image/jpeg", filename=f"{job_id}_thumb.jpg")


# ── Background removal endpoint ───────────────────────────────────────────────

@app.post("/rembg")
async def remove_background(file: UploadFile = File(...)):
    """Accept JPEG/PNG image, return PNG with background removed (CUDA U2Net)."""
    try:
        import rembg
    except ImportError:
        raise HTTPException(status_code=503, detail="rembg not installed on GPU server")

    data = await file.read()
    try:
        result = await asyncio.to_thread(rembg.remove, data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"rembg failed: {e}")

    return Response(content=result, media_type="image/png")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8877"))
    uvicorn.run(app, host="0.0.0.0", port=port)
