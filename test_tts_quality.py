#!/usr/bin/env python3
"""
TTS音质测试工具
测试修复后的TTS是否还有破音问题
"""

import asyncio
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from director_tts import DirectorTTS

async def test_tts_quality():
    """测试TTS音质"""
    
    # 测试文案（容易破音的内容）
    test_texts = [
        "你有没有试过，精心打扮了一整套，却因为头发太扁、太少、太没型……出门前信心满满，照镜子时直接崩溃？",
        "戴上的那一秒，我在镜子里愣住了——这还是我吗？棕色的长卷发，每一根都有光泽，蓬蓬的，软软的！",
        "这就是小圆圆不圆家的人生长卷发，棕色仿地针全头套，真的让我重新爱上照镜子！"
    ]
    
    tts = DirectorTTS()
    
    # 测试GPU服务器连接
    gpu_available = await tts.test_gpu_connectivity()
    print(f"GPU服务器可用: {gpu_available}")
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n测试 {i}/3: {text[:20]}...")
        
        output_file = f"test_tts_{i}.wav"
        success = await tts.generate_voiceover(
            script_text=text,
            output_path=output_file,
            voice_style="female_young"
        )
        
        if success:
            print(f"✅ 生成成功: {output_file}")
            
            # 检查音频文件质量
            import subprocess
            try:
                result = subprocess.run([
                    'ffprobe', '-v', 'quiet', '-print_format', 'json',
                    '-show_streams', output_file
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    import json
                    info = json.loads(result.stdout)
                    audio_stream = info['streams'][0]
                    
                    print(f"   采样率: {audio_stream.get('sample_rate')}Hz")
                    print(f"   声道数: {audio_stream.get('channels')}")
                    print(f"   编码: {audio_stream.get('codec_name')}")
                    print(f"   时长: {float(audio_stream.get('duration', 0)):.1f}s")
                    
            except Exception as e:
                print(f"   质量检查失败: {e}")
        else:
            print(f"❌ 生成失败")
    
    print("\n测试完成！请播放生成的test_tts_*.wav文件检查是否还有破音问题。")

if __name__ == "__main__":
    asyncio.run(test_tts_quality())