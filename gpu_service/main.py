"""
Douyin GPU Transcription + Clip Service
Run on GPU server: uvicorn main:app --host 0.0.0.0 --port 8877
"""
# Set HuggingFace offline flags BEFORE any imports so huggingface_hub.constants
# reads them at import time and never attempts network access.
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HUGGINGFACE_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
# ModelScope offline — prevents wetext/tokenizer revision checks on every startup
os.environ.setdefault("MODELSCOPE_OFFLINE", "1")
os.environ.setdefault("MS_OFFLINE", "1")

import asyncio
import logging
import sqlite3
import subprocess
import time
import uuid
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

import aiofiles
import torchaudio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import shutil as _shutil

_DEFAULT_STORAGE = (
    r"C:\Users\neo\douyin_recordings" if os.name == "nt" else "/data/douyin-recordings"
)
STORAGE_DIR = os.environ.get("STORAGE_DIR", _DEFAULT_STORAGE)
os.makedirs(STORAGE_DIR, exist_ok=True)

DB_PATH = os.path.join(STORAGE_DIR, "jobs.db")

# ffmpeg binary with libass support (needed for subtitle burn-in).
# On Windows, the conda/miniconda ffmpeg often lacks libass; prefer the
# Chocolatey-installed build which is compiled with --enable-libass.
_CHOCO_FFMPEG = r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"
FFMPEG_ASS = _CHOCO_FFMPEG if os.name == "nt" else (_shutil.which("ffmpeg") or "ffmpeg")

# Falls back to the known location inside STORAGE_DIR/fonts.
_DEFAULT_FONTS_DIR = os.path.join(_DEFAULT_STORAGE, "fonts")
FONTS_DIR = os.environ.get("FONTS_DIR", _DEFAULT_FONTS_DIR if os.path.isdir(_DEFAULT_FONTS_DIR) else "")

# CosyVoice2 model directory.
# ModelScope downloads to models/iic/CosyVoice2-0.5B (with symlink).
# HuggingFace downloads to models/CosyVoice2-0.5B.
# Check both; override via env var COSYVOICE_MODEL_DIR.
def _default_cosy_dir():
    base = os.path.join(STORAGE_DIR, "models")
    for sub in ["iic/CosyVoice2-0.5B", "CosyVoice2-0.5B"]:
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            return p
    return os.path.join(base, "iic", "CosyVoice2-0.5B")

COSYVOICE_MODEL_DIR = os.environ.get("COSYVOICE_MODEL_DIR", _default_cosy_dir())

# ── In-memory stores ──────────────────────────────────────────────────────────
_jobs: dict = {}        # transcription jobs
_clip_jobs: dict = {}   # clip jobs
_tts_jobs: dict = {}    # TTS synthesis jobs
_voice_refs: dict = {}  # lightweight voice reference extractions
_model = None           # Singleton WhisperModel
_cosyvoice = None       # Singleton CosyVoice2 model

# GPU concurrency: one transcription at a time (shares VRAM with ComfyUI)
_gpu_sem: asyncio.Semaphore = asyncio.Semaphore(1)
# NVENC concurrency: 2 concurrent — NVENC is a dedicated hardware unit, no VRAM cost
_clip_sem: asyncio.Semaphore = asyncio.Semaphore(2)

# ── Clip pipeline constants ───────────────────────────────────────────────────
CLIP_W    = 1080
CLIP_H    = 1920
CLIP_FADE = 1.5   # xfade duration (seconds)
SEG_PAD   = 0.0   # no padding — avoids duplicate audio at segment boundaries


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tts_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'queued',
                output_path TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "UPDATE tts_jobs SET status = 'error', error = 'service restarted' WHERE status IN ('queued', 'processing')"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS concat_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'queued',
                output_path TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "UPDATE concat_jobs SET status = 'error', error = 'service restarted' WHERE status IN ('queued', 'processing')"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS voice_refs (
                ref_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'queued',
                wav_path TEXT,
                transcript TEXT,
                error TEXT,
                room_id INTEGER,
                label TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Migrate: add columns missing from older databases
        for col, typedef in [("transcript", "TEXT"), ("room_id", "INTEGER"), ("label", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE voice_refs ADD COLUMN {col} {typedef}")
            except Exception:
                pass
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


def _load_tts_jobs() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tts_jobs").fetchall()
    return {r["job_id"]: dict(r) for r in rows}


def _load_voice_refs() -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM voice_refs").fetchall()
    result = {}
    for r in rows:
        d = dict(r)
        d.setdefault("room_id", None)
        d.setdefault("label", "")
        result[r["ref_id"]] = d
    return result


def _db_insert_voice_ref(ref_id: str, room_id: int = None, label: str = None):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO voice_refs (ref_id, status, room_id, label) VALUES (?, 'queued', ?, ?)",
            (ref_id, room_id, label),
        )
        conn.commit()


def _get_room_voice_ref(room_id: int) -> dict | None:
    """Return the most recent done voice_ref for a room, or None."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM voice_refs WHERE room_id=? AND status='done' ORDER BY created_at DESC LIMIT 1",
            (room_id,),
        ).fetchone()
    return dict(row) if row else None


def _db_update_voice_ref(ref_id: str, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [ref_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE voice_refs SET {sets} WHERE ref_id = ?", vals)
        conn.commit()


def _db_insert_tts_job(job_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tts_jobs (job_id, status) VALUES (?, 'queued')",
            (job_id,),
        )
        conn.commit()


def _db_update_tts_job(job_id: str, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE tts_jobs SET {sets} WHERE job_id = ?", vals)
        conn.commit()


def _db_insert_job(job_id: str, mp4_path: str, srt_path: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO jobs (job_id, mp4_path, srt_path, status) VALUES (?, ?, ?, 'processing')",
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


def _db_insert_concat_job(job_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO concat_jobs (job_id, status) VALUES (?, 'queued')",
            (job_id,),
        )
        conn.commit()


def _db_update_concat_job(job_id: str, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE concat_jobs SET {sets} WHERE job_id = ?", vals)
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
            vad_parameters={
                "threshold": 0.3,              # more sensitive — catches speech under background music
                "min_silence_duration_ms": 300, # shorter gap needed to split segments
                "speech_pad_ms": 400,
            },
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

async def _has_audio_stream(path: str) -> bool:
    """Return True if the file contains at least one audio stream."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return bool(stdout.strip())


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


_VALID_XFADE_CLASSIC = {
    "dissolve", "fadeblack", "fadewhite", "fadegrays",
    "slideleft", "slideright", "smoothleft", "smoothright",
    "wipeleft", "wiperight", "wipeup", "wipedown",
    "zoomin", "radial", "hblur", "squeezeh", "squeezev",
    "diagtl", "diagtr", "pixelize",
}


async def _nvenc_xfade_merge(seg_files_with_dur: list, out_dir: str):
    """
    Sequential xfade merge using NVENC.
    seg_files_with_dur: list of (path, duration_seconds, transition, transition_duration)
    transition/transition_duration are optional (defaults: slideleft/0.35).
    Returns path to merged file, or None on failure.
    """
    if not seg_files_with_dur:
        return None
    if len(seg_files_with_dur) == 1:
        return seg_files_with_dur[0][0]

    _counter = [0]

    async def _merge2(f1: str, d1: float, f2: str, d2: float, dst: str,
                      tr: str = "slideleft", tr_dur: float = 0.35):
        fade = max(0.1, min(tr_dur, 1.0))
        tr_used = tr if tr in _VALID_XFADE_CLASSIC else "slideleft"
        off = max(0.0, d1 - fade)
        ha1, ha2 = await asyncio.gather(_has_audio_stream(f1), _has_audio_stream(f2))

        vf = (f"[0:v]settb=1/25[va];[1:v]settb=1/25[vb];"
              f"[va][vb]xfade=transition={tr_used}:duration={fade}:offset={off:.3f}[vout]")

        if ha1 and ha2:
            fc = vf + f";[0:a][1:a]acrossfade=d={fade}[aout]"
            maps = ["-map", "[vout]", "-map", "[aout]"]
            aargs = ["-c:a", "aac", "-b:a", "128k"]
        elif ha1:
            fc = vf
            maps = ["-map", "[vout]", "-map", "0:a"]
            aargs = ["-c:a", "aac", "-b:a", "128k"]
        elif ha2:
            fc = vf
            maps = ["-map", "[vout]", "-map", "1:a"]
            aargs = ["-c:a", "aac", "-b:a", "128k"]
        else:
            fc = vf
            maps = ["-map", "[vout]"]
            aargs = ["-an"]

        rc = await _run_ffmpeg(
            "ffmpeg", "-y", "-i", f1, "-i", f2,
            "-filter_complex", fc,
            *maps,
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_nvenc", "-b:v", "8M",
            *aargs,
            dst,
        )
        return rc == 0, d1 - fade + d2

    # Normalize to 4-tuples: (path, duration, transition, tr_dur)
    chunks = []
    for item in seg_files_with_dur:
        if len(item) == 4:
            chunks.append(item)
        elif len(item) == 3:
            chunks.append((item[0], item[1], item[2], 0.35))
        else:
            chunks.append((item[0], item[1], "slideleft", 0.35))

    temp_files = set()
    _counter = [0]

    while len(chunks) > 1:
        next_chunks = []
        for i in range(0, len(chunks), 2):
            if i + 1 >= len(chunks):
                next_chunks.append(chunks[i])
            else:
                _counter[0] += 1
                dst = os.path.join(out_dir, f"tree_{_counter[0]}.mp4")
                # Use the transition assigned to segment i+1 (the incoming clip)
                _, _, tr, tr_dur = chunks[i + 1]
                ok, new_dur = await _merge2(
                    chunks[i][0], chunks[i][1],
                    chunks[i+1][0], chunks[i+1][1],
                    dst, tr, tr_dur,
                )
                for f, *_ in (chunks[i], chunks[i+1]):
                    if f in temp_files:
                        try:
                            os.remove(f)
                        except Exception:
                            pass
                if not ok:
                    return None
                temp_files.add(dst)
                next_chunks.append((dst, new_dur, tr, tr_dur))
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

            tr = str(seg.get("transition", "slideleft"))
            tr_dur = float(seg.get("transition_duration", 0.35))
            seg_files_with_dur.append((seg_out, padded_dur, tr, tr_dur))
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
            if FONTS_DIR:
                fonts_fwd = FONTS_DIR.replace("\\", "/")
                # Escape drive colon for FFmpeg filter string (Windows: "D:/..." → "D\:/...")
                if len(fonts_fwd) > 1 and fonts_fwd[1] == ":":
                    fonts_escaped = fonts_fwd[0] + "\\:" + fonts_fwd[2:]
                else:
                    fonts_escaped = fonts_fwd
                video_filter = f"[0:v]ass=filename='{escaped}':fontsdir='{fonts_escaped}',format=yuv420p[vout]"
            else:
                video_filter = f"[0:v]ass=filename='{escaped}',format=yuv420p[vout]"
            filter_complex = f"{audio_filter};{video_filter}"
            vmap, amap = "[vout]", "[aout]"
        else:
            filter_complex = audio_filter
            vmap, amap = "0:v", "[aout]"

        rc = await _run_ffmpeg(
            FFMPEG_ASS, "-y", "-i", merged,
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


# ── Concat-merge job (stream-copy, no re-encode) ──────────────────────────────

_concat_jobs: dict = {}
_concat_sem: asyncio.Semaphore = asyncio.Semaphore(1)


class ConcatJobRequest(BaseModel):
    clip_job_ids: list[str]   # ordered list of clip_job_ids whose output.mp4 to join


async def _do_concat_job(job_id: str, clip_job_ids: list):
    out_dir = os.path.join(STORAGE_DIR, "concat", job_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "merged.mp4")
    list_file = os.path.join(out_dir, "list.txt")
    try:
        # Gather source paths
        sources = []
        for cjid in clip_job_ids:
            job = _clip_jobs.get(cjid)
            if not job or job.get("status") != "done":
                raise ValueError(f"Clip job {cjid} not done (status={job.get('status') if job else 'missing'})")
            p = job.get("output_path")
            if not p or not os.path.exists(p):
                raise ValueError(f"Clip job {cjid} output missing: {p}")
            sources.append(p)

        if not sources:
            raise ValueError("No valid source clips")

        with open(list_file, "w", encoding="utf-8") as f:
            for p in sources:
                f.write(f"file '{p}'\n")

        rc = await _run_ffmpeg(
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            out_path,
        )
        if rc != 0 or not os.path.exists(out_path):
            raise RuntimeError("ffmpeg concat failed")

        _concat_jobs[job_id]["status"] = "done"
        _concat_jobs[job_id]["output_path"] = out_path
        _db_update_concat_job(job_id, status="done", output_path=out_path)
    except Exception as e:
        _concat_jobs[job_id]["status"] = "error"
        _concat_jobs[job_id]["error"] = str(e)
        _db_update_concat_job(job_id, status="error", error=str(e))
    finally:
        try:
            os.remove(list_file)
        except Exception:
            pass


async def _run_concat_job(job_id: str, clip_job_ids: list):
    async with _concat_sem:
        await _do_concat_job(job_id, clip_job_ids)


# ── CosyVoice2 TTS ───────────────────────────────────────────────────────────

import logging as _logging
_log = _logging.getLogger(__name__)

# TTS concurrency: serialised — shares VRAM with Whisper
_tts_sem: asyncio.Semaphore = asyncio.Semaphore(1)

# Emotion → instruct text mapping for inference_instruct2 mode
_EMOTION_INSTRUCT: dict = {
    "excited":      "用热情洋溢、充满活力的声音说，语速稍快，充满感染力",
    "warm":         "用温柔亲切、自然流畅的声音说，如朋友间娓娓道来",
    "clear":        "用清晰标准、专业自信的声音说，吐字清晰有力",
    "natural":      "用自然流畅、轻松愉快的声音说，语气随和",
    "persuasive":   "用亲切有说服力、富有感染力的声音说，语气诚恳",
    "urgent":       "用紧迫感十足、语速加快的声音说，制造稀缺感和冲动感",
    "confident":    "用自信笃定、从容不迫的声音说，让人信服",
    "emotional":    "用饱含情感、真诚动人的声音说，声音微带感动",
    "storytelling": "用娓娓道来、有画面感的声音说，像在讲一个故事",
    "luxury":       "用优雅从容、低调奢华的声音说，语速舒缓，气质感十足",
}

# Default reference audio: bundled CosyVoice asset (Chinese female).
_COSYVOICE_REPO = os.environ.get(
    "COSYVOICE_REPO",
    r"C:\Users\neo\CosyVoice" if os.name == "nt" else "/opt/CosyVoice",
)
_DEFAULT_REF_AUDIO = os.path.join(_COSYVOICE_REPO, "asset", "zero_shot_prompt.wav")


def _get_cosyvoice():
    global _cosyvoice
    if _cosyvoice is None:
        import sys as _sys
        # Matcha-TTS must be on sys.path for CosyVoice2 flow model to import correctly.
        # Without it the flow model silently degrades and produces unintelligible audio.
        _matcha = r'C:\Users\neo\CosyVoice\third_party\Matcha-TTS'
        _cosy_root = r'C:\Users\neo\CosyVoice'
        for _p in (_cosy_root, _matcha):
            if os.path.isdir(_p) and _p not in _sys.path:
                _sys.path.insert(0, _p)
        from cosyvoice.cli.cosyvoice import CosyVoice2
        if not os.path.isdir(COSYVOICE_MODEL_DIR):
            raise FileNotFoundError(
                f"CosyVoice2 model not found at {COSYVOICE_MODEL_DIR}."
            )
        # fp16=False: keep autocast disabled so all models run in their native dtypes.
        # Root cause of "gu lulu" audio was in Qwen2Encoder.forward_one_step: it passed
        # attention_mask=(1,1) on every cached step, but transformers 5.x DynamicCache+SDPA
        # requires the FULL history mask (1, past_len+1).  The fix is in llm.py
        # (forward_one_step extends the mask when cache is present).
        _cosyvoice = CosyVoice2(COSYVOICE_MODEL_DIR, load_jit=False, load_trt=False, fp16=False)
        _log.warning("CosyVoice2 model loaded")
    return _cosyvoice


def _synth_audio(text: str, emotion: str, ref_audio_path: str, out_path: str, prompt_text: str = "", sft_spk: str = ""):
    """Blocking TTS synthesis via CosyVoice2 — run in a thread via asyncio.to_thread.

    Mode selection:
    - sft_spk provided → inference_sft (built-in speaker, no ref needed)
    - ref_audio_path provided → inference_zero_shot (full voice cloning: ref speech
      tokens feed the LLM AND ref mel features guide the flow model)
    - no ref → inference_instruct2 with default ref (no cloning, just intelligible TTS)
    """
    import torch
    model = _get_cosyvoice()

    # ── SFT mode: use a built-in speaker, no reference audio needed ───────────
    if sft_spk.strip():
        spk = sft_spk.strip()
        _log.info("_synth_audio: sft mode, speaker=%r", spk)
        results = list(model.inference_sft(text, spk, stream=False))
    elif ref_audio_path and os.path.isfile(ref_audio_path):
        # ── Zero-shot mode: full voice cloning from reference audio ───────────
        # LLM sees speech tokens extracted from the reference (via ONNX tokenizer on CPU)
        # AND the flow model uses reference mel features — strongest voice match.
        _log.info("_synth_audio: zero_shot mode, ref=%r, prompt_text=%r",
                  ref_audio_path, (prompt_text or "")[:40])
        results = list(model.inference_zero_shot(text, prompt_text or "", ref_audio_path, stream=False))
    else:
        # ── Instruct2 fallback: no valid reference, use default wav ───────────
        ref = _DEFAULT_REF_AUDIO
        if not os.path.isfile(ref):
            raise FileNotFoundError(f"No reference audio available (default: {ref!r}).")
        instruct_text = _EMOTION_INSTRUCT.get(emotion, _EMOTION_INSTRUCT["natural"])
        _log.info("_synth_audio: instruct2 fallback, emotion=%r", emotion)
        results = list(model.inference_instruct2(text, instruct_text, ref, stream=False))

    if not results:
        raise RuntimeError("CosyVoice2 returned no audio chunks")

    chunks = [r["tts_speech"] for r in results]
    audio = torch.cat(chunks, dim=1) if len(chunks) > 1 else chunks[0]
    # Save as float32 WAV — matches CosyVoice2 official examples, no conversion needed.
    # torchaudio.save with a float32 tensor writes 32-bit float PCM which is universally supported.
    if audio.dtype != torch.float32:
        audio = audio.float()
    torchaudio.save(out_path, audio, model.sample_rate)


async def _do_tts_job(job_id: str, text: str, emotion: str, ref_audio_path: str, prompt_text: str = "", sft_spk: str = "", speed: float = 1.0):
    _tts_jobs[job_id].update({"status": "processing"})
    _db_update_tts_job(job_id, status="processing")

    out_dir = os.path.join(STORAGE_DIR, "tts_outputs", job_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{job_id}.wav")

    try:
        async with _tts_sem:
            await asyncio.to_thread(_synth_audio, text, emotion, ref_audio_path, out_path, prompt_text, sft_spk)

        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("TTS output file empty or missing")

        # Apply speed ratio via atempo if requested (0.5–2.0 range per ffmpeg filter)
        if abs(speed - 1.0) > 0.05:
            speed = max(0.5, min(4.0, speed))
            fixed_path = out_path + "_fast.wav"
            if speed <= 2.0:
                atempo = f"atempo={speed:.3f}"
            else:
                half = speed ** 0.5
                atempo = f"atempo={half:.3f},atempo={half:.3f}"
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", out_path, "-filter:a", atempo, fixed_path],
                capture_output=True
            )
            if proc.returncode == 0 and os.path.isfile(fixed_path) and os.path.getsize(fixed_path) > 0:
                os.replace(fixed_path, out_path)
                _log.info(f"TTS job {job_id}: speed={speed:.2f}x applied")

        _tts_jobs[job_id].update({"status": "done", "output_path": out_path})
        _db_update_tts_job(job_id, status="done", output_path=out_path)
        _log.info(f"TTS job {job_id} done ({os.path.getsize(out_path)//1024} KB)")
    except Exception as e:
        err = str(e)[:300]
        _log.error(f"TTS job {job_id} failed: {err}")
        _tts_jobs[job_id].update({"status": "error", "error": err})
        _db_update_tts_job(job_id, status="error", error=err)


# ── Startup ───────────────────────────────────────────────────────────────────

_init_db()
_jobs = _load_jobs()
_clip_jobs = _load_clip_jobs()
_tts_jobs = _load_tts_jobs()
_voice_refs = _load_voice_refs()

_JOB_TTL_SECONDS = 24 * 3600  # 24 hours


async def _auto_cleanup_loop():
    """Periodically evict terminal jobs from in-memory dicts (prevent unbounded growth)."""
    import time
    while True:
        await asyncio.sleep(3600)  # run every hour
        now = time.time()
        for store in (_jobs, _clip_jobs, _tts_jobs, _concat_jobs, _classic_concat_jobs):
            expired = [
                jid for jid, j in list(store.items())
                if j.get("status") in ("done", "error")
                and now - j.get("_created_at", now) > _JOB_TTL_SECONDS
            ]
            for jid in expired:
                store.pop(jid, None)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    asyncio.create_task(_auto_cleanup_loop())
    # CosyVoice2 model is loaded lazily on first TTS job (model takes ~30s to load).
    yield


app = FastAPI(title="Douyin GPU Service", lifespan=_lifespan)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    _w = getattr(_gpu_sem, "_waiters", None)
    queued = max(0, len(_w) if _w else 0)
    clip_running = sum(1 for j in _clip_jobs.values() if j.get("status") == "processing")
    clip_pending = sum(1 for j in _clip_jobs.values() if j.get("status") == "queued")
    concat_running = sum(1 for j in _concat_jobs.values() if j.get("status") == "queued")
    classic_concat_running = sum(1 for j in _classic_concat_jobs.values() if j.get("status") in ("queued", "processing"))
    return {
        "status": "ok",
        "jobs": len(_jobs),
        "gpu_busy": _gpu_sem.locked(),
        "queue_depth": queued,
        "clip_jobs_running": clip_running,
        "clip_jobs_pending": clip_pending,
        "concat_jobs_active": concat_running,
        "classic_concat_jobs_active": classic_concat_running,
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


# ── Frame extraction endpoint ─────────────────────────────────────────────────

import base64 as _base64
import tempfile as _tempfile

class FrameExtractRequest(BaseModel):
    timestamps: list  # [float, ...]
    scale: str = "540:960:force_original_aspect_ratio=decrease"

@app.post("/jobs/{job_id}/extract-frames")
async def extract_frames(job_id: str, req: FrameExtractRequest):
    """Extract frames from a transcription job's MP4 at given timestamps.
    Returns base64-encoded JPEGs. Used by the local backend to offload ffmpeg
    frame extraction (for segment scoring) onto the GPU server."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    mp4_path = job["mp4_path"]
    if not os.path.exists(mp4_path):
        raise HTTPException(status_code=404, detail="MP4 not found on disk")

    frames = []
    for ts in req.timestamps:
        fd, tmp = _tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        pre  = max(0.0, float(ts) - 2.0)
        fine = float(ts) - pre
        cmd = [
            "ffmpeg", "-nostdin", "-y",
            "-ss", f"{pre:.3f}", "-i", mp4_path,
            "-ss", f"{fine:.3f}", "-frames:v", "1",
            "-vf", req.scale, "-q:v", "4", tmp,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if proc.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                async with aiofiles.open(tmp, "rb") as f:
                    data = await f.read()
                frames.append(_base64.b64encode(data).decode())
            else:
                frames.append(None)
        except Exception as e:
            logger.warning(f"Frame extract failed for {job_id} at {ts}s: {e}")
            frames.append(None)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    return {"frames": frames}


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
        "_created_at": time.time(),
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


# ── Concat-merge endpoints ────────────────────────────────────────────────────

@app.post("/concat-jobs", status_code=201)
async def create_concat_job(req: ConcatJobRequest):
    if not req.clip_job_ids:
        raise HTTPException(status_code=422, detail="clip_job_ids is empty")
    job_id = uuid.uuid4().hex[:16]
    _concat_jobs[job_id] = {"status": "queued", "output_path": None, "error": None, "_created_at": time.time()}
    _db_insert_concat_job(job_id)
    asyncio.create_task(_run_concat_job(job_id, req.clip_job_ids))
    return {"job_id": job_id, "status": "queued"}


@app.get("/concat-jobs/{job_id}")
async def get_concat_job(job_id: str):
    job = _concat_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Concat job not found")
    return {"job_id": job_id, "status": job["status"], "error": job.get("error")}


@app.get("/concat-jobs/{job_id}/mp4")
async def get_concat_mp4(job_id: str):
    job = _concat_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Concat job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Not ready (status={job['status']})")
    path = job.get("output_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Output file missing")
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}_merged.mp4")


# ── Classic-concat job (upload clips → NVENC re-encode merge) ────────────────
# Mac uploads already-processed clip files; GPU re-encodes with NVENC so the
# output codec is always H.264 regardless of input (VideoToolbox / NVENC mix).

_classic_concat_jobs: dict = {}
_classic_concat_sem: asyncio.Semaphore = asyncio.Semaphore(1)


async def _do_classic_concat_job(job_id: str, clip_paths: list):
    """NVENC linear merge of uploaded clip files (no transitions, no TTS)."""
    out_dir = os.path.join(STORAGE_DIR, "classic_concat", job_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "merged.mp4")
    list_file = os.path.join(out_dir, "list.txt")
    try:
        if not clip_paths:
            raise ValueError("No clip files provided")
        for p in clip_paths:
            if not os.path.exists(p):
                raise ValueError(f"Clip file missing: {p}")

        if len(clip_paths) == 1:
            # Single clip — NVENC re-encode for codec normalisation
            rc = await _run_ffmpeg(
                "ffmpeg", "-y", "-i", clip_paths[0],
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "-c:v", "h264_nvenc", "-b:v", "10M",
                "-c:a", "aac", "-b:a", "192k",
                out_path,
            )
        else:
            # Build concat list, re-encode each to normalised intermediate, then concat
            seg_files = []
            for i, p in enumerate(clip_paths):
                seg_out = os.path.join(out_dir, f"seg_{i:03d}.mp4")
                rc = await _run_ffmpeg(
                    "ffmpeg", "-y", "-i", p,
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                    "-c:v", "h264_nvenc", "-b:v", "10M",
                    "-c:a", "aac", "-b:a", "192k",
                    seg_out,
                )
                if rc != 0 or not os.path.exists(seg_out):
                    raise RuntimeError(f"Segment {i} NVENC pre-encode failed")
                seg_files.append(seg_out)

            with open(list_file, "w", encoding="utf-8") as f:
                for p in seg_files:
                    f.write(f"file '{p}'\n")

            rc = await _run_ffmpeg(
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                out_path,
            )
            # Clean up intermediates
            for p in seg_files:
                try:
                    os.remove(p)
                except Exception:
                    pass

        if rc != 0 or not os.path.exists(out_path):
            raise RuntimeError("NVENC classic concat failed")

        _classic_concat_jobs[job_id]["status"] = "done"
        _classic_concat_jobs[job_id]["output_path"] = out_path
    except Exception as e:
        _classic_concat_jobs[job_id]["status"] = "error"
        _classic_concat_jobs[job_id]["error"] = str(e)
    finally:
        # Clean up list file and uploaded source clips (keep only merged output)
        try:
            os.remove(list_file)
        except Exception:
            pass
        upload_dir = os.path.join(out_dir, "uploads")
        if os.path.isdir(upload_dir):
            import shutil
            try:
                shutil.rmtree(upload_dir)
            except Exception:
                pass


async def _run_classic_concat_job(job_id: str, clip_paths: list):
    async with _classic_concat_sem:
        await _do_classic_concat_job(job_id, clip_paths)


@app.post("/classic-concat-jobs", status_code=201)
async def create_classic_concat_job(files: list[UploadFile] = File(...)):
    """Receive pre-processed clip files, NVENC-merge them, return job_id."""
    if not files:
        raise HTTPException(status_code=422, detail="No files uploaded")
    job_id = uuid.uuid4().hex[:16]
    upload_dir = os.path.join(STORAGE_DIR, "classic_concat", job_id, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    clip_paths = []
    for i, f in enumerate(files):
        dest = os.path.join(upload_dir, f"{i:03d}_{f.filename or 'clip.mp4'}")
        async with aiofiles.open(dest, "wb") as out:
            while chunk := await f.read(1024 * 1024):
                await out.write(chunk)
        clip_paths.append(dest)
    _classic_concat_jobs[job_id] = {
        "status": "queued", "output_path": None, "error": None,
        "_created_at": time.time(),
    }
    asyncio.create_task(_run_classic_concat_job(job_id, clip_paths))
    return {"job_id": job_id, "status": "queued"}


@app.get("/classic-concat-jobs/{job_id}")
async def get_classic_concat_job(job_id: str):
    job = _classic_concat_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Classic-concat job not found")
    return {"job_id": job_id, "status": job["status"], "error": job.get("error")}


@app.get("/classic-concat-jobs/{job_id}/mp4")
async def get_classic_concat_mp4(job_id: str):
    job = _classic_concat_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Classic-concat job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Not ready (status={job['status']})")
    path = job.get("output_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Output file missing")
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}_classic.mp4")


# ── TTS endpoints (CosyVoice2) ────────────────────────────────────────────────

class TTSJobRequest(BaseModel):
    text: str
    emotion: str = "natural"          # excited|warm|clear|natural|persuasive
    ref_clip_job_id: str = ""         # optional: clip-job-id to clone voice from (legacy)
    ref_voice_id: str = ""            # optional: voice-ref-id from /voice-refs endpoint
    room_id: int = None               # optional: auto-use the latest done voice-ref for this room
    prompt_text: str = ""             # optional: override transcript for reference audio
    sft_spk: str = ""                 # optional: use inference_sft with a built-in speaker ID
    speed: float = 1.0                # playback speed ratio (atempo post-processing)


@app.post("/tts-jobs", status_code=201)
async def create_tts_job(req: TTSJobRequest):
    if not req.text.strip():
        raise HTTPException(status_code=422, detail="text is empty")

    # Resolve reference audio — priority: explicit ref_voice_id > room auto-lookup > clip-job (legacy)
    ref_audio_path = ""
    prompt_text = ""
    if req.ref_voice_id:
        ref = _voice_refs.get(req.ref_voice_id)
        if ref and ref.get("status") == "done":
            wav = ref.get("wav_path", "")
            ref_audio_path = wav if wav and os.path.isfile(wav) else ""
            prompt_text = ref.get("transcript", "") or ""
        else:
            logger.warning(f"voice ref {req.ref_voice_id} not ready (status={ref.get('status') if ref else 'not found'})")
    elif req.room_id:
        # Auto-find the most recent done voice ref for this room
        ref = _get_room_voice_ref(req.room_id)
        if ref:
            wav = ref.get("wav_path", "")
            ref_audio_path = wav if wav and os.path.isfile(wav) else ""
            prompt_text = ref.get("transcript", "") or ""
            logger.info(f"TTS: auto-using room {req.room_id} voice ref {ref['ref_id']} ({ref.get('label','')})")
        else:
            logger.warning(f"TTS: no done voice ref found for room {req.room_id}")
    elif req.ref_clip_job_id:
        ref_job = _clip_jobs.get(req.ref_clip_job_id)
        if ref_job and ref_job.get("status") == "done":
            mp4_path = ref_job.get("output_path", "")
            if mp4_path and os.path.isfile(mp4_path):
                # Extract WAV from MP4 for CosyVoice2 reference audio
                wav_path = mp4_path.replace(".mp4", "_ref.wav")
                if not os.path.isfile(wav_path):
                    try:
                        subprocess.run(
                            ["ffmpeg", "-y", "-i", mp4_path, "-vn",
                             "-ar", "16000", "-ac", "1", wav_path],
                            capture_output=True, check=True
                        )
                    except Exception as e:
                        logger.warning(f"Failed to extract WAV from clip {mp4_path}: {e}")
                        wav_path = ""
                ref_audio_path = wav_path if os.path.isfile(wav_path) else ""

    job_id = uuid.uuid4().hex[:16]
    _tts_jobs[job_id] = {"status": "queued", "output_path": None, "error": None, "_created_at": time.time()}
    _db_insert_tts_job(job_id)
    # Manual prompt_text override wins over looked-up transcript
    if req.prompt_text.strip():
        prompt_text = req.prompt_text.strip()

    asyncio.create_task(_do_tts_job(job_id, req.text, req.emotion, ref_audio_path, prompt_text, req.sft_spk, req.speed))
    return {"job_id": job_id, "status": "queued"}


@app.get("/tts-jobs/{job_id}")
async def get_tts_job(job_id: str):
    job = _tts_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="TTS job not found")
    return {"job_id": job_id, "status": job["status"], "error": job.get("error")}


@app.get("/tts-jobs/{job_id}/audio")
async def get_tts_audio(job_id: str):
    job = _tts_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="TTS job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"TTS not ready (status={job['status']})")
    path = job.get("output_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Audio file missing on server")
    return FileResponse(path, media_type="audio/wav", filename=f"{job_id}.wav")


# ── Voice ref extraction (lightweight audio-only, no NVENC) ──────────────────

class VoiceRefRequest(BaseModel):
    mp4_filename: str   # filename in STORAGE_DIR/{room_id}/
    room_id: int
    start: float = 5.0  # start offset (seconds)
    end: float = 28.0   # end offset (seconds) — CosyVoice2 limit: <30s


async def _do_voice_ref(ref_id: str, mp4_path: str, start: float, duration: float):
    """Extract WAV audio from MP4 — runs in a thread, no NVENC required."""
    out_dir = os.path.join(STORAGE_DIR, "voice_refs")
    os.makedirs(out_dir, exist_ok=True)
    wav_path = os.path.join(out_dir, f"{ref_id}.wav")

    _voice_refs[ref_id].update({"status": "processing"})
    _db_update_voice_ref(ref_id, status="processing")

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-i", mp4_path,
            "-vn", "-ar", "16000", "-ac", "1",
            wav_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not os.path.isfile(wav_path) or os.path.getsize(wav_path) == 0:
            err = stderr[-300:].decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg audio extract failed (rc={proc.returncode}): {err}")

        # Transcribe the extracted WAV so inference_zero_shot gets a real prompt_text.
        # Run in a thread — wm.transcribe() is synchronous and would block the event loop.
        transcript = ""
        try:
            def _transcribe():
                wm = _get_model()
                segs, _ = wm.transcribe(wav_path, language="zh", beam_size=5, vad_filter=True)
                return "".join(s.text for s in segs).strip()
            transcript = await asyncio.to_thread(_transcribe)
            _log.info(f"Voice ref {ref_id}: transcript = {transcript[:80]!r}")
        except Exception as te:
            _log.warning(f"Voice ref {ref_id}: transcription failed: {te}")

        _voice_refs[ref_id].update({"status": "done", "wav_path": wav_path, "transcript": transcript})
        _db_update_voice_ref(ref_id, status="done", wav_path=wav_path, transcript=transcript)
        _log.info(f"Voice ref {ref_id}: extracted {os.path.getsize(wav_path)//1024} KB WAV")
    except Exception as e:
        err = str(e)[:300]
        _log.error(f"Voice ref {ref_id} failed: {err}")
        _voice_refs[ref_id].update({"status": "error", "error": err})
        _db_update_voice_ref(ref_id, status="error", error=err)


@app.post("/voice-refs", status_code=201)
async def create_voice_ref(req: VoiceRefRequest):
    """Extract a WAV voice reference from a recording (lightweight, no NVENC)."""
    mp4_path = os.path.join(STORAGE_DIR, str(req.room_id), req.mp4_filename)
    if not os.path.isfile(mp4_path):
        raise HTTPException(status_code=404, detail=f"File not found: {req.mp4_filename}")

    duration = max(1.0, req.end - req.start)
    ref_id = uuid.uuid4().hex[:16]
    _voice_refs[ref_id] = {"status": "queued", "wav_path": None, "error": None, "_created_at": time.time()}
    _db_insert_voice_ref(ref_id)
    asyncio.create_task(_do_voice_ref(ref_id, mp4_path, req.start, duration))
    return {"ref_id": ref_id, "status": "queued"}


@app.post("/voice-refs/upload", status_code=201)
async def upload_voice_ref(
    file: UploadFile = File(...),
    prompt_text: str = Form(default=""),
    room_id: int = Form(default=None),
    label: str = Form(default=""),
):
    """Upload a WAV/MP3 file as a voice reference, optionally binding it to a room.

    Usage:
        curl -X POST http://host:8877/voice-refs/upload \\
             -F "file=@speaker.wav" \\
             -F "room_id=1" \\
             -F "label=小圆圆不圆主播声音" \\
             -F "prompt_text=参考音频里说的原文（可选，留空则自动转录）"

    Once done, this ref becomes the default voice for that room's TTS jobs.
    """
    ref_id = uuid.uuid4().hex[:16]
    out_dir = os.path.join(STORAGE_DIR, "voice_refs")
    os.makedirs(out_dir, exist_ok=True)

    # Accept WAV or MP3; always normalise to 16kHz mono WAV for Whisper + CosyVoice2
    ext = os.path.splitext(file.filename or "")[1].lower() or ".wav"
    raw_path = os.path.join(out_dir, f"{ref_id}_raw{ext}")
    wav_path = os.path.join(out_dir, f"{ref_id}.wav")

    _voice_refs[ref_id] = {
        "status": "processing", "wav_path": None, "error": None,
        "room_id": room_id, "label": label or "", "_created_at": time.time(),
    }
    _db_insert_voice_ref(ref_id, room_id=room_id, label=label or None)
    _db_update_voice_ref(ref_id, status="processing")

    # Save upload
    content = await file.read()
    async with aiofiles.open(raw_path, "wb") as f:
        await f.write(content)

    async def _process():
        try:
            # Convert to 16kHz mono WAV (ffmpeg handles WAV/MP3/M4A/etc.)
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", raw_path,
                "-vn", "-ar", "16000", "-ac", "1", wav_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0 or not os.path.isfile(wav_path) or os.path.getsize(wav_path) == 0:
                raise RuntimeError(f"ffmpeg failed: {stderr[-200:].decode('utf-8', errors='replace')}")
            try:
                os.remove(raw_path)
            except OSError:
                pass

            # Auto-transcribe if no prompt_text provided
            transcript = prompt_text.strip()
            if not transcript:
                try:
                    def _transcribe():
                        wm = _get_model()
                        segs, _ = wm.transcribe(wav_path, language="zh", beam_size=5, vad_filter=True)
                        return "".join(s.text for s in segs).strip()
                    transcript = await asyncio.to_thread(_transcribe)
                    _log.info(f"Voice ref {ref_id} upload: transcript = {transcript[:80]!r}")
                except Exception as te:
                    _log.warning(f"Voice ref {ref_id} upload: transcription failed: {te}")

            _voice_refs[ref_id].update({"status": "done", "wav_path": wav_path, "transcript": transcript})
            _db_update_voice_ref(ref_id, status="done", wav_path=wav_path, transcript=transcript)
            _log.info(f"Voice ref {ref_id} upload done: {os.path.getsize(wav_path)//1024} KB")
        except Exception as e:
            err = str(e)[:300]
            _log.error(f"Voice ref {ref_id} upload failed: {err}")
            _voice_refs[ref_id].update({"status": "error", "error": err})
            _db_update_voice_ref(ref_id, status="error", error=err)

    asyncio.create_task(_process())
    return {"ref_id": ref_id, "status": "processing", "room_id": room_id, "label": label}


@app.get("/voice-refs")
async def list_voice_refs(room_id: int = None):
    """List all voice refs, optionally filtered by room_id."""
    refs = []
    for ref_id, ref in _voice_refs.items():
        if room_id is not None and ref.get("room_id") != room_id:
            continue
        refs.append({
            "ref_id": ref_id,
            "status": ref["status"],
            "room_id": ref.get("room_id"),
            "label": ref.get("label", ""),
            "transcript": ref.get("transcript", ""),
            "error": ref.get("error"),
        })
    refs.sort(key=lambda r: r["ref_id"], reverse=True)
    return refs


@app.get("/voice-refs/{ref_id}")
async def get_voice_ref(ref_id: str):
    ref = _voice_refs.get(ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="Voice ref not found")
    return {
        "ref_id": ref_id,
        "status": ref["status"],
        "room_id": ref.get("room_id"),
        "label": ref.get("label", ""),
        "transcript": ref.get("transcript", ""),
        "error": ref.get("error"),
    }


# ── Director job (multi-source clip composition, NVENC) ──────────────────────

_director_jobs: dict = {}
_director_sem: asyncio.Semaphore = asyncio.Semaphore(1)


class DirectorClipItem(BaseModel):
    room_id: int
    filename: str          # filename only; located at STORAGE_DIR/{room_id}/{filename}
    start: float           # start offset in source file (seconds)
    duration: float        # desired clip duration (seconds)
    scene_type: str = ""   # hook / transformation / etc. (informational)


class DirectorJobRequest(BaseModel):
    clips: list            # list of DirectorClipItem dicts
    ass_content: str = ""  # combined ASS subtitle (pre-built on client, timed to full video)
    tts_audio_b64: str = ""  # base64-encoded TTS WAV (replaces original audio)
    transition_type: str = "slideleft"
    transition_duration: float = 0.4
    thumb_seek: float = 3.0


def _update_director_job(job_id: str, **kwargs):
    _director_jobs.setdefault(job_id, {}).update(kwargs)


async def _nvenc_director_merge(seg_files_with_dur: list, out_dir: str,
                                 transition_type: str, transition_duration: float):
    """
    Sequential xfade merge for director clips using NVENC.
    Supports all FFmpeg xfade transitions; falls back to dissolve if unknown.
    """
    _VALID_XFADE = {
        "fadewhite", "fadeblack", "fadegrays", "dissolve", "hblur",
        "smoothleft", "smoothright", "wipeleft", "slideleft", "slideright",
        "slideup", "squeezeh", "squeezev", "diagtl", "diagtr",
        "horzopen", "horzclose", "zoomin", "radial",
    }
    tr = transition_type if transition_type in _VALID_XFADE else "dissolve"
    fade = max(0.1, min(transition_duration, 1.0))

    if not seg_files_with_dur:
        return None
    if len(seg_files_with_dur) == 1:
        return seg_files_with_dur[0][0]

    _counter = [0]

    async def _has_video_stream(path: str) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        return bool(out.strip())

    async def _merge2(f1: str, d1: float, f2: str, d2: float, dst: str):
        off = max(0.0, d1 - fade)
        (hv1, ha1), (hv2, ha2) = await asyncio.gather(
            asyncio.gather(_has_video_stream(f1), _has_audio_stream(f1)),
            asyncio.gather(_has_video_stream(f2), _has_audio_stream(f2)),
        )
        # If either input lacks video, fall back to the one that has video (or f1)
        if not hv1 and not hv2:
            raise RuntimeError(f"Both seg inputs lack video stream: {f1}, {f2}")
        if not hv1:
            import shutil; shutil.copy2(f2, dst)
            return True, d2
        if not hv2:
            import shutil; shutil.copy2(f1, dst)
            return True, d1

        vf = (f"[0:v]settb=1/25[va];[1:v]settb=1/25[vb];"
              f"[va][vb]xfade=transition={tr}:duration={fade}:offset={off:.3f}[vout]")

        if ha1 and ha2:
            fc = vf + f";[0:a][1:a]acrossfade=d={fade}[aout]"
            maps = ["-map", "[vout]", "-map", "[aout]"]
            aargs = ["-c:a", "aac", "-b:a", "128k"]
        elif ha1:
            fc = vf
            maps = ["-map", "[vout]", "-map", "0:a"]
            aargs = ["-c:a", "aac", "-b:a", "128k"]
        elif ha2:
            fc = vf
            maps = ["-map", "[vout]", "-map", "1:a"]
            aargs = ["-c:a", "aac", "-b:a", "128k"]
        else:
            fc = vf
            maps = ["-map", "[vout]"]
            aargs = ["-an"]

        rc = await _run_ffmpeg(
            "ffmpeg", "-y", "-i", f1, "-i", f2,
            "-filter_complex", fc,
            *maps,
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_nvenc", "-b:v", "10M",
            *aargs,
            dst,
        )
        return rc == 0, d1 - fade + d2

    chunks = list(seg_files_with_dur)
    temp_files: set = set()

    while len(chunks) > 1:
        next_chunks = []
        for i in range(0, len(chunks), 2):
            if i + 1 >= len(chunks):
                next_chunks.append(chunks[i])
            else:
                _counter[0] += 1
                dst = os.path.join(out_dir, f"dtree_{_counter[0]}.mp4")
                ok, new_dur = await _merge2(
                    chunks[i][0], chunks[i][1],
                    chunks[i + 1][0], chunks[i + 1][1], dst,
                )
                for f, _ in (chunks[i], chunks[i + 1]):
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


async def _do_director_job(job_id: str, clips: list, ass_content: str,
                            tts_audio_b64: str, transition_type: str,
                            transition_duration: float, thumb_seek: float):
    """Full director pipeline on GPU: preprocess N clips → xfade merge → subtitle+audio encode."""
    import base64 as _b64
    out_dir = os.path.join(STORAGE_DIR, "director", job_id)
    os.makedirs(out_dir, exist_ok=True)

    try:
        _update_director_job(job_id, status="processing", phase="preprocess", pct=0)

        n = len(clips)
        _SF = (
            f"scale={CLIP_W}:{CLIP_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={CLIP_W}:{CLIP_H}:(ow-iw)/2:(oh-ih)/2,"
            f"unsharp=5:5:0.6:5:5:0.0"
        )

        # ── Phase 1: preprocess each clip ─────────────────────────────────────
        seg_files_with_dur = []
        for i, clip in enumerate(clips):
            mp4_path = os.path.join(STORAGE_DIR, str(clip["room_id"]), clip["filename"])
            if not os.path.exists(mp4_path):
                raise FileNotFoundError(f"Source not found: {mp4_path}")

            seg_out = os.path.join(out_dir, f"seg{i:03d}.mp4")
            start    = float(clip["start"])
            duration = float(clip["duration"])

            rc = await _run_ffmpeg(
                "ffmpeg", "-y",
                "-ss", f"{start:.3f}", "-t", f"{duration + 0.1:.3f}", "-i", mp4_path,
                "-vf", f"trim=0:{duration:.3f},setpts=PTS-STARTPTS,{_SF},fps=25",
                "-af", f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS",
                "-c:v", "h264_nvenc", "-b:v", "10M",
                "-c:a", "aac", "-b:a", "128k",
                seg_out,
            )
            if rc != 0 or not os.path.exists(seg_out):
                raise RuntimeError(f"Clip {i} preprocess failed (rc={rc})")

            seg_files_with_dur.append((seg_out, duration))
            _update_director_job(job_id, pct=int((i + 1) / n * 40))

        # ── Phase 2: xfade merge ───────────────────────────────────────────────
        _update_director_job(job_id, phase="merge", pct=40)
        merged = await _nvenc_director_merge(
            seg_files_with_dur, out_dir, transition_type, transition_duration
        )
        if not merged or not os.path.exists(merged):
            raise RuntimeError("xfade merge failed")
        _update_director_job(job_id, pct=75)

        # ── Phase 3: final encode – subtitle burn + TTS audio ─────────────────
        _update_director_job(job_id, phase="final", pct=75)
        final_out = os.path.join(out_dir, "director.mp4")

        # Write ASS
        ass_path = os.path.join(out_dir, "subs.ass")
        has_subs = False
        if ass_content and "Dialogue:" in ass_content:
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(ass_content)
            has_subs = True

        # Write TTS audio
        tts_path = None
        has_tts = False
        if tts_audio_b64:
            tts_path = os.path.join(out_dir, "tts.wav")
            with open(tts_path, "wb") as f:
                f.write(_b64.b64decode(tts_audio_b64))
            has_tts = os.path.exists(tts_path) and os.path.getsize(tts_path) > 0

        merged_has_audio = await _has_audio_stream(merged)
        inputs = ["-i", merged]

        if has_tts:
            inputs += ["-i", tts_path]
            audio_filter = (
                "[1:a]acompressor=threshold=-25dB:ratio=3:attack=5:release=100:makeup=4dB,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"
            )
            has_audio_out = True
        elif merged_has_audio:
            audio_filter = (
                "[0:a]acompressor=threshold=-25dB:ratio=3:attack=5:release=100:makeup=4dB,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"
            )
            has_audio_out = True
        else:
            audio_filter = None
            has_audio_out = False

        if has_subs:
            fwd = ass_path.replace("\\", "/")
            escaped = (fwd[0] + "\\:" + fwd[2:]) if len(fwd) > 1 and fwd[1] == ":" else fwd
            if FONTS_DIR:
                ff = FONTS_DIR.replace("\\", "/")
                fonts_esc = (ff[0] + "\\:" + ff[2:]) if len(ff) > 1 and ff[1] == ":" else ff
                video_filter = f"[0:v]ass=filename='{escaped}':fontsdir='{fonts_esc}',format=yuv420p[vout]"
            else:
                video_filter = f"[0:v]ass=filename='{escaped}',format=yuv420p[vout]"
            if audio_filter:
                filter_complex = f"{audio_filter};{video_filter}"
            else:
                filter_complex = video_filter
            vmap = "[vout]"
        else:
            if audio_filter:
                filter_complex = audio_filter
            else:
                filter_complex = None
            vmap = "0:v"

        ff_args = [FFMPEG_ASS, "-y", *inputs]
        if filter_complex:
            ff_args += ["-filter_complex", filter_complex]
        ff_args += ["-map", vmap]
        if has_audio_out:
            ff_args += ["-map", "[aout]" if audio_filter else "0:a"]
        ff_args += ["-pix_fmt", "yuv420p"]

        rc = await _run_ffmpeg(
            *ff_args,
            "-c:v", "h264_nvenc", "-b:v", "10M",
            "-ar", "44100", "-ac", "2",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            final_out,
        )
        if rc != 0 or not os.path.exists(final_out):
            raise RuntimeError(f"Final encode failed (rc={rc})")

        # ── Phase 4: thumbnail ────────────────────────────────────────────────
        _update_director_job(job_id, phase="thumbnail", pct=90)
        thumb_out = os.path.join(out_dir, "thumb.jpg")
        if seg_files_with_dur:
            await _run_ffmpeg(
                "ffmpeg", "-y",
                "-ss", f"{max(1.0, thumb_seek):.3f}", "-i", merged,
                "-frames:v", "1",
                "-vf", (f"scale={CLIP_W}:{CLIP_H}:force_original_aspect_ratio=decrease,"
                        f"pad={CLIP_W}:{CLIP_H}:(ow-iw)/2:(oh-ih)/2"),
                "-q:v", "2", thumb_out,
            )
        thumb_path = thumb_out if os.path.exists(thumb_out) and os.path.getsize(thumb_out) > 0 else None

        _update_director_job(
            job_id, status="done", phase="done", pct=100,
            output_path=final_out, thumb_path=thumb_path or "",
        )
        logger.info(f"Director job {job_id} complete: {final_out}")

    except Exception as e:
        _update_director_job(job_id, status="error", error=str(e))
        logger.error(f"Director job {job_id} failed: {e}")


async def _run_director_job(job_id: str, clips: list, ass_content: str,
                             tts_audio_b64: str, transition_type: str,
                             transition_duration: float, thumb_seek: float):
    async with _director_sem:
        await _do_director_job(job_id, clips, ass_content, tts_audio_b64,
                                transition_type, transition_duration, thumb_seek)


@app.post("/director-jobs", status_code=201)
async def create_director_job(req: DirectorJobRequest):
    if not req.clips:
        raise HTTPException(status_code=422, detail="clips is empty")
    job_id = f"dir_{uuid.uuid4().hex[:12]}"
    _update_director_job(job_id, status="queued", phase="", pct=0,
                         created_at=time.time())
    asyncio.create_task(_run_director_job(
        job_id,
        req.clips,
        req.ass_content,
        req.tts_audio_b64,
        req.transition_type,
        req.transition_duration,
        req.thumb_seek,
    ))
    return {"job_id": job_id, "status": "queued"}


@app.get("/director-jobs/{job_id}")
async def get_director_job(job_id: str):
    job = _director_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Director job not found")
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "phase":  job.get("phase", ""),
        "pct":    job.get("pct", 0),
        "error":  job.get("error"),
    }


@app.get("/director-jobs/{job_id}/mp4")
async def get_director_mp4(job_id: str):
    job = _director_jobs.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(status_code=404, detail="Director job not ready")
    path = job.get("output_path")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Output file missing on server")
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")


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


@app.post("/maintenance/cleanup-clips")
async def cleanup_clips():
    """Delete output dirs for completed/errored clip jobs. Frees disk space."""
    import shutil
    deleted = 0
    freed_bytes = 0

    terminal_clip_ids = [
        jid for jid, j in list(_clip_jobs.items())
        if j.get("status") in ("done", "error")
    ]
    for jid in terminal_clip_ids:
        job = _clip_jobs.get(jid)
        if not job:
            continue
        out_path = job.get("output_path", "")
        if out_path:
            job_dir = os.path.dirname(out_path)
            if os.path.isdir(job_dir):
                try:
                    size = sum(
                        os.path.getsize(os.path.join(dp, f))
                        for dp, _, files in os.walk(job_dir)
                        for f in files
                    )
                    shutil.rmtree(job_dir, ignore_errors=True)
                    freed_bytes += size
                    deleted += 1
                except Exception:
                    pass
        _clip_jobs.pop(jid, None)

    # Also clean up terminal concat job dirs
    terminal_concat_ids = [
        jid for jid, j in list(_concat_jobs.items())
        if j.get("status") in ("done", "error")
    ]
    for jid in terminal_concat_ids:
        job = _concat_jobs.get(jid)
        if not job:
            continue
        out_path = job.get("output_path", "")
        if out_path:
            job_dir = os.path.dirname(out_path)
            if os.path.isdir(job_dir):
                try:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    deleted += 1
                except Exception:
                    pass
        _concat_jobs.pop(jid, None)

    # Clean up terminal TTS output files
    tts_dir = os.path.join(STORAGE_DIR, "tts_outputs")
    terminal_tts_ids = [
        jid for jid, j in list(_tts_jobs.items())
        if j.get("status") in ("done", "error")
    ]
    for jid in terminal_tts_ids:
        job = _tts_jobs.get(jid)
        if not job:
            continue
        out_path = job.get("output_path", "")
        if out_path and os.path.isfile(out_path):
            try:
                size = os.path.getsize(out_path)
                os.remove(out_path)
                freed_bytes += size
                deleted += 1
            except Exception:
                pass
        _tts_jobs.pop(jid, None)

    return {"deleted": deleted, "freed_gb": round(freed_bytes / 1024 ** 3, 3)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8877"))
    uvicorn.run(app, host="0.0.0.0", port=port)
