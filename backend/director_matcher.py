"""
导演模式语义匹配模块

使用本地sentence-transformers进行语义匹配，将AI脚本片段与录像内容匹配
"""

import asyncio
import logging
import os
import numpy as np
import aiosqlite
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json
import re

logger = logging.getLogger(__name__)

# 延迟导入sentence-transformers，因为可能需要安装
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    logger.warning("sentence-transformers not available, will use fallback matching")
    SENTENCE_TRANSFORMERS_AVAILABLE = False

# Module-level singleton — model loading takes ~30s, only do it once
_matcher_instance: Optional["SemanticMatcher"] = None


def get_matcher(db_path: str) -> "SemanticMatcher":
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = SemanticMatcher(db_path)
    else:
        _matcher_instance.db_path = db_path  # update path, keep loaded model
    return _matcher_instance


class SemanticMatcher:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.model = None
        
        # 初始化sentence-transformers模型
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
                logger.info("Loaded sentence-transformers model successfully")
            except Exception as e:
                logger.warning(f"Failed to load sentence-transformers model: {e}")
                self.model = None
        
        # 预定义关键词映射（用于回退匹配）
        self.keyword_patterns = {
            '假发效果': ['假发', '效果', '自然', '真实'],
            '上头效果': ['戴上', '上头', '佩戴', '效果'],
            '颜色展示': ['颜色', '色彩', '显白', '发色'],
            '质感特写': ['质感', '柔顺', '光泽', '顺滑'],
            '对比效果': ['对比', '前后', '变化', '差别'],
            '产品特写': ['产品', '细节', '特写', '展示'],
            '购买引导': ['购买', '下单', '链接', '小黄车'],
            '场景展示': ['日常', '约会', '工作', '场合']
        }
    
    async def match_segments_to_recordings(self, script_segments: List[Dict],
                                         group_id: int) -> List[Dict]:
        """
        将脚本片段匹配到最佳录像片段，同一录像不重复使用（尽力而为）。
        """
        try:
            recordings = await self._get_group_recordings(group_id)
            if not recordings:
                logger.warning(f"No recordings found for group {group_id}")
                return []

            # Phase 1: score all segments in parallel (CPU-bound embedding via thread pool)
            best_matches = await asyncio.gather(*[
                self._find_best_recording_match(seg, recordings)
                for seg in script_segments
            ])

            # Phase 2: assign start offsets sequentially (each segment consumes footage)
            matched_segments = []
            used_offsets: Dict[int, float] = {}

            for i, (segment, best_match) in enumerate(zip(script_segments, best_matches)):
                logger.info(f"Segment {i+1}/{len(script_segments)}: {segment.get('text', '')[:50]!r} → score={best_match.get('score', 0):.2f}")

                seg_duration = segment.get('duration', 15.0)
                rec_id = best_match.get('recording_id')
                rec_dur = next(
                    (r['duration'] for r in recordings if r['recording_id'] == rec_id),
                    30.0
                )

                # Advance start_time to avoid repeating footage already used
                start = used_offsets.get(rec_id, 0.0)
                # If remaining footage is insufficient, wrap around
                if start + seg_duration > rec_dur:
                    start = 0.0

                used_offsets[rec_id] = start + seg_duration

                matched_segments.append({
                    'script_segment': segment,
                    'matched_recording_id': rec_id,
                    'matched_start_time': start,
                    'matched_duration': min(seg_duration, rec_dur - start),
                    'confidence_score': best_match.get('score', 0.0),
                    'match_reason': best_match.get('reason', 'automatic'),
                })

            logger.info(f"Matched {len(matched_segments)} segments for group {group_id}")
            return matched_segments

        except Exception as e:
            logger.error(f"Segment matching failed for group {group_id}: {e}")
            return await self._get_fallback_matches(script_segments, group_id)
    
    async def _get_group_recordings(self, group_id: int) -> List[Dict]:
        """获取分组的录像数据及转录文本（单次查询，避免N+1）"""
        recordings = []
        recordings_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")

        try:
            from datetime import datetime
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT id, filename, start_time, end_time FROM recordings"
                    " WHERE group_id = ? AND clipped = 2 ORDER BY start_time",
                    (group_id,),
                ) as cursor:
                    rows = await cursor.fetchall()

            for row in rows:
                # 计算时长
                duration = 30.0
                if row["end_time"]:
                    try:
                        start = datetime.fromisoformat(row["start_time"])
                        end = datetime.fromisoformat(row["end_time"])
                        duration = max(1.0, (end - start).total_seconds())
                    except Exception:
                        pass

                srt_path = os.path.join(
                    recordings_dir,
                    os.path.splitext(row["filename"])[0] + ".srt",
                )
                transcript_text = ""
                if os.path.exists(srt_path):
                    try:
                        with open(srt_path, encoding="utf-8") as f:
                            lines = [
                                line.strip() for line in f
                                if line.strip() and not line.strip().isdigit() and "-->" not in line
                            ]
                            transcript_text = " ".join(lines)
                    except Exception as e:
                        logger.warning(f"Failed to read SRT {srt_path}: {e}")

                recordings.append({
                    "recording_id": row["id"],
                    "filename": row["filename"],
                    "transcript_text": transcript_text,
                    "duration": duration,
                })

        except Exception as e:
            logger.error(f"Failed to get recordings for group {group_id}: {e}")

        return recordings
    
    async def _find_best_recording_match(self, segment: Dict,
                                       recordings: List[Dict]) -> Dict:
        """
        为单个脚本片段找到最匹配的录像。
        综合得分 = 0.6 * semantic + 0.4 * keyword（各自归一化到0-1）
        """
        if not recordings:
            return {'score': 0.0, 'reason': 'no_recordings'}

        segment_text = segment.get('text', '')
        visual_keywords = segment.get('visual_keywords', [])

        scores: List[Tuple[float, str, Dict]] = []

        try:
            loop = asyncio.get_event_loop()
            for recording in recordings:
                transcript = recording.get('transcript_text', '')

                sem_score = 0.0
                if self.model and segment_text and transcript:
                    # Run CPU-bound embedding in thread pool to avoid blocking the event loop
                    sem_score = await loop.run_in_executor(
                        None, self._calculate_semantic_similarity, segment_text, transcript
                    )

                kw_score = self._calculate_keyword_match_score(visual_keywords, transcript)

                # Weighted combination; if no semantic model, rely on keywords alone
                if self.model and segment_text:
                    combined = 0.6 * sem_score + 0.4 * kw_score
                else:
                    combined = kw_score if kw_score > 0 else 0.01  # slight non-zero to avoid all-ties

                scores.append((combined, f'sem={sem_score:.2f} kw={kw_score:.2f}', recording))

        except Exception as e:
            logger.warning(f"Error in matching calculation: {e}")

        if not scores:
            return {
                'recording_id': recordings[0]['recording_id'],
                'score': 0.0, 'reason': 'fallback_first',
            }

        scores.sort(key=lambda x: x[0], reverse=True)
        best_score, best_reason, best_recording = scores[0]

        return {
            'recording_id': best_recording['recording_id'],
            'duration': min(best_recording.get('duration', 15.0), segment.get('duration', 15.0)),
            'score': best_score,
            'reason': best_reason,
        }
    
    def _calculate_semantic_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的语义相似度（同步，供 run_in_executor 调用）"""
        if not self.model or not text1 or not text2:
            return 0.0
        try:
            embeddings = self.model.encode([text1, text2])
            similarity = np.dot(embeddings[0], embeddings[1]) / (
                np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
            )
            return max(0.0, float(similarity))
        except Exception as e:
            logger.warning(f"Semantic similarity calculation failed: {e}")
            return 0.0
    
    def _calculate_keyword_match_score(self, visual_keywords: List[str],
                                     transcript: str) -> float:
        """计算关键词匹配度。无关键词时返回中性分0.3，让语义分决定排序。"""
        if not visual_keywords:
            return 0.3  # 无关键词：中性，不拉低综合分
        if not transcript:
            return 0.0
        
        transcript_lower = transcript.lower()
        total_score = 0.0
        
        for keyword in visual_keywords:
            keyword_lower = keyword.lower()
            
            # 直接匹配
            if keyword_lower in transcript_lower:
                total_score += 1.0
                continue
            
            # 模式匹配（基于预定义映射）
            patterns = self.keyword_patterns.get(keyword, [keyword])
            for pattern in patterns:
                if pattern.lower() in transcript_lower:
                    total_score += 0.8  # 模式匹配权重稍低
                    break
        
        # 归一化分数
        return total_score / len(visual_keywords) if visual_keywords else 0.0
    
    async def _get_fallback_matches(self, script_segments: List[Dict],
                                  group_id: int) -> List[Dict]:
        """回退匹配：按顺序轮转分配录像，每段从不同偏移位置开始避免重复画面"""
        recordings = await self._get_group_recordings(group_id)
        if not recordings:
            return []

        matched_segments = []
        used_offsets: Dict[int, float] = {}

        for i, segment in enumerate(script_segments):
            rec = recordings[i % len(recordings)]
            rid = rec['recording_id']
            seg_dur = segment.get('duration', 15.0)
            rec_dur = rec.get('duration', 30.0)

            start = used_offsets.get(rid, 0.0)
            if start + seg_dur > rec_dur:
                start = 0.0
            used_offsets[rid] = start + seg_dur

            matched_segments.append({
                'script_segment': segment,
                'matched_recording_id': rid,
                'matched_start_time': start,
                'matched_duration': min(seg_dur, rec_dur - start),
                'confidence_score': 0.1,
                'match_reason': 'fallback_sequential',
            })

        return matched_segments
# Alias for backward compatibility
DirectorMatcher = SemanticMatcher
