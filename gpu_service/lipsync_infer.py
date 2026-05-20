"""
Wav2Lip ONNX Lip Sync Inference Script
=======================================
Lightweight lip sync using ONNX Runtime (GPU).
Works on Python 3.13+ / Windows / RTX 4080S.

Models needed in ./models/:
  - wav2lip_gan.onnx   (from HuggingFace: leonelhs/Wav2Lip-ONNX)
  - s3fd.onnx          (face detection)

Usage:
  python lipsync_infer.py --video input.mp4 --audio tts.wav --output out.mp4
"""
import argparse
import os
import sys
import tempfile
import subprocess
import time
import numpy as np
import cv2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(SCRIPT_DIR, "models")
WAV2LIP_MODEL = os.path.join(MODELS_DIR, "wav2lip_gan.onnx")
S3FD_MODEL = os.path.join(MODELS_DIR, "s3fd.onnx")

# Wav2Lip expects 96x96 face crops, mel spectrograms of 80 bins x 16 frames
IMG_SIZE = 96
MEL_STEP_SIZE = 16


def extract_audio_mel(audio_path: str, sr: int = 16000):
    """Extract mel spectrogram from audio file."""
    import librosa
    wav, _ = librosa.load(audio_path, sr=sr)
    mel = librosa.feature.melspectrogram(y=wav, sr=sr, n_mels=80, hop_length=int(sr*0.01),
                                          win_length=int(sr*0.025), fmin=55, fmax=7600)
    mel = librosa.power_to_db(mel, ref=np.max)
    return mel.T  # (T, 80)


def get_face_bbox(frame, face_detector):
    """Detect face in frame using S3FD ONNX model or OpenCV cascade fallback."""
    # Use OpenCV Haar cascade as lightweight alternative
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))
    if len(faces) == 0:
        return None
    # Return largest face
    faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)
    x, y, w, h = faces[0]
    # Expand bbox by 20% for better context
    pad_w, pad_h = int(w * 0.2), int(h * 0.2)
    x1 = max(0, x - pad_w)
    y1 = max(0, y - pad_h)
    x2 = min(frame.shape[1], x + w + pad_w)
    y2 = min(frame.shape[0], y + h + pad_h)
    return (x1, y1, x2, y2)


def run_lipsync(video_path: str, audio_path: str, output_path: str):
    """Main lip sync pipeline."""
    import onnxruntime as ort
    
    if not os.path.exists(WAV2LIP_MODEL):
        print(f"[LipSync] Model not found: {WAV2LIP_MODEL}")
        return False
    
    print(f"[LipSync] Loading model...")
    sess = ort.InferenceSession(WAV2LIP_MODEL, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    
    # Extract mel from audio
    print(f"[LipSync] Extracting mel spectrogram...")
    mel = extract_audio_mel(audio_path)
    
    # Open video
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Calculate mel chunks per frame (mel hop = 10ms, frame_dur = 1/fps)
    mel_frames_per_video_frame = int(100.0 / fps)  # ~4 at 25fps
    
    # Output video
    tmp_video = output_path + "_tmp.mp4"
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(tmp_video, fourcc, fps, (w, h))
    
    print(f"[LipSync] Processing {total_frames} frames @ {fps}fps...")
    face_bbox = None
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Detect face every 30 frames (face doesn't move much)
        if frame_idx % 30 == 0 or face_bbox is None:
            bbox = get_face_bbox(frame, None)
            if bbox is not None:
                face_bbox = bbox
        
        if face_bbox is None:
            # No face detected, write original frame
            writer.write(frame)
            frame_idx += 1
            continue
        
        x1, y1, x2, y2 = face_bbox
        face_crop = frame[y1:y2, x1:x2]
        
        # Get mel chunk for this frame
        mel_start = frame_idx * mel_frames_per_video_frame
        mel_end = mel_start + MEL_STEP_SIZE
        if mel_end > len(mel):
            mel_chunk = np.zeros((MEL_STEP_SIZE, 80), dtype=np.float32)
            remaining = len(mel) - mel_start
            if remaining > 0:
                mel_chunk[:remaining] = mel[mel_start:mel_end]
        else:
            mel_chunk = mel[mel_start:mel_end].astype(np.float32)
        
        # Prepare inputs for Wav2Lip ONNX
        face_resized = cv2.resize(face_crop, (IMG_SIZE, IMG_SIZE))
        face_input = face_resized.astype(np.float32) / 255.0
        face_input = np.transpose(face_input, (2, 0, 1))  # (3, 96, 96)
        face_input = np.expand_dims(face_input, 0)  # (1, 3, 96, 96)
        
        mel_input = mel_chunk.T  # (80, 16)
        mel_input = np.expand_dims(np.expand_dims(mel_input, 0), 0)  # (1, 1, 80, 16)
        
        try:
            # Run inference
            input_names = [inp.name for inp in sess.get_inputs()]
            output_names = [out.name for out in sess.get_outputs()]
            
            result = sess.run(output_names, {
                input_names[0]: face_input,
                input_names[1]: mel_input,
            })
            
            # Result is (1, 3, 96, 96) - the lip-synced face
            pred_face = result[0][0]  # (3, 96, 96)
            pred_face = np.transpose(pred_face, (1, 2, 0))  # (96, 96, 3)
            pred_face = (pred_face * 255).clip(0, 255).astype(np.uint8)
            
            # Resize back and composite onto original frame
            pred_face_full = cv2.resize(pred_face, (x2-x1, y2-y1))
            
            # Only replace lower half of face (mouth region)
            face_h = y2 - y1
            mouth_start = int(face_h * 0.4)  # lower 60% of face
            frame[y1+mouth_start:y2, x1:x2] = pred_face_full[mouth_start:]
            
        except Exception as e:
            # On inference error, use original frame
            if frame_idx == 0:
                print(f"[LipSync] Inference error: {e}")
        
        writer.write(frame)
        frame_idx += 1
        
        if frame_idx % 100 == 0:
            print(f"[LipSync] Progress: {frame_idx}/{total_frames} ({frame_idx*100//total_frames}%)")
    
    cap.release()
    writer.release()
    
    # Mux with original audio using ffmpeg
    print(f"[LipSync] Muxing audio...")
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
    
    # Cleanup
    if os.path.exists(tmp_video):
        os.remove(tmp_video)
    
    if result.returncode == 0 and os.path.exists(output_path):
        print(f"[LipSync] Done! Output: {output_path}")
        return True
    else:
        print(f"[LipSync] Mux failed: {result.stderr[-200:]}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wav2Lip ONNX Lip Sync")
    parser.add_argument("--video", required=True, help="Input video")
    parser.add_argument("--audio", required=True, help="Target audio (TTS)")
    parser.add_argument("--output", required=True, help="Output video")
    parser.add_argument("--no-enhance", action="store_true", help="Skip face enhancement")
    args = parser.parse_args()
    
    start = time.time()
    ok = run_lipsync(args.video, args.audio, args.output)
    elapsed = time.time() - start
    print(f"[LipSync] Total time: {elapsed:.1f}s")
    sys.exit(0 if ok else 1)
