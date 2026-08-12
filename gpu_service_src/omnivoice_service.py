"""
OmniVoice TTS Service — FastAPI wrapper around k2-fsa/OmniVoice.

Run on GPU server:
    python omnivoice_service.py --port 8879

API endpoints:
    POST /tts-jobs          Create TTS job
    GET  /tts-jobs/{id}     Get job status
    GET  /tts-jobs/{id}/audio  Get audio output
    POST /voice-refs        Create voice reference
    GET  /voice-refs        List voice references
    GET  /health            Health check
"""

import argparse
import asyncio
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Try to import OmniVoice
try:
    from omnivoice import OmniVoice
except ImportError:
    OmniVoice = None

# ── Config ────────────────────────────────────────────────────────────────────
STORAGE_DIR = os.environ.get("STORAGE_DIR", r"C:\Users\neo\douyin_recordings")
MODEL_DIR = os.environ.get("MODEL_DIR", os.environ.get("COSYVOICE_MODEL_DIR", ""))
PORT = int(os.environ.get("OMNIVOICE_PORT", "8879"))

os.makedirs(os.path.join(STORAGE_DIR, "tts_outputs"), exist_ok=True)
os.makedirs(os.path.join(STORAGE_DIR, "voice_refs"), exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("omnivoice")

# ── Global state ──────────────────────────────────────────────────────────────
_jobs: dict = {}
_voice_refs: dict = {}
_model = None
_db_path = os.path.join(STORAGE_DIR, "omnivoice_jobs.db")


# ── DB helpers ────────────────────────────────────────────────────────────────
def _init_db():
    conn = sqlite3.connect(_db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tts_jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'queued',
            text TEXT,
            ref_voice_id TEXT,
            output_path TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS voice_refs (
            ref_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'queued',
            wav_path TEXT,
            transcript TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()


def _db_insert_job(job_id: str):
    conn = sqlite3.connect(_db_path)
    conn.execute(
        "INSERT OR REPLACE INTO tts_jobs (job_id, status) VALUES (?, 'queued')",
        (job_id,),
    )
    conn.commit()
    conn.close()


def _db_update_job(job_id: str, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    conn = sqlite3.connect(_db_path)
    conn.execute(f"UPDATE tts_jobs SET {sets} WHERE job_id = ?", vals)
    conn.commit()
    conn.close()


# ── Model loading ─────────────────────────────────────────────────────────────
def _load_model():
    global _model
    if _model is not None:
        return _model
    if OmniVoice is None:
        raise RuntimeError("OmniVoice not installed. Run: pip install omnivoice")
    logger.info("Loading OmniVoice model...")
    _model = OmniVoice.from_pretrained(
        "k2-fsa/OmniVoice",
        device_map="cuda:0",
        dtype=torch.float16,
    )
    logger.info("OmniVoice model loaded")
    return _model


# ── TTS synthesis ─────────────────────────────────────────────────────────────
def _synth_audio(job_id: str, text: str, ref_voice_id: str = ""):
    _db_update_job(job_id, status="processing")
    out_dir = os.path.join(STORAGE_DIR, "tts_outputs", job_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{job_id}.wav")

    try:
        model = _load_model()

        # Resolve reference audio
        ref_audio = None
        ref_text = ""
        if ref_voice_id:
            ref = _voice_refs.get(ref_voice_id)
            if ref and ref.get("status") == "done":
                ref_audio = ref.get("wav_path")
                ref_text = ref.get("transcript", "")

        # Generate audio
        audio = model.generate(
            text=text,
            ref_audio=ref_audio,
            ref_text=ref_text,
        )

        # Save audio
        import soundfile as sf
        if isinstance(audio, list):
            audio = audio[0] if audio else None
        if audio is None:
            raise RuntimeError("OmniVoice returned no audio")
        sf.write(out_path, audio, 24000)

        _db_update_job(job_id, status="done", output_path=out_path)
        logger.info(f"TTS job {job_id} done ({os.path.getsize(out_path)//1024} KB)")

    except Exception as e:
        logger.error(f"TTS job {job_id} failed: {e}")
        _db_update_job(job_id, status="error", error=str(e))


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="OmniVoice TTS Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSJobRequest(BaseModel):
    text: str
    ref_voice_id: str = ""


@app.on_event("startup")
async def startup():
    _init_db()
    # Load existing jobs from DB
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM tts_jobs").fetchall()
    for row in rows:
        _jobs[row["job_id"]] = {
            "status": row["status"],
            "output_path": row["output_path"],
            "error": row["error"],
        }
    conn.close()
    logger.info(f"OmniVoice TTS Service started on port {PORT}")


@app.get("/health")
async def health():
    model_loaded = _model is not None
    return {
        "status": "ok",
        "model_loaded": model_loaded,
        "jobs": len(_jobs),
    }


@app.post("/tts-jobs", status_code=201)
async def create_tts_job(req: TTSJobRequest):
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="text is empty")

    job_id = uuid.uuid4().hex[:16]
    _jobs[job_id] = {"status": "queued", "output_path": None, "error": None}
    _db_insert_job(job_id)

    asyncio.create_task(_synth_audio(job_id, req.text.strip(), req.ref_voice_id))
    return {"job_id": job_id, "status": "queued"}


@app.get("/tts-jobs/{job_id}")
async def get_tts_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        # Check DB
        conn = sqlite3.connect(_db_path)
        row = conn.execute("SELECT * FROM tts_jobs WHERE job_id = ?", (job_id,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"job_id": job_id, "status": row["status"], "error": row["error"]}
    return {"job_id": job_id, "status": job["status"], "error": job.get("error")}


@app.get("/tts-jobs/{job_id}/audio")
async def get_tts_audio(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"TTS not ready (status={job['status']})")
    path = job.get("output_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Audio file missing")
    return FileResponse(path, media_type="audio/wav", filename=f"{job_id}.wav")


@app.get("/jobs")
async def list_jobs():
    return {"jobs": list(_jobs.keys()), "count": len(_jobs)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OmniVoice TTS Service")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)
