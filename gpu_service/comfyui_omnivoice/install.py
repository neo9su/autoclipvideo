"""
ComfyUI-OmniVoice-TTS installer.
Run this script after cloning the repo to ComfyUI/custom_nodes/
"""
import subprocess
import sys
import os

def install():
    print("Installing OmniVoice dependencies...")
    
    # Install omnivoice without dependencies (to avoid downgrading torch)
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "omnivoice", "--no-deps", "--quiet"
    ], check=True)
    
    # Install missing dependencies
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "soundfile", "numpy", "transformers", "--quiet"
    ], check=True)
    
    print("Installation complete!")
    print("Restart ComfyUI to load the OmniVoice nodes.")

if __name__ == "__main__":
    install()
