# 抖音录屏项目双模式并行系统设计文档

## 核心架构设计

```
前端界面
├── 模式选择器 (每个分组/视频独立选择)
├── 经典模式界面 (完全保留，零影响)
└── 导演模式界面 (新增，独立UI流程)

后端路由
├── /api/v1/* (经典模式，保持不变)
└── /api/v2/* (导演模式，新增路径群)

数据共享层
├── 同一套数据库 (recordings, groups等)
├── 共享转录服务 (GPU whisper)
├── 共享存储 (视频文件、缩略图等)
└── 模式标记字段 (editing_mode, director_config)

处理引擎
├── 经典模式: editor.py + analyzer.py (保持不变)
└── 导演模式: director_engine.py (新增核心处理引擎)
```

## 数据库扩展设计

### 非破坏性字段添加

```sql
-- 分组表扩展
ALTER TABLE clip_groups ADD COLUMN editing_mode TEXT DEFAULT 'classic'; -- 'classic' | 'director'
ALTER TABLE clip_groups ADD COLUMN director_config TEXT; -- JSON配置
ALTER TABLE clip_groups ADD COLUMN director_status INTEGER DEFAULT 0; -- 0:未处理 1:处理中 2:已完成 -1:失败
ALTER TABLE clip_groups ADD COLUMN director_script TEXT; -- AI生成的脚本内容
ALTER TABLE clip_groups ADD COLUMN director_segments TEXT; -- JSON: 语义匹配的片段信息
ALTER TABLE clip_groups ADD COLUMN director_audio_path TEXT; -- TTS音频路径
ALTER TABLE clip_groups ADD COLUMN director_final_video TEXT; -- 导演模式最终视频路径

-- 录像表扩展（可选，用于单个视频的模式选择）
ALTER TABLE recordings ADD COLUMN preferred_editing_mode TEXT DEFAULT 'classic';
```

## API路由设计

### V2 API 路径群 (导演模式专用)

```
/api/v2/groups/{id}/set-director-mode     POST  设置分组为导演模式
/api/v2/groups/{id}/director-config       GET   获取导演模式配置
/api/v2/groups/{id}/director-config       PUT   更新导演模式配置
/api/v2/groups/{id}/generate-script       POST  生成AI脚本
/api/v2/groups/{id}/director-process      POST  开始导演模式处理
/api/v2/groups/{id}/director-status       GET   获取导演模式处理状态
/api/v2/groups/{id}/director-preview      GET   预览导演模式结果
/api/v2/groups/{id}/switch-to-classic     POST  切换回经典模式
```

## 前端界面设计

### 模式选择器组件
```vue
<template>
  <div class="mode-selector">
    <div class="mode-tabs">
      <button :class="['mode-tab', mode === 'classic' && 'active']" 
              @click="switchMode('classic')">
        经典模式
      </button>
      <button :class="['mode-tab', mode === 'director' && 'active']"
              @click="switchMode('director')">
        导演模式 <span class="beta-tag">AI</span>
      </button>
    </div>
    <div class="mode-indicator">
      <span :class="['mode-dot', modeClass]"></span>
      <span>{{ modeLabel }}</span>
    </div>
  </div>
</template>
```

### 导演模式处理界面
```vue
<template>
  <div class="director-panel" v-if="group.editing_mode === 'director'">
    <div class="director-steps">
      <div class="step" :class="step >= 1 && 'active'">1. AI脚本生成</div>
      <div class="step" :class="step >= 2 && 'active'">2. 语义匹配</div>
      <div class="step" :class="step >= 3 && 'active'">3. TTS配音</div>
      <div class="step" :class="step >= 4 && 'active'">4. 视频合成</div>
    </div>
    <!-- 详细处理状态和控制按钮 -->
  </div>
</template>
```

## 导演模式核心处理引擎

### 1. AI脚本生成模块 (director_script.py)

```python
import boto3
from typing import List, Dict
import json

class DirectorScriptGenerator:
    def __init__(self):
        self.bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    
    async def generate_script(self, group_data: Dict) -> Dict:
        """基于分组数据生成导演脚本"""
        prompt = self._build_script_prompt(group_data)
        
        response = await self._call_bedrock_claude(prompt)
        script = self._parse_script_response(response)
        
        return {
            'script_text': script.get('text'),
            'segments': script.get('segments', []),
            'style': script.get('style', 'professional'),
            'duration_estimate': script.get('duration', 60)
        }
    
    def _build_script_prompt(self, group_data: Dict) -> str:
        """构建脚本生成提示词"""
        return f"""
        你是一个专业的短视频脚本创作师。请基于以下信息生成一个吸引人的短视频脚本：
        
        产品信息：
        - 款式：{group_data.get('wig_model', '未知')}
        - 颜色：{group_data.get('wig_color', '未知')}
        - 直播间：{group_data.get('room_name', '未知')}
        
        可用素材：{len(group_data.get('recordings', []))} 段录像
        
        要求：
        1. 生成60-90秒的脚本
        2. 突出产品特色和使用场景
        3. 分段标记需要匹配的视觉内容
        4. 语言活泼有感染力
        
        返回JSON格式：
        {{
            "text": "完整脚本文本",
            "segments": [
                {{"text": "分段文本1", "visual_keywords": ["关键词1", "关键词2"]}},
                {{"text": "分段文本2", "visual_keywords": ["关键词3", "关键词4"]}}
            ],
            "style": "professional|casual|energetic",
            "duration": 60
        }}
        """
```

### 2. 语义匹配模块 (director_matcher.py)

```python
from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List, Dict, Tuple
import sqlite3

class SemanticMatcher:
    def __init__(self):
        # 使用本地sentence-transformers模型
        self.model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    
    async def match_segments_to_recordings(self, script_segments: List[Dict], 
                                         recordings: List[Dict]) -> List[Dict]:
        """将脚本片段匹配到最佳录像片段"""
        matched_segments = []
        
        for segment in script_segments:
            best_match = await self._find_best_recording_match(segment, recordings)
            matched_segments.append({
                'script_segment': segment,
                'matched_recording': best_match,
                'confidence_score': best_match.get('score', 0.0)
            })
        
        return matched_segments
    
    async def _find_best_recording_match(self, segment: Dict, 
                                       recordings: List[Dict]) -> Dict:
        """为单个脚本片段找到最匹配的录像"""
        segment_keywords = segment.get('visual_keywords', [])
        segment_text = segment.get('text', '')
        
        # 计算语义相似度
        segment_embedding = self.model.encode([segment_text])
        best_score = 0.0
        best_recording = None
        
        for recording in recordings:
            # 获取录像的转录文本和已有分析数据
            recording_text = await self._get_recording_transcript(recording['id'])
            if not recording_text:
                continue
                
            recording_embedding = self.model.encode([recording_text])
            similarity = np.dot(segment_embedding, recording_embedding.T)[0][0]
            
            # 结合关键词匹配提升权重
            keyword_bonus = self._calculate_keyword_match(segment_keywords, recording_text)
            final_score = similarity * 0.7 + keyword_bonus * 0.3
            
            if final_score > best_score:
                best_score = final_score
                best_recording = recording.copy()
                best_recording['score'] = final_score
        
        return best_recording or recordings[0]  # 兜底返回第一个录像
```

### 3. TTS配音模块 (director_tts.py)

```python
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
import subprocess
import tempfile
from typing import Optional

class DirectorTTS:
    def __init__(self, gpu_server_url: str = "http://10.190.0.203:8877"):
        self.gpu_server = gpu_server_url
    
    async def generate_voiceover(self, script_text: str, 
                               output_path: str,
                               voice_style: str = "professional") -> bool:
        """生成TTS配音文件"""
        try:
            # 首先尝试GPU服务器的TTS
            success = await self._generate_tts_gpu(script_text, output_path, voice_style)
            if success:
                return True
            
            # 回退到本地TTS
            return await self._generate_tts_local(script_text, output_path)
        
        except Exception as e:
            print(f"TTS generation failed: {e}")
            return False
    
    async def _generate_tts_gpu(self, text: str, output_path: str, 
                              voice_style: str) -> bool:
        """使用GPU服务器生成TTS"""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    'text': text,
                    'voice_style': voice_style,
                    'format': 'wav',
                    'sample_rate': 44100
                }
                
                async with session.post(f"{self.gpu_server}/tts", 
                                      json=payload, timeout=120) as resp:
                    if resp.status == 200:
                        audio_data = await resp.read()
                        async with aiofiles.open(output_path, 'wb') as f:
                            await f.write(audio_data)
                        return True
                    return False
        except Exception as e:
            print(f"GPU TTS failed: {e}")
            return False
    
    async def _generate_tts_local(self, text: str, output_path: str) -> bool:
        """本地TTS回退方案（macOS say命令）"""
        try:
            with tempfile.NamedTemporaryFile(suffix='.aiff') as temp_file:
                # 使用macOS的say命令生成语音
                process = await asyncio.create_subprocess_exec(
                    'say', '-v', 'Ting-Ting', '-o', temp_file.name, text,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                
                if process.returncode == 0:
                    # 转换为WAV格式
                    convert_process = await asyncio.create_subprocess_exec(
                        'ffmpeg', '-i', temp_file.name, '-y', output_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await convert_process.communicate()
                    return convert_process.returncode == 0
                
            return False
        except Exception as e:
            print(f"Local TTS failed: {e}")
            return False
```

### 4. 导演模式主引擎 (director_engine.py)

```python
import asyncio
import json
from pathlib import Path
from typing import Dict, List, Optional
import aiosqlite
from datetime import datetime

from .director_script import DirectorScriptGenerator
from .director_matcher import SemanticMatcher
from .director_tts import DirectorTTS
from .director_video import DirectorVideoComposer

class DirectorEngine:
    def __init__(self, db_path: str, recordings_dir: str):
        self.db_path = db_path
        self.recordings_dir = Path(recordings_dir)
        
        # 核心组件
        self.script_generator = DirectorScriptGenerator()
        self.semantic_matcher = SemanticMatcher()
        self.tts_generator = DirectorTTS()
        self.video_composer = DirectorVideoComposer()
        
        # 状态跟踪
        self._processing_groups = set()
    
    async def process_group(self, group_id: int, 
                          config: Optional[Dict] = None) -> Dict:
        """处理一个分组的导演模式流程"""
        if group_id in self._processing_groups:
            return {'error': 'Group is already being processed'}
        
        self._processing_groups.add(group_id)
        
        try:
            # 更新状态为处理中
            await self._update_group_status(group_id, 1)  # processing
            
            # 1. 获取分组数据
            group_data = await self._get_group_data(group_id)
            if not group_data:
                raise Exception(f"Group {group_id} not found")
            
            # 2. 生成AI脚本
            await self._broadcast_progress(group_id, "生成AI脚本中...")
            script = await self.script_generator.generate_script(group_data)
            await self._save_script(group_id, script)
            
            # 3. 语义匹配
            await self._broadcast_progress(group_id, "进行语义匹配...")
            matched_segments = await self.semantic_matcher.match_segments_to_recordings(
                script['segments'], group_data['recordings']
            )
            await self._save_segments(group_id, matched_segments)
            
            # 4. 生成TTS配音
            await self._broadcast_progress(group_id, "生成AI配音...")
            audio_path = await self._generate_group_audio(group_id, script['script_text'])
            if not audio_path:
                raise Exception("TTS generation failed")
            
            # 5. 视频合成
            await self._broadcast_progress(group_id, "合成最终视频...")
            final_video = await self.video_composer.compose_final_video(
                matched_segments, audio_path, config or {}
            )
            
            if not final_video:
                raise Exception("Video composition failed")
            
            # 6. 保存最终结果
            await self._save_final_result(group_id, final_video)
            await self._update_group_status(group_id, 2)  # completed
            
            return {
                'success': True,
                'final_video': final_video,
                'script': script,
                'segments': matched_segments
            }
            
        except Exception as e:
            await self._update_group_status(group_id, -1)  # failed
            await self._save_error(group_id, str(e))
            return {'error': str(e)}
        
        finally:
            self._processing_groups.discard(group_id)
    
    async def _get_group_data(self, group_id: int) -> Optional[Dict]:
        """获取分组的完整数据"""
        async with aiosqlite.connect(self.db_path) as db:
            # 获取分组基本信息
            cursor = await db.execute("""
                SELECT g.*, r.name as room_name 
                FROM clip_groups g 
                LEFT JOIN rooms r ON g.room_id = r.id 
                WHERE g.id = ?
            """, (group_id,))
            group = await cursor.fetchone()
            
            if not group:
                return None
            
            # 获取关联的录像
            cursor = await db.execute("""
                SELECT * FROM recordings 
                WHERE group_id = ? AND clipped = 2
                ORDER BY start_time
            """, (group_id,))
            recordings = await cursor.fetchall()
            
            return {
                'id': group['id'],
                'label': group['label'],
                'wig_model': group['wig_model'],
                'wig_color': group['wig_color'],
                'room_name': group['room_name'],
                'recordings': [dict(r) for r in recordings]
            }
    
    async def _update_group_status(self, group_id: int, status: int):
        """更新分组的导演模式状态"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE clip_groups 
                SET director_status = ?, 
                    updated_at = datetime('now')
                WHERE id = ?
            """, (status, group_id))
            await db.commit()
    
    async def _broadcast_progress(self, group_id: int, message: str):
        """广播处理进度（通过WebSocket）"""
        # 这里需要集成现有的WebSocket广播系统
        progress_data = {
            'type': 'director_progress',
            'group_id': group_id,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        # await broadcast(progress_data)  # 使用现有的broadcast函数
        print(f"[Director Mode] Group {group_id}: {message}")
```

## 部署计划

### 阶段1：基础架构搭建
1. 数据库迁移脚本
2. V2 API路由框架
3. 前端模式选择器组件

### 阶段2：导演模式核心功能
1. AI脚本生成模块
2. 语义匹配引擎
3. TTS配音系统

### 阶段3：视频合成和完善
1. 导演模式视频合成器
2. 质量对比工具
3. 成本监控系统

### 阶段4：用户体验优化
1. 模式切换流畅性
2. 错误处理和回退机制
3. 性能监控和优化

## 风险控制

1. **兼容性保证**：所有新功能通过feature flag控制
2. **回退机制**：导演模式可随时切换回经典模式
3. **资源隔离**：导演模式使用独立的处理队列
4. **监控告警**：实时监控两种模式的处理效果差异

这个设计确保了经典模式完全不受影响，同时为导演模式提供了完整的AI增强功能。