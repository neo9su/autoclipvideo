"""
导演模式API路由 - v2版本
提供导演模式相关的所有接口
"""
import asyncio
import json
import logging
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from director_script import DirectorScriptGenerator
from voice_director import VoiceDirector
from director_matcher import SemanticMatcher, get_matcher
from director_video import DirectorVideoComposer
from qianchuan_script import generate_qianchuan_script
from qianchuan_matcher import (QianchuanMatcher, audit_qianchuan_segments,
                                load_group_context, score_product_match)
from qianchuan_video import QianchuanVideoComposer
from qianchuan_quality import check_qianchuan_video_quality
from qianchuan_policy import build_qianchuan_metadata, validate_qianchuan_metadata

logger = logging.getLogger(__name__)

# 创建导演模式路由
director_router = APIRouter(prefix="/api/v2/director", tags=["director"])
qianchuan_router = APIRouter(prefix="/api/v2/qianchuan", tags=["qianchuan"])

# WebSocket broadcast function — injected by main.py at startup
_broadcast_fn = None

def set_broadcast_fn(fn):
    global _broadcast_fn
    _broadcast_fn = fn


async def _broadcast(msg: dict):
    if _broadcast_fn:
        try:
            await _broadcast_fn(msg)
        except Exception:
            pass

# 初始化服务
script_generator = DirectorScriptGenerator()
voice_director = VoiceDirector()

# 同时最多 1 个 compose-video 任务（libx264/videotoolbox 占满 CPU）
_COMPOSE_SEM = asyncio.Semaphore(1)

class ScriptGenerationRequest(BaseModel):
    group_id: int
    script_type: str = "balanced"  # story/tutorial/comparison/planting/balanced（保留兼容）
    vibe: str = "trendy"           # trendy/emotional/lifestyle/luxury/contrast
    custom_config: Optional[Dict] = None

class ScriptGenerationResponse(BaseModel):
    success: bool
    script: Dict
    generated_at: float
    fallback: bool = False

class VoiceGenerationRequest(BaseModel):
    group_id: int
    use_voice_cloning: bool = True
    custom_reference_audio: Optional[str] = None

class VoiceGenerationResponse(BaseModel):
    success: bool
    audio_segments: List[Dict] = []
    merged_audio_path: Optional[str] = None
    total_duration: float = 0.0
    reference_audio_used: Optional[str] = None
    error: Optional[str] = None

class DirectorModeToggleRequest(BaseModel):
    group_id: int
    enabled: bool

class QianchuanGenerateRequest(BaseModel):
    group_id: int = Field(gt=0)
    product_id: Optional[str] = Field(default=None, max_length=128)
    product_keywords: List[str] = Field(default_factory=list, max_length=20)
    target_duration: float = Field(default=22.0, ge=18.0, le=35.0)
    match_threshold: float = Field(default=0.58, ge=0.0, le=1.0)
    dry_run: bool = False
    generate_video: bool = True
    target_audience: Optional[str] = None
    excluded_audiences: List[str] = Field(default_factory=list, max_length=10)
    bid_coefficient: Optional[float] = Field(default=None, gt=0, le=10)
    template_type: Optional[str] = None
    dedup_actions: List[str] = Field(default_factory=list, max_length=6)
    authenticity_check: Dict[str, Any] = Field(default_factory=dict)
    copy_versions: Dict[str, str] = Field(default_factory=dict)
    trust_proof: Optional[str] = None
    stability_evidence: List[str] = Field(default_factory=list, max_length=10)
    ai_usage: List[str] = Field(default_factory=list, max_length=10)
    ai_generated_human_wig_scene: bool = False
    execution_node: str = "remote-gpu"
    preview_mode: bool = False  # Explicit sample mode; never used for delivery eligibility

class QianchuanGenerateResponse(BaseModel):
    success: bool
    started: bool = False
    group_id: int
    status: int
    script: Optional[Dict] = None
    output_path: Optional[str] = None
    score: Optional[float] = None
    metadata: Optional[Dict] = None
    review: Optional[Dict] = None
    error: Optional[str] = None

@director_router.get("/status")
async def get_director_status():
    """获取导演模式系统状态"""
    from director_script import VIBE_CONFIGS
    return {
        "director_mode_available": True,
        "script_generator_ready": True,
        "supported_script_types": ["story", "tutorial", "comparison", "planting", "balanced"],
        "supported_vibes": {
            k: {"label": v["label"], "description": v["description"], "pacing": v["pacing"]}
            for k, v in VIBE_CONFIGS.items()
        },
        "version": "2.0.1",
    }


@qianchuan_router.get("/status")
async def get_qianchuan_status():
    return {
        "qianchuan_available": True,
        "default_duration": 22,
        "duration_range": "18-25s recommended, 35s hard max",
        "structure": "0-3s结果钩子 / 3-7s痛点 / 7-13s产品证据 / 13-19s上脸效果 / 19-23s CTA",
        "version": "1.0.0",
    }


@qianchuan_router.post("/generate", response_model=QianchuanGenerateResponse)
async def generate_qianchuan(request: QianchuanGenerateRequest):
    """生成千川投流版：强商品匹配 → 固定广告脚本 → 可选后台合成视频。"""
    import aiosqlite
    from db import DB_PATH

    product_keywords = [kw.strip()[:80] for kw in request.product_keywords if kw and kw.strip()]

    context = await load_group_context(DB_PATH, request.group_id, request.product_id)
    if not context:
        raise HTTPException(status_code=404, detail="分组不存在")

    match = score_product_match(
        context,
        product_id=request.product_id,
        keywords=product_keywords,
        threshold=request.match_threshold,
    )
    if not match.get("ok"):
        err = match.get("reason") or "商品强匹配不足"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE clip_groups SET qianchuan_status = -2, qianchuan_error = ?,
                   qianchuan_score = ?, qianchuan_review = ? WHERE id = ?""",
                (err[:500], match.get("score"), json.dumps(match, ensure_ascii=False), request.group_id),
            )
            await db.commit()
        return QianchuanGenerateResponse(
            success=False, group_id=request.group_id, status=-2,
            score=match.get("score"), review=match, error=err,
        )

    script = generate_qianchuan_script(
        context["group"],
        product_context=match.get("product") or {},
        target_duration=request.target_duration,
        selling_points=product_keywords,
    )
    script["preview_mode"] = request.preview_mode
    metadata = build_qianchuan_metadata(
        target_audience=request.target_audience,
        excluded_audiences=request.excluded_audiences,
        bid_coefficient=request.bid_coefficient,
        template_type=request.template_type,
        dedup_actions=request.dedup_actions,
        authenticity_check=request.authenticity_check,
        copy_versions=request.copy_versions,
        trust_proof=request.trust_proof,
        stability_evidence=request.stability_evidence,
        ai_usage=request.ai_usage,
        ai_generated_human_wig_scene=request.ai_generated_human_wig_scene,
        execution_node=request.execution_node,
    )
    policy = validate_qianchuan_metadata(metadata)
    script["campaign_metadata"] = metadata
    script["policy_check"] = policy
    if not policy["eligible_for_delivery"]:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE clip_groups SET qianchuan_status = -3, qianchuan_error = ?, qianchuan_script = ?, qianchuan_review = ? WHERE id = ?",
                ("; ".join(policy["errors"]), json.dumps(script, ensure_ascii=False), json.dumps(policy, ensure_ascii=False), request.group_id),
            )
            await db.commit()
        return QianchuanGenerateResponse(success=False, group_id=request.group_id, status=-3, script=script, metadata=metadata, review=policy, error="投放规则校验失败")

    from pipeline_state import claim_pipeline_start
    async with aiosqlite.connect(DB_PATH) as db:
        if not request.dry_run and request.generate_video:
            if not await claim_pipeline_start(db, "qianchuan_status", request.group_id):
                async with db.execute("SELECT qianchuan_status FROM clip_groups WHERE id = ?", (request.group_id,)) as cur:
                    current = await cur.fetchone()
                return QianchuanGenerateResponse(success=True, started=False, group_id=request.group_id, status=current[0] if current else 0, script=script, score=match.get("score"), review=match)
        await db.execute(
            """UPDATE clip_groups SET qianchuan_status = ?, qianchuan_error = NULL,
               qianchuan_script = ?, qianchuan_score = ?, qianchuan_review = ? WHERE id = ?""",
            (
                0 if request.dry_run or not request.generate_video else 1,
                json.dumps(script, ensure_ascii=False),
                match.get("score"),
                json.dumps(match, ensure_ascii=False),
                request.group_id,
            ),
        )
        await db.commit()

    if request.dry_run or not request.generate_video:
        return QianchuanGenerateResponse(
            success=True, started=False, group_id=request.group_id, status=0,
            script=script, score=match.get("score"), metadata=metadata, review=policy,
        )

    asyncio.create_task(_qianchuan_generate_bg(request.group_id, script))
    return QianchuanGenerateResponse(
        success=True, started=True, group_id=request.group_id, status=1,
        script=script, score=match.get("score"), metadata=metadata, review=policy,
    )


@qianchuan_router.post("/compose", response_model=QianchuanGenerateResponse)
async def compose_qianchuan(request: QianchuanGenerateRequest):
    """Alias for /generate, kept for callers that use compose wording."""
    return await generate_qianchuan(request)


@qianchuan_router.get("/group/{group_id}/result")
async def get_qianchuan_result(group_id: int):
    import aiosqlite
    from db import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT qianchuan_status, qianchuan_script, qianchuan_segments,
                      qianchuan_audio_path, qianchuan_final_video, qianchuan_error,
                      qianchuan_score, qianchuan_review
               FROM clip_groups WHERE id = ?""",
            (group_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="分组不存在")
    return {
        "group_id": group_id,
        "status": row[0],
        "script": _loads_qianchuan_json(row[1]),
        "segments": _loads_qianchuan_json(row[2]),
        "audio_path": row[3],
        "final_video": row[4],
        "error": row[5],
        "score": row[6],
        "review": _loads_qianchuan_json(row[7]),
    }


def _loads_qianchuan_json(value: Optional[str]) -> Optional[Any]:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return {"raw": str(value)[:1000], "parse_error": True}


async def _set_qianchuan_error(group_id: int, status: int, error: str, review: Optional[Dict] = None):
    import aiosqlite
    from db import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE clip_groups SET qianchuan_status = ?, qianchuan_error = ?,
               qianchuan_review = COALESCE(?, qianchuan_review) WHERE id = ?""",
            (status, (error or "")[:500], json.dumps(review, ensure_ascii=False) if review else None, group_id),
        )
        await db.commit()


async def _run_qianchuan_pipeline(group_id: int) -> None:
    """Auto-start Qianchuan once, while allowing failed attempts to retry."""
    import aiosqlite
    from db import DB_PATH, aio_connect
    from pipeline_state import claim_pipeline_start
    async with aio_connect() as db:
        if not await claim_pipeline_start(db, "qianchuan_status", group_id):
            logger.info(f"Qianchuan pipeline group {group_id} already running/completed — skipping")
            return
        await db.commit()
    try:
        context = await load_group_context(DB_PATH, group_id)
        if not context:
            raise RuntimeError("group not found")
        group = context["group"]
        match = score_product_match(context, keywords=[group.get("label"), group.get("wig_model"), group.get("wig_color")], threshold=0.0)
        script = generate_qianchuan_script(
            group, product_context=match.get("product") or {}, selling_points=[]
        )
        script["preview_mode"] = False
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE clip_groups SET qianchuan_script=?, qianchuan_score=?, qianchuan_review=? WHERE id=?", (json.dumps(script, ensure_ascii=False), match.get("score"), json.dumps(match, ensure_ascii=False), group_id))
            await db.commit()
        await _qianchuan_generate_bg(group_id, script)
    except Exception as exc:
        logger.error(f"Qianchuan pipeline {group_id} failed: {exc}")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE clip_groups SET qianchuan_status=-1, qianchuan_error=? WHERE id=?", (str(exc)[:400], group_id))
            await db.commit()


async def _qianchuan_generate_bg(group_id: int, script: Dict) -> None:
    import aiosqlite
    import os
    from db import DB_PATH

    async with _COMPOSE_SEM:
        try:
            # 1) Voiceover: reuse existing voice clone/TTS controller but keep qianchuan DB fields isolated.
            voice_result = await voice_director.generate_voiceover(script=script, group_id=group_id, reference_audio_path=None)
            if not voice_result.get("success"):
                raise RuntimeError(voice_result.get("error") or "千川配音生成失败")
            audio_path = voice_result.get("merged_audio_path")
            audio_segments = voice_result.get("audio_segments") or []
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE clip_groups SET qianchuan_audio_path = ?, qianchuan_segments = ? WHERE id = ?",
                    (audio_path, json.dumps(audio_segments, ensure_ascii=False), group_id),
                )
                await db.commit()

            # 2) Strong shot matching with ad-oriented metadata.
            matcher = QianchuanMatcher(DB_PATH)
            script_segments = [
                {
                    "text": s.get("voiceover_text", ""),
                    "voiceover_text": s.get("voiceover_text", ""),
                    "visual_keywords": s.get("visual_requirements", []),
                    "priority_shots": s.get("priority_shots", []),
                    "duration": max(2.5, next((a.get("duration", 0) for a in audio_segments if a.get("scene_id") == s.get("scene_id")), s.get("duration", 3.0))),
                    "scene_type": s.get("scene_type", ""),
                    "scene_id": s.get("scene_id"),
                }
                for s in script.get("scenes", [])
            ]
            matched = await matcher.match_qianchuan_segments(script_segments, group_id)
            audit = audit_qianchuan_segments(matched, audio_segments)
            review_payload = {"matching": matched, "relevance_audit": audit}
            minimum_matches = max(3, len(script_segments) - 1)
            if len(matched) < minimum_matches and not script.get("preview_mode"):
                detail = {
                    "matched_count": len(matched), "required_count": minimum_matches,
                    "matched_scene_ids": [item.get("script_segment", {}).get("scene_id") for item in matched],
                    "reason": "recordings unavailable or no usable SRT match",
                }
                logger.error("Qianchuan shot matching insufficient for group %s: %s", group_id, detail)
                await _set_qianchuan_error(group_id, -2, "千川镜头匹配不足: " + json.dumps(detail, ensure_ascii=False), review_payload)
                await _broadcast({"type": "qianchuan_error", "group_id": group_id, "error": detail, "review": review_payload})
                return
            if not audit.get("ok") and not script.get("preview_mode"):
                await _set_qianchuan_error(
                    group_id, -2, "千川文案-画面相关性不足，拒绝无关素材: "
                    + "; ".join(audit.get("rejection_reasons", []))[:450], review_payload)
                await _broadcast({"type": "qianchuan_relevance_rejected", "group_id": group_id, "review": review_payload})
                return

            if script.get("preview_mode"):
                review_payload["preview_mode"] = True
                review_payload["delivery_eligible"] = False
                logger.warning("Generating explicit Qianchuan preview for group %s despite strict audit", group_id)

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE clip_groups SET qianchuan_segments = ? WHERE id = ?",
                    (json.dumps({"audio_segments": audio_segments, "matched_segments": matched, "relevance_audit": audit}, ensure_ascii=False), group_id),
                )
                await db.commit()

            # 3) Compose via isolated composer wrapper.
            recordings_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "recordings"))
            composer = QianchuanVideoComposer(recordings_dir)
            output_path = await composer.compose_qianchuan_video(matched, audio_path, script, audio_segments)
            if not output_path:
                raise RuntimeError("千川视频合成失败: composer returned no output; check director/GPU logs")

            # 4) Quality gate. Keep statuses separate: -3 quality failure, -4 probe/encode failure.
            try:
                quality = await check_qianchuan_video_quality(output_path)
            except Exception as qe:
                await _set_qianchuan_error(group_id, -4, f"质量探测失败: {qe}")
                await _broadcast({"type": "qianchuan_error", "group_id": group_id, "error": str(qe)})
                return
            if not quality.get("ok"):
                await _set_qianchuan_error(group_id, -3, "; ".join(quality.get("errors", [])), quality)
                await _broadcast({"type": "qianchuan_error", "group_id": group_id, "error": quality.get("errors", [])})
                return

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """UPDATE clip_groups SET qianchuan_final_video = ?, qianchuan_error = NULL,
                       qianchuan_status = 2, qianchuan_review = ? WHERE id = ?""",
                    (output_path, json.dumps(quality, ensure_ascii=False), group_id),
                )
                await db.commit()
            await _broadcast({"type": "qianchuan_done", "group_id": group_id, "output_path": output_path})
        except Exception as e:
            msg = f"千川生成失败: {e}"
            logger.error(f"_qianchuan_generate_bg failed for group {group_id}: {e}")
            await _set_qianchuan_error(group_id, -1, msg)
            await _broadcast({"type": "qianchuan_error", "group_id": group_id, "error": msg})

@director_router.post("/generate-script", response_model=ScriptGenerationResponse)
async def generate_script(request: ScriptGenerationRequest):
    """为指定分组生成导演脚本"""
    await _clear_director_error(request.group_id)
    try:
        group_data = await _get_group_data(request.group_id)
        if not group_data:
            raise HTTPException(status_code=404, detail="分组不存在")

        srt_content = await _extract_srt_content(request.group_id)
        if not srt_content:
            raise HTTPException(status_code=400, detail="无可用的转录内容")

        result = await script_generator.generate_script(
            srt_content=srt_content,
            wig_model=group_data.get("wig_model", ""),
            wig_color=group_data.get("wig_color", ""),
            room_name=group_data.get("room_name", ""),
            script_type=request.script_type,
            vibe=request.vibe,
        )

        if result["success"]:
            await _save_director_script(request.group_id, result["script"], vibe=request.vibe)

        return ScriptGenerationResponse(**result)

    except HTTPException as e:
        await _set_director_error(request.group_id, e.detail)
        raise
    except Exception as e:
        msg = f"脚本生成失败: {e}"
        logger.error(f"Script generation failed for group {request.group_id}: {e}")
        await _set_director_error(request.group_id, msg)
        raise HTTPException(status_code=500, detail=msg)

class SetVibeRequest(BaseModel):
    group_id: int
    vibe: str


@director_router.post("/set-vibe")
async def set_vibe(request: SetVibeRequest):
    """保存分组的 vibe 选择"""
    from director_script import VIBE_CONFIGS
    if request.vibe not in VIBE_CONFIGS:
        raise HTTPException(status_code=422, detail=f"未知 vibe: {request.vibe}")
    import aiosqlite
    from db import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute(
            "UPDATE clip_groups SET vibe = ? WHERE id = ?",
            (request.vibe, request.group_id)
        )
        await db.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="分组不存在")
    return {"success": True, "group_id": request.group_id, "vibe": request.vibe}


@director_router.post("/toggle-mode")
async def toggle_director_mode(request: DirectorModeToggleRequest):
    """切换分组的导演模式状态"""
    
    try:
        import aiosqlite
        from db import DB_PATH
        
        async with aiosqlite.connect(DB_PATH) as db:
            # 检查分组是否存在
            async with db.execute(
                "SELECT id FROM clip_groups WHERE id = ?", 
                (request.group_id,)
            ) as cursor:
                if not await cursor.fetchone():
                    raise HTTPException(status_code=404, detail="分组不存在")
            
            # 更新模式
            mode = "director" if request.enabled else "classic"
            await db.execute(
                "UPDATE clip_groups SET editing_mode = ? WHERE id = ?",
                (mode, request.group_id)
            )
            await db.commit()
        
        return {
            "success": True,
            "group_id": request.group_id,
            "editing_mode": mode,
            "message": f"分组 {request.group_id} 已切换到 {mode} 模式"
        }
        
    except Exception as e:
        logger.error(f"Failed to toggle mode for group {request.group_id}: {e}")
        raise HTTPException(status_code=500, detail=f"模式切换失败: {str(e)}")

@director_router.get("/group/{group_id}/script")
async def get_group_script(group_id: int):
    """获取分组的导演脚本"""
    
    try:
        import aiosqlite
        from db import DB_PATH
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT director_script FROM clip_groups WHERE id = ?",
                (group_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="分组不存在")
                
                script = row[0]
                if not script:
                    return {"has_script": False, "message": "尚未生成脚本"}
                
                return {
                    "has_script": True,
                    "script": json.loads(script) if isinstance(script, str) else script
                }
                
    except Exception as e:
        logger.error(f"Failed to get script for group {group_id}: {e}")
        raise HTTPException(status_code=500, detail=f"获取脚本失败: {str(e)}")


class ScriptUpdateRequest(BaseModel):
    group_id: int
    script: Dict


@director_router.post("/update-script")
async def update_script(request: ScriptUpdateRequest):
    """手动编辑/审核后保存修改过的脚本。覆盖已有脚本，清除已生成的配音和视频（需重新生成）。"""
    import aiosqlite
    from db import DB_PATH

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Verify group exists
            async with db.execute(
                "SELECT id FROM clip_groups WHERE id = ?", (request.group_id,)
            ) as cur:
                if not await cur.fetchone():
                    raise HTTPException(status_code=404, detail="分组不存在")
            # Save edited script, clear downstream outputs so user must re-generate
            await db.execute(
                """UPDATE clip_groups
                   SET director_script = ?,
                       director_audio_path = NULL,
                       director_segments = NULL,
                       director_final_video = NULL,
                       director_status = 0,
                       director_error = NULL
                   WHERE id = ?""",
                (json.dumps(request.script, ensure_ascii=False), request.group_id),
            )
            await db.commit()
        return {"success": True, "message": "脚本已保存，请重新生成配音"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update script for group {request.group_id}: {e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")


@director_router.post("/generate-voiceover")
async def generate_voiceover(group_id: int, use_voice_cloning: bool = True):
    """为分组生成声音克隆配音"""
    await _clear_director_error(group_id)
    try:
        group_data = await _get_group_data(group_id)
        if not group_data:
            raise HTTPException(status_code=404, detail="分组不存在")

        script_data = await _get_group_script_data(group_id)
        if not script_data:
            raise HTTPException(status_code=400, detail="请先生成导演脚本")

        result = await voice_director.generate_voiceover(
            script=script_data,
            group_id=group_id,
            reference_audio_path=None,
        )

        if result["success"]:
            await _save_voiceover_data(group_id, result)
            await _broadcast({"type": "director_voice_done", "group_id": group_id})
        else:
            err = result.get("error", "配音生成失败")
            await _set_director_error(group_id, err)

        return {
            "success": result["success"],
            "audio_segments": result.get("audio_segments", []),
            "merged_audio_path": result.get("merged_audio_path"),
            "total_duration": result.get("total_duration", 0.0),
            "reference_audio_used": result.get("reference_audio_used"),
            "error": result.get("error"),
        }

    except HTTPException as e:
        await _set_director_error(group_id, e.detail)
        raise
    except Exception as e:
        msg = f"配音生成失败: {e}"
        logger.error(f"Voiceover generation failed for group {group_id}: {e}")
        await _set_director_error(group_id, msg)
        raise HTTPException(status_code=500, detail=msg)

@director_router.get("/group/{group_id}/voiceover")  
async def get_group_voiceover(group_id: int):
    """获取分组的配音信息"""
    
    try:
        import aiosqlite
        from db import DB_PATH
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT director_audio_path, director_segments FROM clip_groups WHERE id = ?",
                (group_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="分组不存在")
                
                audio_path, segments = row
                if not audio_path:
                    return {"has_voiceover": False, "message": "尚未生成配音"}
                
                return {
                    "has_voiceover": True,
                    "audio_path": audio_path,
                    "segments": json.loads(segments) if segments else []
                }
                
    except Exception as e:
        logger.error(f"Failed to get voiceover for group {group_id}: {e}")
        raise HTTPException(status_code=500, detail=f"获取配音失败: {str(e)}")

# Helper functions
async def _get_group_data(group_id: int) -> Optional[Dict]:
    """从数据库获取分组数据"""
    import aiosqlite
    from db import DB_PATH
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("""
                SELECT cg.id, cg.label, cg.wig_model, cg.wig_color, r.name as room_name
                FROM clip_groups cg
                LEFT JOIN rooms r ON cg.room_id = r.id  
                WHERE cg.id = ?
            """, (group_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "label": row[1],
                        "wig_model": row[2] or "",
                        "wig_color": row[3] or "",
                        "room_name": row[4] or ""
                    }
    except Exception as e:
        logger.error(f"Failed to get group data: {e}")
    return None

async def _extract_srt_content(group_id: int) -> Optional[str]:
    """提取分组的SRT转录内容"""
    import aiosqlite
    import os
    from db import DB_PATH
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # 获取分组内的录像文件
            async with db.execute("""
                SELECT filename FROM recordings 
                WHERE group_id = ? AND transcribed = 2
                LIMIT 3
            """, (group_id,)) as cursor:
                recordings = await cursor.fetchall()
        
        if not recordings:
            return None
            
        # 提取SRT纯文字（去掉序号和时间码），按句子合并
        text_lines: list[str] = []
        recordings_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")

        for (filename,) in recordings:
            srt_filename = os.path.splitext(filename)[0] + '.srt'
            srt_path = os.path.join(recordings_dir, srt_filename)
            if not os.path.exists(srt_path):
                continue
            try:
                with open(srt_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.isdigit() and '-->' not in line:
                            text_lines.append(line)
            except Exception as e:
                logger.warning(f"Failed to read SRT {srt_path}: {e}")

        if not text_lines:
            return None

        # 在句子边界截断，不超过 4000 字符，避免中途截断中文句子
        full_text = ''.join(text_lines)
        if len(full_text) <= 4000:
            return full_text

        # 找最近的句子结束符（。！？.!?）
        cutoff = full_text.rfind('。', 0, 4000)
        if cutoff == -1:
            cutoff = full_text.rfind('，', 0, 4000)
        if cutoff == -1:
            cutoff = 4000
        return full_text[:cutoff + 1]
        
    except Exception as e:
        logger.error(f"Failed to extract SRT content: {e}")
        return None

async def _save_director_script(group_id: int, script: Dict, vibe: str = "trendy"):
    """保存导演脚本和vibe到数据库"""
    import aiosqlite
    from db import DB_PATH

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE clip_groups SET director_script = ?, vibe = ?, director_error = NULL WHERE id = ?",
                (json.dumps(script), vibe, group_id)
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to save script: {e}")


async def _set_director_error(group_id: int, error: str):
    """将错误信息写入数据库，供前端展示"""
    import aiosqlite
    from db import DB_PATH
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE clip_groups SET director_error = ? WHERE id = ?",
                (error[:500], group_id)
            )
            await db.commit()
    except Exception:
        pass


async def _clear_director_error(group_id: int):
    await _set_director_error(group_id, None)

async def _get_group_script_data(group_id: int) -> Optional[Dict]:
    """获取分组的导演脚本数据"""
    import aiosqlite
    from db import DB_PATH
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT director_script FROM clip_groups WHERE id = ?",
                (group_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[0]:
                    return json.loads(row[0])
    except Exception as e:
        logger.error(f"Failed to get script data: {e}")
    return None

@director_router.post("/compose-video")
async def compose_video(group_id: int, video_style: str = "dynamic"):
    """
    步骤3：根据脚本匹配录像片段 + 合并配音，生成最终导演模式视频。
    需要先完成步骤1(generate-script)和步骤2(generate-voiceover)。
    立即返回，后台异步执行；完成后通过 WebSocket 推送 director_done / director_error。
    """
    await _clear_director_error(group_id)
    import aiosqlite
    import os
    from db import DB_PATH

    # ── 同步校验（快速，不阻塞）──────────────────────────────────────────────────
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT director_script, director_audio_path, director_segments FROM clip_groups WHERE id = ?",
            (group_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="分组不存在")

    script_raw, audio_path, segments_raw = row
    if not script_raw:
        raise HTTPException(status_code=400, detail="请先生成导演脚本（步骤1）")
    if not audio_path:
        raise HTTPException(status_code=400, detail="请先生成配音（步骤2）")
    if not os.path.exists(audio_path):
        raise HTTPException(status_code=400, detail=f"配音文件不存在: {audio_path}")

    try:
        script = json.loads(script_raw) if isinstance(script_raw, str) else script_raw
    except Exception:
        raise HTTPException(status_code=400, detail="脚本格式错误，请重新生成")

    scenes = script.get("scenes", [])
    if not scenes:
        raise HTTPException(status_code=400, detail="脚本中没有场景数据")

    # 优先使用实际 TTS 音频时长（保证视频和语音同步）
    audio_dur_by_scene: Dict[int, float] = {}
    if segments_raw:
        try:
            segs = json.loads(segments_raw) if isinstance(segments_raw, str) else segments_raw
            audio_dur_by_scene = {s["scene_id"]: s["duration"] for s in (segs or []) if s.get("scene_id")}
        except Exception:
            pass

    script_segments = [
        {
            "text": scene.get("voiceover_text", scene.get("description", "")),
            "visual_keywords": scene.get("visual_requirements", []),
            "duration": max(3.0, audio_dur_by_scene.get(
                scene.get("scene_id", 0),
                scene.get("timestamp_end", 15) - scene.get("timestamp_start", 0),
            )),
            "scene_type": scene.get("scene_type", ""),
        }
        for scene in scenes
    ]
    recordings_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "recordings"))

    # ── 后台执行（匹配 + 编码，可能数分钟）────────────────────────────────────────
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE clip_groups SET director_status = 1, director_error = NULL WHERE id = ?", (group_id,)
        )
        await db.commit()
    asyncio.create_task(_compose_video_bg(group_id, script_segments, audio_path, recordings_dir, video_style))
    return {"started": True, "message": "视频合成已启动，完成后自动通知"}


async def _compose_video_bg(
    group_id: int,
    script_segments: List[Dict],
    audio_path: str,
    recordings_dir: str,
    video_style: str,
) -> None:
    """后台合成任务：语义匹配 → 视频编码 → 存库 → 广播。"""
    import aiosqlite
    import os
    from db import DB_PATH

    async with _COMPOSE_SEM:  # 同时最多 1 个合成任务
        try:
            matcher = get_matcher(DB_PATH)
            matched_segments = await matcher.match_segments_to_recordings(script_segments, group_id)
            if not matched_segments:
                raise RuntimeError("未能匹配到任何录像片段，请确认分组内有已转录录像（clipped=2）")

            composer = DirectorVideoComposer(recordings_dir)
            config = {"video_style": video_style}
            output_path = await composer.compose_final_video(matched_segments, audio_path, config)
            if not output_path:
                raise RuntimeError("视频合成失败，请查看后端日志")

            # Keep API/manual director workflow aligned with the automatic
            # pipeline: <28s is too short to rescue; 28s~30.5s gets padded so
            # Douyin never rejects near-boundary 29.x clips as under 30s.
            from transcribe import (
                MIN_FINAL_VIDEO_DURATION,
                TARGET_PUBLISH_DURATION,
                _get_video_duration,
                _pad_video_to_min_duration,
            )
            from final_video import postprocess_final_video

            _dur = await _get_video_duration(output_path)
            if _dur <= 0:
                raise RuntimeError("导演版视频时长探测失败")
            if _dur < TARGET_PUBLISH_DURATION:
                padded_path = await _pad_video_to_min_duration(output_path, _dur)
                if padded_path:
                    logger.info(
                        "Director API compose group %s: padded video from %.1fs to >=%.1fs",
                        group_id,
                        _dur,
                        TARGET_PUBLISH_DURATION,
                    )
                    output_path = padded_path
                else:
                    try:
                        os.remove(output_path)
                    except Exception:
                        pass
                    raise RuntimeError(f"导演版视频时长 {_dur:.1f}s < {MIN_FINAL_VIDEO_DURATION:.0f}s 最低要求")

            processed_path = await postprocess_final_video(output_path)
            if not processed_path:
                raise RuntimeError("导演版4K/50fps背景补齐后处理失败")
            output_path = processed_path

            # 清理配音文件（已嵌入视频）
            try:
                if os.path.isfile(audio_path):
                    os.remove(audio_path)
            except Exception:
                pass

            # 保存路径到 DB，同时标记 director_status=2
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """UPDATE clip_groups SET
                       director_final_video = ?, director_error = NULL,
                       director_status = 2, merge_status = 2, merged_at = datetime('now')
                       WHERE id = ?""",
                    (output_path, group_id)
                )
                await db.commit()

            await _broadcast({
                "type": "director_done",
                "group_id": group_id,
                "matched_count": len(matched_segments),
            })

        except Exception as e:
            msg = f"合成失败: {e}"
            logger.error(f"_compose_video_bg failed for group {group_id}: {e}")
            await _set_director_error(group_id, msg)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE clip_groups SET director_status = -1 WHERE id = ?", (group_id,)
                )
                await db.commit()
            await _broadcast({"type": "director_error", "group_id": group_id, "error": msg})


async def _save_voiceover_data(group_id: int, voiceover_result: Dict):
    """保存配音数据到数据库"""
    import aiosqlite
    from db import DB_PATH
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE clip_groups SET director_audio_path = ?, director_segments = ? WHERE id = ?",
                (
                    voiceover_result.get("merged_audio_path"),
                    json.dumps(voiceover_result.get("audio_segments", [])),
                    group_id
                )
            )
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to save voiceover data: {e}")
