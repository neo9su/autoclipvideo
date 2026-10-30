# MuseTalk 1.5 on 203: isolated comparison pilot

User requested MuseTalk test on 203 after rejecting the LatentSync 1.5 preview for mouth blur. This adapter does not change production rendering or publishing.

- Upstream code commit: `TMElyralab/MuseTalk@0a89dec45a0192b824e3cf4daf96c239440c5ed8`.
- Independent environment: `F:\aid-models\musetalk-1.5` (Python 3.11, Torch 2.0.1 cu118, MMCV 2.0.1 Windows wheel).
- Fixed profile: `musetalk-15-203`, exclusive AID lease, source/audio artifact IDs only, bounded 5–15 second clip. No arbitrary commands or input paths.
- Compare recording 45409 at 427.37 seconds using the exact paced audio from successful LatentSync job 944. Preserve source dimensions; 25 fps; float16, batch size 2; no face restoration or beautification.
- Weights are verified against upstream Hugging Face LFS SHA-256. A reachable mirror may provide identical bytes; hashes are required before use.
- Inference-only dependency set omits training TensorFlow/TensorBoard and Gradio UI.
- Node and manager installers create backups before additive configuration changes. Restart the AID agent only while idle. Existing production profiles are preserved.
- Output is a preview requiring full playback quality review. No claim of improved visual quality until the user can compare mouth/teeth/detail and temporal stability.

Job 946 SUCCEEDED on gpu-203 in 139.7 seconds. Output H.264 1088x1920, 9.96-second video with 9.97-second AAC audio; full decode and download SHA-256 checks passed. Three sampled frames inspected; temporal mouth quality remains subject to playback acceptance. Output SHA-256: `72d2e4591eaeedd3efc6e37588dafdf203052ff073ec9870e3380f9e4a5cccfd`.

Deployment backups: `F:\aid-models\musetalk-1.5\backups\20261031-051237` and manager `/home/neo/.local/state/aid-gpu-scheduler/backups/musetalk-20261030-211245`. Job 946 submitted through AID. Dependency check and CPU imports passed; three invalid-input cases rejected. Five setup-only scheduled tasks removed.

## Localized fusion pilot

Optional `lipSyncRequest.qualityMode=localized` uses a separate inference module; omitted mode retains the original baseline. Bounds the centered three-frame crop correction to 1% of box size and bypasses smoothing during fast motion. Uses the union of original and generated lip/mouth segmentation, with limited dilation and feathering. Only mask edges are temporally smoothed; generated mouth pixels are never temporally averaged. Rejects missing or excessively broad mouth masks. Original pixels outside the mask remain unchanged before video encoding.

CPU checks passed for box smoothing limits, fast motion, outer-pixel preservation, opaque current mouth pixels, and missing-mask rejection. Backup: `F:\aid-models\musetalk-1.5\backups\localized-20261031-052129`. Original upstream inference and global blending remain unchanged. Job 949 uses the exact source/audio artifacts of job 946; job 949 SUCCEEDED in 117.7 seconds; H.264 1088x1920, video 9.96s/audio 9.97s. Decode and SHA-256 passed (`4bbe837f78826889097d99ee068816a2f687a716ef8810d24973d80c77204393`). Matched-frame inspection still shows soft lip/teeth detail; this change reduces fusion scope, not model resolution. Playback acceptance remains pending.
