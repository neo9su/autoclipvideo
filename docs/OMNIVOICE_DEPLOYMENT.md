# OmniVoice TTS Deployment Plan

## Current State
- **GPU TTS Service (8877)**: DOWN - CosyVoice2 service unresponsive
- **Watchdog (8878)**: DOWN - intermittently reachable
- **ComfyUI (8188)**: UP - 14.7 GB VRAM free
- **Backend (8899)**: UP

## Deployment Options

### Option 1: Standalone OmniVoice Service (Recommended)
Deploy a new FastAPI service on port 8879 using OmniVoice model.

**Files created:**
- `gpu_service_src/omnivoice_service.py` - FastAPI service
- `scripts/deploy_omnivoice_service.sh` - Deployment script
- `scripts/deploy_omnivoice.bat` - Windows batch installer

**Steps:**
1. RDP to GPU server (10.190.0.203)
2. Run `install_omnivoice.bat` to install dependencies
3. Run `start_omnivoice.bat` to start the service
4. Update backend config to point to new service

### Option 2: ComfyUI Custom Node
Install OmniVoice as a ComfyUI custom node.

**Files created:**
- `gpu_service/comfyui_omnivoice/install.py` - Installer script

**Steps:**
1. Clone the ComfyUI-OmniVoice-TTS repo:
   ```
   cd C:\ComfyUI\custom_nodes
   git clone https://github.com/Saganaki22/ComfyUI-OmniVoice-TTS.git
   cd ComfyUI-OmniVoice-TTS
   python install.py
   ```
2. Restart ComfyUI
3. Use the OmniVoice nodes in ComfyUI workflows

### Option 3: Fix CosyVoice2 Service
Diagnose and fix the existing CosyVoice2 service.

**Possible issues:**
- Model corruption
- PyTorch/CUDA version mismatch
- Memory issues
- File path problems

**Steps:**
1. Check GPU service logs: `C:\Users\neo\douyin_processor\gpu_service.log`
2. Restart the service via watchdog or manually
3. Verify model files exist

## Backend Integration

To switch the backend to use OmniVoice:

1. Update `GPU_SERVICE_URL` in backend config:
   ```bash
   export GPU_SERVICE_URL=http://10.190.0.203:8879
   ```

2. Or add a new environment variable:
   ```bash
   export OMNIVOICE_URL=http://10.190.0.203:8879
   ```

3. Update `voice_director.py` to use the new service

## Files Created

| File | Purpose |
|------|---------|
| `gpu_service_src/omnivoice_service.py` | OmniVoice FastAPI service |
| `gpu_service/comfyui_omnivoice/install.py` | ComfyUI node installer |
| `scripts/deploy_omnivoice.bat` | Windows deployment script |
| `scripts/deploy_omnivoice_service.sh` | Linux/macOS deployment script |
| `docs/OMNIVOICE_DEPLOYMENT.md` | This file |

## Next Steps

1. **Immediate**: RDP to GPU server and check service status
2. **Short-term**: Deploy OmniVoice as fallback TTS service
3. **Long-term**: Fix CosyVoice2 or replace with OmniVoice permanently
