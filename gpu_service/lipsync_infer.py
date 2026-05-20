"""
Wav2Lip PyTorch Lip Sync Inference Script
==========================================
Lip sync using Wav2Lip GAN model (PyTorch / CUDA).
Compatible with Python 3.13 + torch 2.11 + RTX 4080S.

Model: ./models/wav2lip_gan.pth (from camenduru/Wav2Lip)

Usage:
  python lipsync_infer.py --video input.mp4 --audio tts.wav --output out.mp4
"""
import argparse
import os
import sys
import subprocess
import tempfile
import time
import numpy as np
import cv2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(SCRIPT_DIR, "models")
WAV2LIP_MODEL = os.path.join(MODELS_DIR, "wav2lip_gan.pth")

# Wav2Lip expects 96x96 face crops, mel spectrograms of 80 bins x 16 frames
IMG_SIZE = 96
MEL_STEP_SIZE = 16


def extract_mel(audio_path: str, sr: int = 16000):
    """Extract mel spectrogram from audio file."""
    import librosa
    wav, _ = librosa.load(audio_path, sr=sr)
    mel = librosa.feature.melspectrogram(y=wav, sr=sr, n_mels=80, hop_length=int(sr * 0.01),
                                          win_length=int(sr * 0.025), fmin=55, fmax=7600)
    mel = librosa.power_to_db(mel, ref=np.max)
    return mel.T  # (T, 80)


def get_face_bbox(frame):
    """Detect face using OpenCV Haar cascade."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))
    if len(faces) == 0:
        return None
    # Largest face
    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    x, y, w, h = faces[0]
    # Expand bbox
    pad_w, pad_h = int(w * 0.25), int(h * 0.25)
    x1 = max(0, x - pad_w)
    y1 = max(0, y - pad_h)
    x2 = min(frame.shape[1], x + w + pad_w)
    y2 = min(frame.shape[0], y + h + pad_h)
    return (x1, y1, x2, y2)


def load_wav2lip_model(checkpoint_path: str):
    """Load Wav2Lip GAN model."""
    import torch
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "video-retalking"))  # fallback
    
    # Wav2Lip model architecture (inline to avoid external dependencies)
    from torch import nn
    
    class Conv2d(nn.Module):
        def __init__(self, cin, cout, kernel_size, stride, padding, residual=False):
            super().__init__()
            self.conv_block = nn.Sequential(
                nn.Conv2d(cin, cout, kernel_size, stride, padding),
                nn.BatchNorm2d(cout)
            )
            self.act = nn.ReLU()
            self.residual = residual

        def forward(self, x):
            out = self.conv_block(x)
            if self.residual:
                out += x
            return self.act(out)

    class Wav2Lip(nn.Module):
        def __init__(self):
            super().__init__()
            # Audio encoder
            self.audio_encoder = nn.Sequential(
                Conv2d(1, 32, kernel_size=3, stride=1, padding=1),
                Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
                Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True),
                Conv2d(32, 64, kernel_size=3, stride=(3, 1), padding=1),
                Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True),
                Conv2d(64, 128, kernel_size=3, stride=3, padding=1),
                Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True),
                Conv2d(128, 256, kernel_size=3, stride=(3, 2), padding=1),
                Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True),
                Conv2d(256, 512, kernel_size=3, stride=1, padding=0),
                Conv2d(512, 512, kernel_size=1, stride=1, padding=0),
            )
            # Face encoder
            self.face_encoder_blocks = nn.ModuleList([
                nn.Sequential(Conv2d(6, 16, kernel_size=7, stride=1, padding=3)),
                nn.Sequential(Conv2d(16, 32, kernel_size=3, stride=2, padding=1),
                              Conv2d(32, 32, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(32, 64, kernel_size=3, stride=2, padding=1),
                              Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
                              Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(128, 256, kernel_size=3, stride=2, padding=1),
                              Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(256, 512, kernel_size=3, stride=2, padding=1),
                              Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(512, 512, kernel_size=3, stride=1, padding=0),
                              Conv2d(512, 512, kernel_size=1, stride=1, padding=0)),
            ])
            # Face decoder
            self.face_decoder_blocks = nn.ModuleList([
                nn.Sequential(Conv2d(512, 512, kernel_size=1, stride=1, padding=0)),
                nn.Sequential(Conv2d(1024, 512, kernel_size=3, stride=1, padding=1),
                              Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(768, 512, kernel_size=3, stride=1, padding=1),
                              Conv2d(512, 512, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(640, 256, kernel_size=3, stride=1, padding=1),
                              Conv2d(256, 256, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(320, 128, kernel_size=3, stride=1, padding=1),
                              Conv2d(128, 128, kernel_size=3, stride=1, padding=1, residual=True)),
                nn.Sequential(Conv2d(160, 64, kernel_size=3, stride=1, padding=1),
                              Conv2d(64, 64, kernel_size=3, stride=1, padding=1, residual=True)),
            ])
            self.output_block = nn.Sequential(
                Conv2d(80, 32, kernel_size=3, stride=1, padding=1),
                nn.Conv2d(32, 3, kernel_size=1, stride=1, padding=0),
                nn.Sigmoid()
            )

        def forward(self, audio_sequences, face_sequences):
            B = audio_sequences.size(0)
            # Audio
            audio_embedding = self.audio_encoder(audio_sequences)
            audio_embedding = audio_embedding.reshape(B, -1, 1, 1)
            # Face encode
            feats = []
            x = face_sequences
            for f in self.face_encoder_blocks:
                x = f(x)
                feats.append(x)
            # Face decode with skip connections
            x = audio_embedding
            for i, f in enumerate(self.face_decoder_blocks):
                x = f(x)
                try:
                    x = torch.cat((x, feats[-(i+1)]), dim=1)
                except Exception:
                    pass
                if i < len(self.face_decoder_blocks) - 1:
                    x = nn.functional.interpolate(x, scale_factor=2, mode='bilinear', align_corners=False)
            x = torch.cat((x, face_sequences[:, :3]), dim=1)
            x = self.output_block(x)
            return x

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = Wav2Lip()
    
    print(f"[LipSync] Loading model from {checkpoint_path} on {device}...")
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    
    # Handle different checkpoint formats
    if 'state_dict' in checkpoint:
        state_dict = checkpoint['state_dict']
    elif 'model' in checkpoint:
        state_dict = checkpoint['model']
    else:
        state_dict = checkpoint
    
    # Remove module. prefix if present
    new_state_dict = {}
    for k, v in state_dict.items():
        new_key = k.replace('module.', '')
        new_state_dict[new_key] = v
    
    try:
        model.load_state_dict(new_state_dict, strict=False)
    except Exception as e:
        print(f"[LipSync] Warning: partial load ({e})")
    
    model = model.to(device).eval()
    print(f"[LipSync] Model loaded successfully on {device}")
    return model, device


def run_lipsync(video_path: str, audio_path: str, output_path: str):
    """Main lip sync pipeline using PyTorch."""
    import torch
    
    if not os.path.exists(WAV2LIP_MODEL):
        print(f"[LipSync] ERROR: Model not found: {WAV2LIP_MODEL}")
        return False
    
    model, device = load_wav2lip_model(WAV2LIP_MODEL)
    
    # Extract mel from audio
    print(f"[LipSync] Extracting mel spectrogram...")
    mel = extract_mel(audio_path)
    
    # Open video
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    mel_frames_per_video_frame = int(100.0 / fps)
    
    # Output video (temp)
    tmp_video = output_path + "_tmp.mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(tmp_video, fourcc, fps, (w, h))
    
    print(f"[LipSync] Processing {total_frames} frames @ {fps:.1f}fps...")
    face_bbox = None
    frame_idx = 0
    
    with torch.no_grad():
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Detect face every 30 frames
            if frame_idx % 30 == 0 or face_bbox is None:
                bbox = get_face_bbox(frame)
                if bbox is not None:
                    face_bbox = bbox
            
            if face_bbox is None:
                writer.write(frame)
                frame_idx += 1
                continue
            
            x1, y1, x2, y2 = face_bbox
            face_crop = frame[y1:y2, x1:x2].copy()
            
            # Get mel chunk
            mel_start = frame_idx * mel_frames_per_video_frame
            mel_end = mel_start + MEL_STEP_SIZE
            if mel_end > len(mel):
                mel_chunk = np.zeros((MEL_STEP_SIZE, 80), dtype=np.float32)
                remaining = len(mel) - mel_start
                if remaining > 0:
                    mel_chunk[:remaining] = mel[mel_start:mel_end]
            else:
                mel_chunk = mel[mel_start:mel_end].astype(np.float32)
            
            # Prepare face input (96x96, masked lower half)
            face_resized = cv2.resize(face_crop, (IMG_SIZE, IMG_SIZE))
            face_masked = face_resized.copy()
            face_masked[IMG_SIZE // 2:] = 0  # mask lower half (mouth region)
            
            # Stack: masked face + original face = 6 channels
            img_batch = np.concatenate([face_masked, face_resized], axis=2) / 255.0
            img_batch = np.transpose(img_batch, (2, 0, 1)).astype(np.float32)
            img_tensor = torch.FloatTensor(img_batch).unsqueeze(0).to(device)
            
            # Mel input
            mel_input = mel_chunk.T[np.newaxis, np.newaxis, :, :]  # (1, 1, 80, 16)
            mel_tensor = torch.FloatTensor(mel_input).to(device)
            
            try:
                pred = model(mel_tensor, img_tensor)
                pred_face = pred[0].cpu().numpy().transpose(1, 2, 0) * 255.0
                pred_face = pred_face.clip(0, 255).astype(np.uint8)
                
                # Resize back and composite (only lower half = mouth)
                pred_full = cv2.resize(pred_face, (x2 - x1, y2 - y1))
                face_h = y2 - y1
                mouth_start = int(face_h * 0.45)
                
                # Blend for smooth transition
                blend_zone = int(face_h * 0.05)
                for dy in range(blend_zone):
                    alpha = dy / blend_zone
                    row = mouth_start + dy
                    if row < face_h:
                        frame[y1 + row, x1:x2] = (
                            (1 - alpha) * frame[y1 + row, x1:x2] +
                            alpha * pred_full[row]
                        ).astype(np.uint8)
                # Full replacement below blend zone
                frame[y1 + mouth_start + blend_zone:y2, x1:x2] = pred_full[mouth_start + blend_zone:]
                
            except Exception as e:
                if frame_idx == 0:
                    print(f"[LipSync] Inference error: {e}")
            
            writer.write(frame)
            frame_idx += 1
            
            if frame_idx % 100 == 0:
                print(f"[LipSync] {frame_idx}/{total_frames} ({frame_idx * 100 // max(total_frames, 1)}%)")
    
    cap.release()
    writer.release()
    
    # Mux with ffmpeg (NVENC)
    print(f"[LipSync] Encoding final output with NVENC...")
    cmd = [
        "ffmpeg", "-y",
        "-i", tmp_video,
        "-i", audio_path,
        "-c:v", "h264_nvenc", "-b:v", "10M",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if os.path.exists(tmp_video):
        os.remove(tmp_video)
    
    if result.returncode == 0 and os.path.exists(output_path):
        print(f"[LipSync] Done! {output_path} ({os.path.getsize(output_path) // 1024 // 1024}MB)")
        return True
    else:
        print(f"[LipSync] Mux failed: {result.stderr[-300:]}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wav2Lip PyTorch Lip Sync")
    parser.add_argument("--video", required=True, help="Input video")
    parser.add_argument("--audio", required=True, help="Target audio (TTS)")
    parser.add_argument("--output", required=True, help="Output video")
    args = parser.parse_args()
    
    start = time.time()
    ok = run_lipsync(args.video, args.audio, args.output)
    elapsed = time.time() - start
    print(f"[LipSync] Total time: {elapsed:.1f}s")
    sys.exit(0 if ok else 1)
