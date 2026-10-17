"""Lazy, GPU-aware Qwen3-VL service for wig wearing and identity continuity."""
from __future__ import annotations

import gc
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import List

import cv2
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("QWEN_VL_MODEL", r"F:\models\Qwen3-VL-2B-Instruct")
MIN_FREE_MIB = int(os.environ.get("QWEN_VL_MIN_FREE_MIB", "6000"))
GPU_WAIT_SEC = int(os.environ.get("QWEN_VL_GPU_WAIT_SEC", "600"))
ALLOWED_ROOTS = tuple(
    Path(value).resolve() for value in os.environ.get(
        "QWEN_VL_ALLOWED_ROOTS", r"C:\Users\neo\douyin_backend\recordings;F:\douyin_recordings"
    ).split(";") if value
)
UNLOAD = os.environ.get("QWEN_VL_UNLOAD_AFTER_REQUEST", "1") == "1"

app = FastAPI(title="Qwen VL Wig Identity", version="1.0")
lock = threading.Lock()
model = processor = None


class Window(BaseModel):
    start_sec: float
    end_sec: float
    sample_times: List[float] = Field(min_length=1, max_length=8)


class AnalyzeRequest(BaseModel):
    video_path: str
    target_name: str = ""
    target_color: str = ""
    windows: List[Window] = Field(min_length=1, max_length=3)


def _allowed(path: Path) -> bool:
    return any(path == root or root in path.parents for root in ALLOWED_ROOTS)


def _free_mib() -> int:
    return int(torch.cuda.mem_get_info()[0] / 1024 / 1024) if torch.cuda.is_available() else 0


def _load():
    global model, processor
    if model is not None:
        return
    if not torch.cuda.is_available():
        raise HTTPException(503, "CUDA unavailable")
    deadline = time.monotonic() + GPU_WAIT_SEC
    while _free_mib() < MIN_FREE_MIB and time.monotonic() < deadline:
        time.sleep(5)
    if _free_mib() < MIN_FREE_MIB:
        raise HTTPException(503, f"GPU busy; free={_free_mib()} MiB, required={MIN_FREE_MIB} MiB")
    from transformers import AutoModelForMultimodalLM, AutoProcessor
    processor = AutoProcessor.from_pretrained(MODEL_ID, local_files_only=True)
    model = AutoModelForMultimodalLM.from_pretrained(
        MODEL_ID, local_files_only=True, torch_dtype=torch.bfloat16,
        device_map="cuda", low_cpu_mem_usage=True,
    ).eval()


def _unload():
    global model, processor
    model = processor = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _frame(cap, second: float):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, second) * 1000)
    ok, bgr = cap.read()
    if not ok:
        return None
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    from PIL import Image
    image = Image.fromarray(rgb)
    image.thumbnail((448, 448))
    return image


def _parse(raw: str) -> list:
    match = re.search(r"\[.*\]", raw, re.S)
    if not match:
        raise HTTPException(502, "model returned no JSON array")
    data = json.loads(match.group())
    return data if isinstance(data, list) else []


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_ID, "loaded": model is not None, "gpu_free_mib": _free_mib()}


@app.post("/analyze-wig-windows")
def analyze(req: AnalyzeRequest):
    path = Path(req.video_path).resolve()
    if not path.is_file() or not _allowed(path):
        raise HTTPException(400, "video path is unavailable or outside allowed roots")
    if not lock.acquire(blocking=False):
        raise HTTPException(503, "visual model is busy")
    try:
        _load()
        cap = cv2.VideoCapture(str(path))
        images, frame_meta = [], []
        try:
            for window_index, window in enumerate(req.windows):
                for second in window.sample_times:
                    image = _frame(cap, second)
                    if image is not None:
                        images.append(image)
                        frame_meta.append({"window_index": window_index, "time_sec": second})
        finally:
            cap.release()
        if not images:
            raise HTTPException(422, "no frames decoded")
        content = []
        for meta, image in zip(frame_meta, images):
            content += [{"type": "text", "text": f"frame={json.dumps(meta)}"}, {"type": "image", "image": image}]
        content.append({"type": "text", "text": (
            "逐帧判断主播状态。wear_state只能是 no_wig、transition、stable_wearing。"
            "transition包括正在戴、正在摘、手持假发、发网阶段或严重遮挡。"
            "对stable_wearing生成稳定style_signature，格式为颜色|长短|直卷|刘海|头顶工艺；"
            "同一款摘下再戴回必须给相同signature，真正换款必须不同。"
            f"商品提示：{req.target_name}，颜色提示：{req.target_color}。"
            "只返回JSON数组，每项含window_index,time_sec,wear_state,style_signature,confidence,reason。"
        )})
        messages = [{"role": "user", "content": content}]
        inputs = processor.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt",
        ).to(model.device)
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=800, do_sample=False)
        raw = processor.decode(output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
        return {"model": MODEL_ID, "observations": _parse(raw)}
    finally:
        if UNLOAD:
            _unload()
        lock.release()
