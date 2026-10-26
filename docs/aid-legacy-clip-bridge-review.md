# Failed-clip retry bridge — prepared changes and deployment boundary

## 203 source repair

`clip_retry_sources.py` uses the authoritative recording resolver and then resolves the subtitle independently. It supports a room-subfolder MP4 with a root-folder SRT, and does not treat empty subtitles as usable. Three retry handlers now perform network-file checks off the API loop. Individual/bulk failed-task claims use a conditional UPDATE, so concurrent requests cannot claim the same failed row twice. Original execution functions were not replaced or invoked.

Production source backup: `C:\Users\neo\douyin_backend\codex_rollbacks\retry-paths-20261026-110145`. This is staged, not yet active in the existing backend process. Five local clips and one group pipeline were active at the last check, so the backend was not forcibly restarted. Earlier fixes remain staged alongside it.

## Confirmed AID capability gap

The available AID repository is `/Users/work/1-codex/aid-studio`. Its fixed `gpu_qianchuan_render_worker.py` explicitly accepts only base clip start/duration, aspect, audio preservation, output name and compose/compliant-2K modes. Extra fields are rejected. The old application clip request contains ASS subtitles, per-cut transitions and mute/beep spans. Passing the old payload unchanged is invalid; dropping these fields would change the requested output. `douyin-gpu-processing` likewise only supports transcribe/final-postprocess, not legacy clipping.

## Reviewable proposed extension (not deployed to AID)

`integrations/aid/legacy_clip_worker.py` adds fixed `legacy_clip_v1` data handling: owned artifact IDs, bounded numeric cuts, allow-listed transitions, relative beep windows, ASS captions, 1440x2560/2560x1440 NVENC output, and final duration/track validation. No arbitrary client command/filter/device/path fields are accepted. Existing modes delegate unchanged through `patch_worker.py`. The application client still needs its scheduler upload/job/download bridge before any retry rollout.

`build_bundle.py` prepares the original worker, patched worker, extension, SHA manifest, read-only inspection and explicit activation/rollback helper. Review bundle: `output/aid-legacy-clip-review-v1` (local QA artifact, not committed). Activation requires matching source hashes, FFmpeg subtitles/libass, h264_nvenc and Chinese fonts; dependency failures stop deployment. The patch does not start models, restart GPU services, alter scheduler priorities, or submit workloads. Rollback restores the original worker and removes only the matching new extension.

## Validation and limits

Ten focused tests passed (path resolution, atomic retry claim, schema bounds, unsafe fields, command generation and timeline offsets). The local full CPU smoke test is skipped because the installed FFmpeg lacks the subtitles filter. An isolated CPU-only test on 203 confirmed the same missing filter after normalization/transitions/beep stages had run, so it also did not pass full caption validation. No dependencies were reinstalled. This does not establish whether 222's FFmpeg has libass; activation explicitly checks that. No GPU validation, AID deployment, backend activation or bulk failed-clip submission has occurred.

The AID scheduler skill requires explicit administration authorization identifying the target before managing its deployment. The next requested authorization is narrowly scoped to upgrading the existing qianchuan-render executor on 10.190.0.222 and one scheduled test; bulk retries follow only after a successful representative result. Production files, original failure evidence and existing models remain intact.
