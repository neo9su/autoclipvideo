"""
Douyin GPU Transcription Service
Run on GPU server: uvicorn main:app --host 0.0.0.0 --port 8877
"""
import asyncio
import os
import sqlite3

import aiofiles
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

STORAGE_DIR = os.environ.get("STORAGE_DIR", "/data/douyin-recordings")
os.makedirs(STORAGE_DIR, exist_ok=True)

DB_PATH = os.path.join(STORAGE_DIR, "jobs.db")

# In-memory job store: job_id -> {status, mp4_path, srt_path, error}
_jobs: dict = {}
_model = None  # Singleton WhisperModel


def _init_db():
    """Create jobs table and reset any interrupted jobs from a previous run."""
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
        # Jobs that were processing when the service last died will never complete — mark as error
        conn.execute(
            "UPDATE jobs SET status = 'error', error = 'service restarted' WHERE status = 'processing'"
        )
        conn.commit()


def _load_jobs() -> dict:
    """Restore job state from DB into memory."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs").fetchall()
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
    """Blocking transcription — runs in a thread pool."""
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


_init_db()
_jobs = _load_jobs()

app = FastAPI(title="Douyin GPU Transcription Service")


@app.get("/health")
async def health():
    return {"status": "ok", "jobs": len(_jobs)}


@app.post("/jobs", status_code=201)
async def create_job(
    file: UploadFile = File(...),
    room_id: int = Form(...),
):
    """Receive MP4 file and start transcription immediately."""
    job_id = os.path.splitext(file.filename)[0]
    room_dir = os.path.join(STORAGE_DIR, str(room_id))
    os.makedirs(room_dir, exist_ok=True)

    mp4_path = os.path.join(room_dir, file.filename)
    srt_path = os.path.join(room_dir, job_id + ".srt")

    # Save uploaded file in chunks
    async with aiofiles.open(mp4_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 1 MB chunks
            await f.write(chunk)

    _jobs[job_id] = {
        "status": "processing",
        "mp4_path": mp4_path,
        "srt_path": srt_path,
        "error": None,
    }
    _db_insert_job(job_id, mp4_path, srt_path)

    asyncio.create_task(asyncio.to_thread(_do_transcribe, job_id))
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
    return FileResponse(
        srt_path,
        media_type="text/plain; charset=utf-8",
        filename=os.path.basename(srt_path),
    )
