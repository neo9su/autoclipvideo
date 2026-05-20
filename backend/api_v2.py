"""
导演模式API路由 - v2版本
提供导演模式相关的所有接口
"""
import asyncio
import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from director_script import DirectorScriptGenerator
from voice_director import VoiceDirector
from director_matcher import SemanticMatcher, get_matcher
from director_video import DirectorVideoComposer

logger = logging.getLogger(__name__)

# 创建导演模式路由
director_router = APIRouter(prefix="/api/v2/director", tags=["director"])

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
        "version": "2.0.0",
    }

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