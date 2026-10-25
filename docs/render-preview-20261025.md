# AID render recovery — 2026-10-25

New render credential is stored outside Git in a restricted key file. Verified access to `qianchuan-render`; existing transcription credential is retained separately. No global production GPU routing was changed.

First isolated preview: recording 45409, 427.37–473.01 seconds (45.64 seconds), brown fringe long straight hair / half-up demonstration. Source hash and timeline are persisted in `codex_operations/production-20261025/render-45409-v1.json` on 203. Product identity remains unconfirmed; do not automatically attach a product from a spoken live cart number.

`aid_render_recording_preview.py` streams the source as a new artifact owned by the render client, preserves a stable idempotency key and job ID, and submits only the documented compliant 2K protocol. Original recordings and business database are untouched. The result remains a preview pending complete playback, audio and output validation. The renderer does not add the preferred animated captions or sound effects.

Rollback: no database/config rollback is needed. Remove the isolated `CodexAIDRender45409` task after it finishes and retain its state/audit files. Do not delete source media or cancel an active render merely to remove the launcher. No bulk production has been enabled by this script.
