"""
ComfyUI API client.

Provides anime-style img2img generation:
  1. Upload source frame to ComfyUI
  2. Run img2img workflow: AnythingV5 + ControlNet Tile
  3. Poll until done, download result image
"""
import asyncio
import json
import logging
import os
import random
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://10.190.0.203:8188")

# Anime-style prompts
_POSITIVE_BASE = (
    "masterpiece, best quality, anime illustration, beautiful girl, "
    "gorgeous hair, detailed face, vibrant warm colors, cheerful bright lighting, "
    "sunny atmosphere, warm golden light, happy joyful expression, "
    "bokeh background, pastel tones, glowing skin, "
    "fashion outfit, dynamic pose, high detail, 8k"
)
_NEGATIVE = (
    "lowres, bad anatomy, bad hands, missing fingers, extra limbs, "
    "blurry, worst quality, low quality, jpeg artifacts, watermark, "
    "text, signature, username, ugly, deformed, mutated, disfigured, "
    "dark, gloomy, moody, shadow, low contrast, desaturated"
)

# ── Workflow builder ───────────────────────────────────────────────────────────

def _build_workflow(image_name: str, seed: int, denoise: float = 0.65) -> dict:
    """
    Build ComfyUI workflow JSON for img2img with ControlNet Tile.

    Graph:
      CheckpointLoader → CLIP → positive/negative conditioning
      LoadImage → ControlNetApply (tile) → KSampler → VAEDecode → SaveImage
                → VAEEncode ─────────────────────────────────────────────┘
    """
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "AnythingV5.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": _POSITIVE_BASE, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": _NEGATIVE, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
        "5": {
            "class_type": "ControlNetLoader",
            "inputs": {"control_net_name": "control_v11f1e_sd15_tile.pth"},
        },
        "6": {
            "class_type": "ControlNetApply",
            "inputs": {
                "conditioning": ["2", 0],
                "control_net": ["5", 0],
                "image": ["4", 0],
                "strength": 0.75,
            },
        },
        "7": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["4", 0], "vae": ["1", 2]},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["6", 0],
                "negative": ["3", 0],
                "latent_image": ["7", 0],
                "seed": seed,
                "steps": 25,
                "cfg": 7.0,
                "sampler_name": "euler_ancestral",
                "scheduler": "karras",
                "denoise": denoise,
            },
        },
        "9": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["8", 0], "vae": ["1", 2]},
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {"images": ["9", 0], "filename_prefix": "thumb"},
        },
    }


# ── API calls ─────────────────────────────────────────────────────────────────

async def _upload_image(client: httpx.AsyncClient, image_path: str) -> Optional[str]:
    """Upload an image file to ComfyUI's input directory. Returns filename."""
    with open(image_path, "rb") as f:
        resp = await client.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (os.path.basename(image_path), f, "image/jpeg")},
            data={"overwrite": "true"},
            timeout=30,
        )
    if resp.status_code == 200:
        return resp.json()["name"]
    logger.error(f"ComfyUI upload failed: {resp.status_code} {resp.text[:200]}")
    return None


async def _queue_prompt(client: httpx.AsyncClient, workflow: dict) -> Optional[str]:
    """Submit workflow to queue. Returns prompt_id."""
    resp = await client.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow},
        timeout=15,
    )
    if resp.status_code == 200:
        return resp.json()["prompt_id"]
    logger.error(f"ComfyUI queue failed: {resp.status_code} {resp.text[:200]}")
    return None


async def _wait_for_result(
    client: httpx.AsyncClient, prompt_id: str, timeout: int = 120
) -> Optional[str]:
    """Poll history until prompt completes. Returns output image filename."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(2)
        try:
            resp = await client.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            if resp.status_code != 200:
                continue
            history = resp.json()
            if prompt_id not in history:
                continue
            job = history[prompt_id]
            # Detect error state immediately instead of waiting for timeout
            status = job.get("status", {})
            if isinstance(status, dict) and status.get("status_str") == "error":
                msgs = status.get("messages", [])
                err_msgs = [m[1] for m in msgs if isinstance(m, list) and m[0] == "execution_error"]
                err_detail = err_msgs[0].get("exception_message", "unknown") if err_msgs else "unknown"
                logger.error(f"ComfyUI job {prompt_id} failed: {err_detail}")
                return None
            outputs = job.get("outputs", {})
            for node_output in outputs.values():
                images = node_output.get("images", [])
                if images:
                    return images[0]["filename"]
        except Exception as e:
            logger.debug(f"ComfyUI poll error: {e}")
    logger.error(f"ComfyUI timeout waiting for prompt {prompt_id}")
    return None


async def _download_image(
    client: httpx.AsyncClient, filename: str, dest_path: str
) -> bool:
    """Download generated image from ComfyUI output."""
    resp = await client.get(
        f"{COMFYUI_URL}/view",
        params={"filename": filename, "type": "output"},
        timeout=30,
    )
    if resp.status_code == 200:
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        return True
    logger.error(f"ComfyUI download failed: {resp.status_code}")
    return False


async def _free_vram(client: httpx.AsyncClient) -> None:
    """Unload models and release VRAM after generation so Whisper/GPU service can allocate."""
    try:
        await client.post(
            f"{COMFYUI_URL}/api/free",
            json={"unload_models": True, "free_memory": True},
            timeout=10,
        )
        logger.debug("ComfyUI VRAM freed")
    except Exception as e:
        logger.debug(f"ComfyUI free VRAM failed (non-critical): {e}")


# ── Public API ────────────────────────────────────────────────────────────────

async def free_vram() -> None:
    """Proactively release ComfyUI VRAM so Whisper/other GPU consumers can allocate."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await _free_vram(client)
    except Exception:
        pass


async def health_check() -> bool:
    """Return True if ComfyUI is reachable."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{COMFYUI_URL}/system_stats")
            return resp.status_code == 200
    except Exception:
        return False


async def anime_img2img(
    source_image: str,
    output_path: str,
    seed: Optional[int] = None,
    denoise: float = 0.65,
    timeout: int = 120,
) -> bool:
    """
    Convert source_image to anime illustration style via ComfyUI.

    Args:
        source_image: path to input JPEG/PNG frame
        output_path:  where to save the result JPEG
        seed:         fixed seed for reproducibility (None = random)
        denoise:      img2img strength 0.0–1.0 (0.65 = preserve composition)
        timeout:      max seconds to wait for generation

    Returns True on success, False on failure.
    """
    if seed is None:
        seed = random.randint(0, 2**32 - 1)

    try:
        async with httpx.AsyncClient() as client:
            # 1. Upload source frame
            image_name = await _upload_image(client, source_image)
            if not image_name:
                return False
            logger.debug(f"Uploaded frame → {image_name}")

            # 2. Queue workflow
            workflow = _build_workflow(image_name, seed, denoise)
            prompt_id = await _queue_prompt(client, workflow)
            if not prompt_id:
                return False
            logger.debug(f"Queued prompt {prompt_id}")

            # 3. Wait for result
            output_filename = await _wait_for_result(client, prompt_id, timeout)
            if not output_filename:
                await _free_vram(client)
                return False
            logger.debug(f"Generated: {output_filename}")

            # 4. Download result
            ok = await _download_image(client, output_filename, output_path)

            # 5. Release VRAM so Whisper/GPU service can allocate freely
            await _free_vram(client)
            return ok

    except Exception as e:
        logger.error(f"ComfyUI anime_img2img error: {e}")
        return False
