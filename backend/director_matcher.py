"""
导演模式语义匹配模块

使用本地sentence-transformers进行语义匹配，将AI脚本片段与录像SRT段落对齐。
核心改进：用 SRT 时间戳定视频切点，保证主播讲完整一个语义点再切，避免话说到一半被截断。
"""

import asyncio
import logging
import os
import re
import numpy as np
import aiosqlite
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import json

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


# ── SRT 解析工具 ──────────────────────────────────────────────────────────────

def _parse_srt_entries(srt_path: str) -> List[Dict]:
    """解析 SRT 文件为结构化段落列表 [{idx, start, end, text}]"""
    if not os.path.exists(srt_path):
        return []
    try:
        with open(srt_path, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    entries = []
    for block in re.split(r"\n{2,}", content.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0])
            arrow = lines[1].split("-->")
            start = _ts_to_sec(arrow[0])
            end = _ts_to_sec(arrow[1])
            text = " ".join(lines[2:])
            entries.append({"idx": idx, "start": start, "end": end, "text": text})
        except (ValueError, IndexError):
            continue
    return entries


def _ts_to_sec(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


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
        将脚本片段匹配到最佳录像片段。
        
        核心逻辑：用 SRT 时间戳精确定位视频切点，而不是盲目顺序推进。
        每个 script segment 的 voiceover_text 在录像 SRT 中做语义搜索，
        找到最匹配的连续 SRT 段落，取其完整时间范围作为切点。
        这样保证主播讲完一个完整语义点再切，不会话说到一半被截断。
        """
        try:
            recordings = await self._get_group_recordings(group_id)
            if not recordings:
                logger.warning(f"No recordings found for group {group_id}")
                return []

            # 已使用的 SRT entry 索引集合（避免重复使用同一段内容）
            used_srt_indices: Dict[int, set] = {}  # rec_id -> set of srt entry indices

            matched_segments = []

            for i, segment in enumerate(script_segments):
                seg_text = segment.get('voiceover_text', '') or segment.get('text', '')
                seg_duration = segment.get('duration', 15.0)
                
                logger.info(f"Matching segment {i+1}/{len(script_segments)}: {seg_text[:50]!r}")

                # 尝试 SRT 语义匹配
                best_match = await self._find_best_srt_match(
                    seg_text, seg_duration, recordings, used_srt_indices
                )

                if best_match:
                    rec_id = best_match['recording_id']
                    # 标记已用的 SRT entries
                    if rec_id not in used_srt_indices:
                        used_srt_indices[rec_id] = set()
                    used_srt_indices[rec_id].update(best_match.get('used_indices', []))

                    matched_segments.append({
                        'script_segment': segment,
                        'matched_recording_id': rec_id,
                        'matched_start_time': best_match['start_time'],
                        'matched_duration': best_match['duration'],
                        'confidence_score': best_match['score'],
                        'match_reason': best_match['reason'],
                    })
                    logger.info(
                        f"  → rec {rec_id}, t={best_match['start_time']:.1f}s-"
                        f"{best_match['start_time']+best_match['duration']:.1f}s, "
                        f"score={best_match['score']:.2f} ({best_match['reason']})"
                    )
                else:
                    # 回退：顺序分配
                    fallback = await self._fallback_match_single(
                        segment, recordings, used_srt_indices
                    )
                    matched_segments.append(fallback)
                    logger.info(f"  → fallback: rec {fallback['matched_recording_id']}")

            logger.info(f"Matched {len(matched_segments)} segments for group {group_id}")
            return matched_segments

        except Exception as e:
            logger.error(f"Segment matching failed for group {group_id}: {e}")
            return await self._get_fallback_matches(script_segments, group_id)

    async def _find_best_srt_match(
        self,
        segment_text: str,
        segment_duration: float,
        recordings: List[Dict],
        used_srt_indices: Dict[int, set],
    ) -> Optional[Dict]:
        """
        在所有录像的 SRT 段落中找到与 segment_text 最语义匹配的连续段落。
        
        返回: {recording_id, start_time, duration, score, reason, used_indices}
        或 None（找不到好的匹配时）
        """
        if not segment_text:
            return None

        best_result = None
        best_score = 0.3  # 最低阈值：score < 0.3 认为匹配不可靠

        loop = asyncio.get_event_loop()

        for rec in recordings:
            rec_id = rec['recording_id']
            srt_entries = rec.get('srt_entries', [])
            if not srt_entries:
                continue

            used_set = used_srt_indices.get(rec_id, set())
            
            # 在该录像的 SRT entries 中寻找最佳连续段落（窗口 1-5 条 SRT）
            result = await loop.run_in_executor(
                None, self._find_best_window_in_srt,
                segment_text, srt_entries, used_set, segment_duration
            )

            if result and result['score'] > best_score:
                best_score = result['score']
                best_result = {
                    'recording_id': rec_id,
                    'start_time': result['start_time'],
                    'duration': result['duration'],
                    'score': result['score'],
                    'reason': f"srt_semantic={result['score']:.2f}",
                    'used_indices': result['used_indices'],
                }

        return best_result

    def _find_best_window_in_srt(
        self,
        query_text: str,
        srt_entries: List[Dict],
        used_indices: set,
        target_duration: float,
    ) -> Optional[Dict]:
        """
        滑动窗口搜索：在 SRT entries 中找到与 query_text 最匹配的连续段落。
        窗口大小 1-5 条 SRT entry，优先选择：
        1. 语义相似度最高
        2. 时长接近 target_duration（但不强制，保证语义完整性优先）
        3. 未被之前的 segment 使用过
        
        返回: {start_time, duration, score, used_indices} 或 None
        """
        if not self.model or not srt_entries:
            return self._keyword_window_search(query_text, srt_entries, used_indices, target_duration)

        n = len(srt_entries)
        candidates = []

        # 预编码 query
        try:
            query_emb = self.model.encode([query_text])[0]
        except Exception:
            return self._keyword_window_search(query_text, srt_entries, used_indices, target_duration)

        # 滑动窗口：1-5 条连续 SRT entries
        for window_size in range(1, min(6, n + 1)):
            for start_idx in range(n - window_size + 1):
                end_idx = start_idx + window_size - 1
                
                # 检查是否有已用的 entry（轻度惩罚，不完全排除）
                indices = set(range(start_idx, end_idx + 1))
                overlap_ratio = len(indices & used_indices) / len(indices) if indices else 0
                if overlap_ratio > 0.5:
                    continue  # 超过一半已用，跳过

                # 拼接窗口文本
                window_text = " ".join(srt_entries[j]['text'] for j in range(start_idx, end_idx + 1))
                window_start = srt_entries[start_idx]['start']
                window_end = srt_entries[end_idx]['end']
                window_dur = window_end - window_start

                # 时长过短（<2s）或过长（>30s）的窗口跳过
                if window_dur < 2.0 or window_dur > 30.0:
                    continue

                # 语义相似度
                try:
                    window_emb = self.model.encode([window_text])[0]
                    similarity = float(np.dot(query_emb, window_emb) / (
                        np.linalg.norm(query_emb) * np.linalg.norm(window_emb)
                    ))
                except Exception:
                    continue

                # 时长匹配奖励（时长越接近 target 越好，但不惩罚超出）
                dur_ratio = min(window_dur, target_duration) / max(window_dur, target_duration)
                dur_bonus = 0.1 * dur_ratio  # 最多加 0.1 分

                # 重叠惩罚
                overlap_penalty = 0.2 * overlap_ratio

                final_score = similarity + dur_bonus - overlap_penalty

                candidates.append({
                    'start_time': window_start,
                    'duration': window_dur,
                    'score': final_score,
                    'used_indices': list(indices),
                    'window_size': window_size,
                })

        if not candidates:
            return self._keyword_window_search(query_text, srt_entries, used_indices, target_duration)

        # 选最高分
        candidates.sort(key=lambda x: x['score'], reverse=True)
        best = candidates[0]
        
        # 确保语义完整性：如果最佳窗口末尾的 SRT entry 像是话说到一半
        # （下一条 SRT 紧跟且有连续性），尝试扩展
        best = self._extend_for_completeness(best, srt_entries, used_indices)
        
        return best

    def _extend_for_completeness(self, match: Dict, srt_entries: List[Dict], used_indices: set) -> Dict:
        """
        检查匹配窗口末尾是否话说到一半，如果是则扩展到完整语义。
        判断标准：下一条 SRT 的 start - 当前窗口 end < 1.5s（说明是连续讲话）
        且下一条文本以连词/续句词开头或当前末尾无句号。
        最多扩展 2 条。
        """
        indices = match['used_indices']
        if not indices:
            return match
        
        last_idx = max(indices)
        n = len(srt_entries)
        extended = list(indices)
        
        # 最多向后扩展 2 条
        for _ in range(2):
            next_idx = last_idx + 1
            if next_idx >= n:
                break
            if next_idx in used_indices:
                break
            
            # 间隔检查：下一条 SRT 紧跟（gap < 1.5s）
            gap = srt_entries[next_idx]['start'] - srt_entries[last_idx]['end']
            if gap > 1.5:
                break
            
            # 语义连续性检查
            cur_text = srt_entries[last_idx]['text']
            next_text = srt_entries[next_idx]['text']
            
            # 当前句子未完结的标志
            incomplete = (
                cur_text.rstrip().endswith(('的', '了', '这', '那', '就', '还', '把', '在', '是'))
                or not cur_text.rstrip().endswith(('。', '！', '？', '…', '.', '!', '?'))
            )
            # 下一句是续接的标志
            continues = (
                next_text.lstrip().startswith(('然后', '所以', '而且', '但是', '就是', '这个', '那个', '它'))
                or gap < 0.3  # 间隔极短，基本是连续讲话
            )
            
            if incomplete or continues:
                extended.append(next_idx)
                last_idx = next_idx
            else:
                break
        
        if len(extended) > len(indices):
            new_end = srt_entries[max(extended)]['end']
            new_start = srt_entries[min(extended)]['start']
            match = {
                **match,
                'start_time': new_start,
                'duration': new_end - new_start,
                'used_indices': extended,
            }
        
        return match

    def _keyword_window_search(
        self,
        query_text: str,
        srt_entries: List[Dict],
        used_indices: set,
        target_duration: float,
    ) -> Optional[Dict]:
        """
        关键词回退匹配：当 sentence-transformers 不可用时。
        在 SRT entries 中找关键词重叠最多的连续窗口。
        """
        if not srt_entries:
            return None

        query_words = set(query_text)
        n = len(srt_entries)
        best = None
        best_score = 0.0

        for window_size in range(1, min(5, n + 1)):
            for start_idx in range(n - window_size + 1):
                end_idx = start_idx + window_size - 1
                indices = set(range(start_idx, end_idx + 1))
                
                if len(indices & used_indices) / len(indices) > 0.5:
                    continue

                window_text = " ".join(srt_entries[j]['text'] for j in range(start_idx, end_idx + 1))
                window_start = srt_entries[start_idx]['start']
                window_end = srt_entries[end_idx]['end']
                window_dur = window_end - window_start

                if window_dur < 2.0 or window_dur > 30.0:
                    continue

                # 简单字符重叠度
                overlap = len(set(window_text) & query_words)
                score = overlap / max(len(query_words), 1)

                if score > best_score:
                    best_score = score
                    best = {
                        'start_time': window_start,
                        'duration': window_dur,
                        'score': score,
                        'used_indices': list(indices),
                    }

        return best if best and best_score > 0.2 else None

    async def _get_group_recordings(self, group_id: int) -> List[Dict]:
        """获取分组的录像数据及 SRT 分段信息（保留每条 SRT 的时间戳）"""
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
                
                # 解析 SRT 为结构化段落（保留时间戳）
                srt_entries = _parse_srt_entries(srt_path)
                # 同时保留全文拼接（向后兼容）
                transcript_text = " ".join(e['text'] for e in srt_entries)

                recordings.append({
                    "recording_id": row["id"],
                    "filename": row["filename"],
                    "transcript_text": transcript_text,
                    "srt_entries": srt_entries,
                    "duration": duration,
                })

        except Exception as e:
            logger.error(f"Failed to get recordings for group {group_id}: {e}")

        return recordings

    async def _fallback_match_single(
        self,
        segment: Dict,
        recordings: List[Dict],
        used_srt_indices: Dict[int, set],
    ) -> Dict:
        """单个 segment 的回退匹配：录像级语义匹配 + 顺序偏移"""
        seg_text = segment.get('voiceover_text', '') or segment.get('text', '')
        seg_duration = segment.get('duration', 15.0)

        # 找最匹配的录像
        best_rec = recordings[0] if recordings else None
        best_score = 0.0

        if self.model and seg_text:
            loop = asyncio.get_event_loop()
            for rec in recordings:
                transcript = rec.get('transcript_text', '')
                if transcript:
                    score = await loop.run_in_executor(
                        None, self._calculate_semantic_similarity, seg_text, transcript
                    )
                    if score > best_score:
                        best_score = score
                        best_rec = rec

        if not best_rec:
            best_rec = recordings[0]

        rec_id = best_rec['recording_id']
        rec_dur = best_rec.get('duration', 30.0)

        # 找该录像中最后使用的位置之后开始
        used = used_srt_indices.get(rec_id, set())
        srt_entries = best_rec.get('srt_entries', [])
        
        if srt_entries and used:
            # 从已用的最后一个 entry 之后开始
            last_used = max(used) if used else -1
            start_entry = last_used + 1
            if start_entry < len(srt_entries):
                start_time = srt_entries[start_entry]['start']
                # 向后取够 seg_duration 的 entries
                end_time = start_time + seg_duration
                for j in range(start_entry, len(srt_entries)):
                    if srt_entries[j]['end'] >= end_time:
                        end_time = srt_entries[j]['end']
                        break
                duration = min(end_time - start_time, rec_dur - start_time)
            else:
                start_time = 0.0
                duration = min(seg_duration, rec_dur)
        else:
            start_time = 0.0
            duration = min(seg_duration, rec_dur)

        return {
            'script_segment': segment,
            'matched_recording_id': rec_id,
            'matched_start_time': start_time,
            'matched_duration': max(duration, 3.0),  # 至少 3 秒
            'confidence_score': best_score,
            'match_reason': 'fallback_sequential',
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
