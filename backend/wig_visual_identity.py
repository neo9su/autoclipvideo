"""Client and deterministic reducer for Qwen-VL wig identity observations."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Mapping
from urllib import request


class VisualIdentityUnavailable(RuntimeError):
    pass


def sample_times(window: Mapping[str, object], count: int = 5) -> List[float]:
    start = float(window["start_sec"])
    end = float(window["end_sec"])
    if end <= start:
        return []
    margin = min(2.0, max(0.0, (end - start) / 10))
    low, high = start + margin, end - margin
    if count <= 1 or high <= low:
        return [(start + end) / 2]
    return [low + (high - low) * index / (count - 1) for index in range(count)]


def accepted_visual_windows(
    windows: Iterable[Mapping[str, object]], observations: Iterable[Mapping[str, object]]
) -> List[Dict]:
    """Keep windows with stable-wearing evidence and one consistent style identity."""
    by_window: Dict[int, List[Mapping[str, object]]] = {}
    for item in observations:
        by_window.setdefault(int(item.get("window_index", -1)), []).append(item)
    accepted = []
    reference_signature = ""
    for index, raw in enumerate(windows):
        items = by_window.get(index, [])
        stable = [item for item in items if item.get("wear_state") == "stable_wearing"]
        unsafe = [item for item in items if item.get("wear_state") in {"no_wig", "transition"}]
        signatures = {str(item.get("style_signature") or "").strip() for item in stable} - {""}
        if len(stable) < 3 or len(unsafe) > 1 or len(signatures) != 1:
            continue
        signature = next(iter(signatures))
        if reference_signature and signature != reference_signature:
            continue
        reference_signature = reference_signature or signature
        item = dict(raw)
        item["visual_verified"] = True
        item["visual_style_signature"] = signature
        item["identity_evidence"] = "transcript_boundary_and_qwen_vl_sequence"
        accepted.append(item)
    return accepted


def verify_windows(video_path: str | Path, windows: List[Dict], target_name: str, target_color: str) -> List[Dict]:
    url = os.environ.get("WIG_VISUAL_IDENTITY_URL", "").strip()
    if not url:
        return windows
    observations = []
    for offset in range(0, len(windows), 3):
        chunk = windows[offset:offset + 3]
        payload = {
            "video_path": str(video_path), "target_name": target_name, "target_color": target_color,
            "windows": [{**window, "sample_times": sample_times(window)} for window in chunk],
        }
        req = request.Request(
            url.rstrip("/") + "/analyze-wig-windows",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with request.urlopen(req, timeout=float(os.environ.get("WIG_VISUAL_TIMEOUT", "900"))) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise VisualIdentityUnavailable(str(exc)) from exc
        for item in result.get("observations") or []:
            item["window_index"] = int(item.get("window_index", -1)) + offset
            observations.append(item)
    return accepted_visual_windows(windows, observations)
