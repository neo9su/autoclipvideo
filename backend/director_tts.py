"""
导演模式TTS配音模块

支持GPU服务器TTS和本地macOS TTS回退
"""

import asyncio
import aiohttp
import aiofiles
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, Dict, List
import json
import re

logger = logging.getLogger(__name__)

class DirectorTTS:
    def __init__(self, gpu_server_url: str = "http://10.190.0.203:8877"):
        self.gpu_server = gpu_server_url
        self.timeout = 120  # 2分钟超时
        
        # TTS配置
        self.voice_configs = {
            'female_young': {
                'gpu_voice': 'zh-CN-XiaoxiaoNeural',
                'macos_voice': 'Ting-Ting',
                'description': '年轻女声'
            },
            'female_mature': {
                'gpu_voice': 'zh-CN-XiaoyiNeural', 
                'macos_voice': 'Mei-Jia',
                'description': '成熟女声'
            },
            'female_sweet': {
                'gpu_voice': 'zh-CN-XiaohanNeural',
                'macos_voice': 'Sin-ji',
                'description': '甜美女声'
            }
        }
    
    async def generate_voiceover(self, script_text: str, 
                               output_path: str,
                               voice_style: str = "female_young") -> bool:
        """
        生成TTS配音文件
        
        Args:
            script_text: 脚本文本
            output_path: 输出文件路径
            voice_style: 配音风格
        
        Returns:
            bool: 成功返回True
        """
        if not script_text.strip():
            logger.error("Empty script text provided")
            return False
        
        # 确保输出目录存在
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # 首先尝试GPU服务器TTS
            logger.info(f"Attempting GPU TTS for {len(script_text)} characters")
            if await self._generate_tts_gpu(script_text, output_path, voice_style):
                logger.info(f"GPU TTS successful: {output_path}")
                return True
            
            logger.warning("GPU TTS failed, falling back to local TTS")
            
            # 回退到本地TTS
            if await self._generate_tts_local(script_text, output_path, voice_style):
                logger.info(f"Local TTS successful: {output_path}")
                return True
            
            logger.error("All TTS methods failed")
            return False
            
        except Exception as e:
            logger.error(f"TTS generation failed: {e}")
            return False
    
    async def _generate_tts_gpu(self, text: str, output_path: str, 
                              voice_style: str) -> bool:
        """使用GPU服务器生成TTS"""
        try:
            voice_config = self.voice_configs.get(voice_style, self.voice_configs['female_young'])
            
            payload = {
                'text': text,
                'voice': voice_config['gpu_voice'],
                'format': 'wav',
                'sample_rate': 48000,    # 提高到48kHz
                'speed': 1.1,            # 语速稍快，更流畅自然
                'pitch': -2,             # 略微降低音调，避免尖锐
                'volume': 0.75           # 降低音量防止削顶
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.gpu_server}/tts", 
                    json=payload, 
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status == 200:
                        audio_data = await resp.read()
                        if len(audio_data) > 0:
                            async with aiofiles.open(output_path, 'wb') as f:
                                await f.write(audio_data)
                            return True
                    else:
                        logger.warning(f"GPU TTS returned status {resp.status}")
                        
        except asyncio.TimeoutError:
            logger.warning("GPU TTS request timed out")
        except aiohttp.ClientError as e:
            logger.warning(f"GPU TTS client error: {e}")
        except Exception as e:
            logger.warning(f"GPU TTS unexpected error: {e}")
        
        return False
    
    async def _generate_tts_local(self, text: str, output_path: str, 
                                voice_style: str) -> bool:
        """本地TTS回退方案（macOS say命令）"""
        try:
            voice_config = self.voice_configs.get(voice_style, self.voice_configs['female_young'])
            macos_voice = voice_config['macos_voice']
            
            # 分段处理长文本，避免say命令限制
            segments = self._split_text_for_tts(text)
            temp_files = []
            
            try:
                # 为每个段落生成音频
                for i, segment in enumerate(segments):
                    temp_file = f"{output_path}.temp_{i}.aiff"
                    temp_files.append(temp_file)
                    
                    process = await asyncio.create_subprocess_exec(
                        'say', '-v', macos_voice, 
                        '-r', '180',  # 降低语速到180词/分钟
                        '--quality=127',  # 最高质量
                        '-o', temp_file, segment,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await process.communicate()
                    
                    if process.returncode != 0:
                        logger.error(f"Say command failed for segment {i}: {stderr.decode()}")
                        return False
                
                # 合并音频文件
                if len(temp_files) == 1:
                    # 单个文件，直接转换
                    success = await self._convert_audio_to_wav(temp_files[0], output_path)
                else:
                    # 多个文件，先合并再转换
                    merged_file = f"{output_path}.merged.aiff"
                    success = await self._merge_audio_files(temp_files, merged_file)
                    if success:
                        success = await self._convert_audio_to_wav(merged_file, output_path)
                        # 清理合并文件
                        Path(merged_file).unlink(missing_ok=True)
                
                return success
                
            finally:
                # 清理临时文件
                for temp_file in temp_files:
                    Path(temp_file).unlink(missing_ok=True)
                
        except Exception as e:
            logger.error(f"Local TTS failed: {e}")
            return False
    
    def _split_text_for_tts(self, text: str, max_length: int = 200) -> List[str]:
        """将长文本分割为适合TTS的段落"""
        if len(text) <= max_length:
            return [text]
        
        # 按句号分割
        sentences = re.split(r'[。！？]', text)
        segments = []
        current_segment = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # 如果当前段落加上新句子不超过限制，就添加
            if len(current_segment + sentence) <= max_length:
                current_segment += sentence + "。"
            else:
                # 保存当前段落，开始新段落
                if current_segment:
                    segments.append(current_segment.strip())
                current_segment = sentence + "。"
        
        # 添加最后一个段落
        if current_segment:
            segments.append(current_segment.strip())
        
        return segments if segments else [text]
    
    async def _merge_audio_files(self, input_files: List[str], output_file: str) -> bool:
        """合并多个音频文件"""
        try:
            # 构建ffmpeg命令
            cmd = ['ffmpeg', '-y']
            for file in input_files:
                cmd.extend(['-i', file])
            
            # 创建filter_complex参数来连接音频
            filter_complex = ''.join([f"[{i}:0]" for i in range(len(input_files))])
            filter_complex += f"concat=n={len(input_files)}:v=0:a=1[out]"
            
            cmd.extend(['-filter_complex', filter_complex, '-map', '[out]', output_file])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return True
            else:
                logger.error(f"Audio merge failed: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Audio merge error: {e}")
            return False
    
    async def _convert_audio_to_wav(self, input_file: str, output_file: str) -> bool:
        """转换音频格式为WAV，优化音质防止破音"""
        try:
            # 使用ffmpeg优化参数防止破音：
            # -ar 48000: 提高采样率到48kHz
            # -af "volume=0.8": 降低音量到80%防止削顶
            # -af "highpass=f=80": 去除低频杂音
            # -af "compand=attacks=0.1:decays=0.3:points=-90/-90|-35/-35|-25/-25|0/-15": 动态压缩
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', input_file, 
                '-ar', '48000',           # 48kHz采样率
                '-ac', '2',               # 立体声
                '-af', 'volume=0.8,highpass=f=80,compand=attacks=0.1:decays=0.3:points=-90/-90|-35/-35|-25/-25|0/-15',
                '-c:a', 'pcm_s16le',     # 无损PCM编码
                '-y', output_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                return Path(output_file).exists()
            else:
                logger.error(f"Audio conversion failed: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Audio conversion error: {e}")
            return False
    
    async def get_voice_options(self) -> Dict[str, Dict]:
        """获取可用的配音选项"""
        return self.voice_configs
    
    async def test_gpu_connectivity(self) -> bool:
        """测试GPU服务器连接"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.gpu_server}/status",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False