"""
GPU服务器TTS服务扩展
添加声音克隆和配音生成功能
"""

# 需要添加到 gpu_service/main.py

from TTS.api import TTS
import torch
import torchaudio
import numpy as np
from pathlib import Path
import tempfile
import asyncio

# 全局TTS模型（启动时加载）
tts_model = None

def init_tts_model():
    """初始化XTTS-v2模型"""
    global tts_model
    try:
        # 支持中文声音克隆的模型
        tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")
        print("✓ XTTS-v2 模型加载成功")
    except Exception as e:
        print(f"✗ TTS模型加载失败: {e}")

@app.post("/tts/clone-voice")
async def clone_voice_synthesis(
    text: str = Form(...),
    reference_audio: UploadFile = File(...),
    emotion: str = Form("neutral"),
    speed: float = Form(1.0)
):
    """声音克隆合成API"""
    
    if not tts_model:
        return {"error": "TTS模型未加载"}
    
    try:
        # 保存上传的参考音频
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_ref:
            content = await reference_audio.read()
            temp_ref.write(content)
            temp_ref_path = temp_ref.name
        
        # 音频预处理（如果需要）
        ref_audio = preprocess_reference_audio(temp_ref_path)
        
        # 声音克隆合成
        import time as _time
        output_path = f"tts_output_{_time.time()}.wav"
        tts_model.tts_to_file(
            text=text,
            speaker_wav=ref_audio,
            language="zh",  # 中文
            file_path=output_path,
            speed=speed
        )
        
        # 音频后处理
        processed_audio = postprocess_audio(output_path, emotion)
        
        return {
            "status": "success",
            "audio_url": f"/tts/download/{processed_audio}",
            "duration": get_audio_duration(processed_audio),
            "sample_rate": 22050
        }
        
    except Exception as e:
        return {"error": f"声音合成失败: {str(e)}"}

def preprocess_reference_audio(audio_path: str) -> str:
    """预处理参考音频"""
    # 加载音频
    waveform, sample_rate = torchaudio.load(audio_path)
    
    # 重采样到22050Hz（XTTS要求）
    if sample_rate != 22050:
        resampler = torchaudio.transforms.Resample(sample_rate, 22050)
        waveform = resampler(waveform)
    
    # 转单声道
    if waveform.shape[0] > 1:
        waveform = torch.mean(waveform, dim=0, keepdim=True)
    
    # 音频增强（降噪、标准化）
    waveform = normalize_audio(waveform)
    
    # 保存处理后的音频
    processed_path = audio_path.replace(".wav", "_processed.wav")
    torchaudio.save(processed_path, waveform, 22050)
    
    return processed_path

def postprocess_audio(audio_path: str, emotion: str = "neutral") -> str:
    """音频后处理"""
    waveform, sr = torchaudio.load(audio_path)
    
    # 根据情感调整音频特征
    if emotion == "excited":
        # 提升能量和音调
        waveform = apply_pitch_shift(waveform, sr, semitones=1)
        waveform = apply_energy_boost(waveform, factor=1.1)
    elif emotion == "confident":
        # 增强低频，稳定音调
        waveform = apply_bass_boost(waveform, sr)
    elif emotion == "urgent":
        # 加快语速，提高紧迫感
        waveform = apply_tempo_change(waveform, factor=1.1)
    
    # 最终标准化
    waveform = normalize_audio(waveform)
    
    # 保存处理后的音频
    output_path = audio_path.replace(".wav", "_final.wav") 
    torchaudio.save(output_path, waveform, sr)
    
    return output_path

# 音频处理工具函数
def normalize_audio(waveform):
    """音频标准化"""
    return waveform / (waveform.abs().max() + 1e-8) * 0.9

def apply_pitch_shift(waveform, sr, semitones):
    """音调调整"""
    # 简单的pitch shifting实现
    return waveform  # 实际需要使用librosa或其他库

def apply_energy_boost(waveform, factor):
    """能量提升"""
    return waveform * factor

def get_audio_duration(audio_path):
    """获取音频时长"""
    waveform, sr = torchaudio.load(audio_path)
    return waveform.shape[1] / sr