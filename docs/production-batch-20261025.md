# Production recovery batch — 2026-10-25

User authorized processing previously unclipped recordings, with source preservation and no external publication. Read-only inventory on 203 found 1104 non-deleted recording rows not marked clipped=2, including 969 transcribed clip failures (265 duration accepted, 704 old duration unknown). Inventory is not proof that every file is accessible, >=1080p or a single wig.

Snapshot stored at C:\Users\neo\douyin_backend\codex_operations\production-20261025\inventory.json; SHA-256 7665fde7a854109b5d764c4fe68d3e62cb13053beef89c28babfaab22a30af4d. No business database rows were reset.

AID credential permits douyin-gpu-processing only. Local fixed-worker protocol source at /Users/work/1-codex/aid-studio/deploy/local/gpu_douyin_processing_worker.py declares operations transcribe and final-postprocess, with input video <=1800 seconds. It does not expose arbitrary editing/cutting/window selection. General upload acceptance is not a guarantee that a worker supports a 45-minute input. User was asked for the editing Profile and protocol; no private GPU port or SSH workload fallback used.

First production prerequisite submitted: recording 45409, filename 3_20261024_160207_004.mp4, 1088x1920, duration 1767.122438 seconds, SHA-256 6d93c33d5a38b0161d6fd7cf028054862e87bad7548f669df15802e1e63292c1. Artifact 94135af0ac523b07f6187b8fc83951fe. AID job 459, profile douyin-gpu-processing, operation transcribe, stable key douyin-recording-45409-transcribe-v1. Observed RUNNING after accepted. Initial estimated cold-start seconds 15. Do not describe this as a completed edited video.

Worker task CodexAIDProduction45409 runs as susun, saves job ID/status and eventual transcript to the batch directory, and polls through AID. HTTP auth uses restricted key file and TLS CA. Raw input preserved. Script validates video metadata, streams upload, caches artifact/job IDs and does not mutate business status or launch the legacy GPU service. Result phase TRANSCRIBED_NOT_CLIPPED explicitly distinguishes prerequisites from editing.

Targeted CPU test passed: source resolver returning str is accepted; cached artifact avoids reupload; a rerun submits only once using durable job identity; successful transcript is saved; business database bytes unchanged. Python syntax compiled. No whole-pipeline render/publish validation.

Rollback/control: cancel active job only through AID POST /v1/jobs/459/cancel if requested. Keep batch manifest and source. No media/database rollback is required since they have not been modified. Do not restart/retry with a new idempotency key. Source path can turn into a validated UNC link during migration without changing source bytes.

First prerequisite completed: AID job 459 SUCCEEDED on gpu-222, assigned GPU-f68178f8-25b4-d393-ac2e-62339307190b. Result operation transcribe, segmentCount 1882, elapsedSeconds 318.555. This is transcript production, not an edited MP4.

Located the existing qianchuan-render protocol in the local AID deployment source (gpu_qianchuan_render_worker.py). It accepts qianchuanRenderRequest with 1–30 clips, artifact IDs plus start/duration, 9:16 or 16:9 and bounded output duration. The current client's GET /v1/profiles does not include qianchuan-render, so no render job was submitted or private-port fallback used. Client Profile authorization remains required before clipping can proceed.
