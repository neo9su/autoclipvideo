# AID render recovery — 2026-10-25

New render credential is stored outside Git in a restricted key file. Verified access to `qianchuan-render`; existing transcription credential is retained separately. No global production GPU routing was changed.

First isolated preview: recording 45409, 427.37–473.01 seconds (45.64 seconds), brown fringe long straight hair / half-up demonstration. Source hash and timeline are persisted in `codex_operations/production-20261025/render-45409-v1.json` on 203. Product identity remains unconfirmed; do not automatically attach a product from a spoken live cart number.

`aid_render_recording_preview.py` streams the source as a new artifact owned by the render client, preserves a stable idempotency key and job ID, and submits only the documented compliant 2K protocol. Original recordings and business database are untouched. The result remains a preview pending complete playback, audio and output validation. The renderer does not add the preferred animated captions or sound effects.

Rollback: no database/config rollback is needed. Remove the isolated `CodexAIDRender45409` task after it finishes and retain its state/audit files. Do not delete source media or cancel an active render merely to remove the launcher. No bulk production has been enabled by this script.

Verified scheduler outcome: job **460 SUCCEEDED**, 13.672 seconds, 1440×2560 H.264 with audio, duration45.64 seconds, size58,253,926 bytes. Output SHA256 `bccade1d5c3fac34d86b9888c4ad3ffdd681a88accbf1341302187876bc39bfa`. Managed download and full CPU decode validation are pending; no claim of complete playback acceptance or bulk production readiness.

Follow-up verification: the output was downloaded by the 203 susun worker directly to `\\10.190.0.222\disk2\douyin-203-f-media\production-20261025\recording-45409-brown-fringe-preview-v1.mp4`. Download hash and size match scheduler results. Full CPU decoding of video and audio completed with exit0 and no errors. The adjacent preview manifest stores these checks. The runner now resumes cached job460 and skips an already verified download. Explicit UTF-8 state reads preserve Chinese labels on Windows.

Remaining: complete visual/audio playback review, captions/effects, product identification and catalog-safe batch orchestration. Do not mark the source clipped or publish this baseline preview automatically. The local SRT sidecar retains original ASR wording and adjusts timestamps to the chosen source window; it is not yet caption proofreading or burned-in subtitles.
