$ErrorActionPreference = "Stop"
$root = "C:\douyin_login\qwen_vl_wig"
$venv = "$root\venv311"
if (-not (Test-Path "$venv\Scripts\python.exe")) {
    & "C:\Python311\python.exe" -m venv $venv
}
$python = "$venv\Scripts\python.exe"
& $python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $python -m pip install transformers==5.3.0 accelerate fastapi uvicorn opencv-python-headless pillow triton-windows
exit $LASTEXITCODE
