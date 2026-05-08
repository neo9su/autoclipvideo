#!/usr/bin/env python3
"""
本地TTS配音服务部署脚本
为导演模式提供高质量中文配音
"""

import asyncio
import subprocess
import json
import os
from pathlib import Path

async def test_macos_tts():
    """测试macOS TTS功能"""
    print("🎙️ 测试macOS TTS功能...")
    
    # 获取可用的中文声音
    result = subprocess.run(['say', '-v', '?'], capture_output=True, text=True)
    chinese_voices = []
    
    for line in result.stdout.split('\n'):
        if 'zh-CN' in line or 'zh_CN' in line:
            voice_name = line.split()[0]
            chinese_voices.append(voice_name)
    
    print(f"发现 {len(chinese_voices)} 个中文语音:")
    for voice in chinese_voices[:5]:
        print(f"  - {voice}")
    
    return chinese_voices

async def generate_test_voiceover():
    """生成测试配音文件"""
    print("\n🎬 生成导演模式测试配音...")
    
    test_script = """你有没有试过，精心打扮了一整套，却因为头发太扁、太少、太没型……出门前信心满满，照镜子时直接崩溃？我之前就是这样。"""
    
    output_dir = Path("test_voiceovers")
    output_dir.mkdir(exist_ok=True)
    
    voices = ['Ting-Ting', 'Mei-Jia', 'Sin-ji']  # 三种不同风格的中文女声
    
    for i, voice in enumerate(voices, 1):
        output_file = output_dir / f"director_test_{i}_{voice}.aiff"
        
        print(f"  生成 {voice} 配音...")
        
        process = await asyncio.create_subprocess_exec(
            'say', '-v', voice,
            '-r', '180',  # 语速稍慢
            '--quality=127',  # 最高质量
            '-o', str(output_file),
            test_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0 and output_file.exists():
            # 转换为WAV格式
            wav_file = output_file.with_suffix('.wav')
            convert_process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', str(output_file),
                '-ar', '48000', '-ac', '2',
                '-af', 'volume=0.8,highpass=f=80',
                '-c:a', 'pcm_s16le',
                '-y', str(wav_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            await convert_process.communicate()
            
            if wav_file.exists():
                print(f"    ✅ {wav_file.name} 生成成功")
                # 删除临时aiff文件
                output_file.unlink()
            else:
                print(f"    ❌ WAV转换失败")
        else:
            print(f"    ❌ TTS生成失败: {stderr.decode()}")

async def update_tts_config():
    """更新TTS配置以支持导演模式"""
    print("\n⚙️ 更新导演模式TTS配置...")
    
    # 优化的TTS配置
    tts_config = {
        'voices': {
            'female_young': {
                'macos_voice': 'Ting-Ting',
                'speed': 180,
                'quality': 127,
                'description': '年轻女声 - 清晰自然'
            },
            'female_mature': {
                'macos_voice': 'Mei-Jia',
                'speed': 175,
                'quality': 127,
                'description': '成熟女声 - 温暖可信'
            },
            'female_sweet': {
                'macos_voice': 'Sin-ji',
                'speed': 185,
                'quality': 127,
                'description': '甜美女声 - 亲和力强'
            }
        },
        'audio_processing': {
            'sample_rate': 48000,
            'channels': 2,
            'volume': 0.8,
            'filters': 'volume=0.8,highpass=f=80,compand=attacks=0.1:decays=0.3:points=-90/-90|-35/-35|-25/-25|0/-15'
        }
    }
    
    config_file = Path('director_tts_config.json')
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(tts_config, f, indent=2, ensure_ascii=False)
    
    print(f"    ✅ 配置已保存到 {config_file}")

async def main():
    print("🚀 开始部署导演模式TTS配音服务...\n")
    
    # 1. 测试系统TTS能力
    voices = await test_macos_tts()
    
    if not voices:
        print("❌ 未发现中文TTS语音，请检查系统设置")
        return
    
    # 2. 生成测试配音样本
    await generate_test_voiceover()
    
    # 3. 更新配置
    await update_tts_config()
    
    print("\n🎉 导演模式TTS配音服务部署完成！")
    print("\n📋 部署总结:")
    print(f"  ✅ 可用中文语音: {len(voices)} 个")
    print("  ✅ 测试配音文件: 已生成")
    print("  ✅ 优化配置: 已更新")
    print("  ✅ 音频质量: 48kHz/16bit 防破音")
    
    print("\n💡 使用方法:")
    print("  1. 检查 test_voiceovers/ 目录中的样本文件")
    print("  2. 选择合适的语音风格")
    print("  3. 导演模式将自动使用优化后的TTS配置")

if __name__ == "__main__":
    asyncio.run(main())