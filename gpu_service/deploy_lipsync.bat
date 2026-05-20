@echo off
chcp 65001 >nul
REM ============================================================
REM  Lip Sync 一键部署 - GPU 服务器 (RTX 4080S / Python 3.13)
REM  
REM  运行方式: 双击此文件 或 在 PowerShell 中执行
REM  预估时间: 3-5 分钟（含模型下载）
REM ============================================================

echo.
echo ========================================
echo   Lip Sync 部署开始
echo ========================================
echo.

REM 创建目录
echo [1/4] 创建目录结构...
mkdir C:\Users\neo\lipsync\models 2>nul

REM 安装依赖
echo [2/4] 安装 Python 依赖...
pip install librosa onnxruntime-gpu --quiet 2>nul
if errorlevel 1 (
    echo   警告: 部分依赖安装可能失败，继续...
)

REM 下载模型
echo [3/4] 下载 Wav2Lip ONNX 模型...
python -c "from huggingface_hub import hf_hub_download; p=hf_hub_download('leonelhs/Wav2Lip-ONNX', 'wav2lip_gan.onnx', local_dir='C:/Users/neo/lipsync/models', local_dir_use_symlinks=False); print(f'  Downloaded: {p}')" 2>nul
if errorlevel 1 (
    echo   错误: 模型下载失败！请检查网络连接
    echo   手动下载: https://huggingface.co/leonelhs/Wav2Lip-ONNX/resolve/main/wav2lip_gan.onnx
    echo   放到: C:\Users\neo\lipsync\models\wav2lip_gan.onnx
)

REM 复制推理脚本
echo [4/4] 部署推理脚本...
REM 请将 lipsync_infer.py 复制到 C:\Users\neo\lipsync\
if exist C:\Users\neo\douyin_processor\lipsync_infer.py (
    copy /Y C:\Users\neo\douyin_processor\lipsync_infer.py C:\Users\neo\lipsync\lipsync_infer.py >nul
    echo   推理脚本已部署
) else (
    echo   注意: 请手动将 lipsync_infer.py 复制到 C:\Users\neo\lipsync\
)

echo.
echo ========================================
echo   验证部署
echo ========================================
echo.

REM 验证
python -c "import onnxruntime; import cv2; import librosa; import numpy; print('  依赖检查: OK')" 2>nul || echo   依赖检查: FAILED
if exist C:\Users\neo\lipsync\models\wav2lip_gan.onnx (
    echo   模型文件: OK
) else (
    echo   模型文件: MISSING
)
if exist C:\Users\neo\lipsync\lipsync_infer.py (
    echo   推理脚本: OK
) else (
    echo   推理脚本: MISSING
)

echo.
echo ========================================
echo   部署完成！
echo   Lip Sync 将在下次导演模式视频合成时自动启用
echo   关闭方式: 删除 C:\Users\neo\lipsync\models\wav2lip_gan.onnx
echo ========================================
echo.
pause
