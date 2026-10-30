# Independent 203 Qianchuan Profile

Implemented under explicit user authorization to copy the existing Qianchuan Profile to 203 and expose it to the douyin-recorder terminal (`douyin`). No 222 renderer upgrade was performed.

## Deployed configuration

- Profile: **qianchuan-render-203**.
- Node restriction: `allowedNodeIds=["gpu-203"]`, `gpuIndices=[0]` (203's RTX 4080 SUPER).
- Priority, exclusivity, non-preemptibility, timing limits and fixed render modes copied from the actual enabled `qianchuan-render` Profile. Source renderer SHA-256: `e136bd7435ae627069fdd0dfdb61fb64a36a2445d0118e95d6da2b12bded277f`, matching both the AID repository and deployed 222 worker.
- Existing `qianchuan-render` remains restricted to gpu-222; its live configuration was compared before/after manager reload and remained identical.
- Added the new Profile to both active client credentials belonging to `source=douyin`, IDs 29 and 30. All prior profile grants remain. No keys were created, rotated, printed or committed.
- Added a separate configured service-catalog entry for the 203 fixed renderer.

Windows worker path: `C:\ProgramData\AIDGpuScheduler\adapters\qianchuan-render-203\gpu_qianchuan_render_worker.py`.
Worker SHA-256: `e7436773ffa9bbae32f6d3079c31a91a03ce70e243c70799e0940d08d161ef1f`.
Windows port changes only fixed executable paths, Profile/node names, owned-child timeout handling, hidden process creation and a worker deadline margin. It retains the base renderer's supported modes. The existing AID node agent was restarted to load its extra entry; no model service, recording backend or publishing backend was restarted. A preflight first used an over-broad global idle assertion while only a 222 job was active; the separately launched 203 agent reload still occurred. Subsequent checks verified only one 203 agent process, no 203 assigned job was interrupted, and 222 job 622 remained running after the manager reload. Further maintenance should gate by the affected node rather than global activity.

## Real scheduler acceptance

Client-scoped, verified-TLS submissions used the existing protected douyin render credential and stable idempotency keys. Input was a small synthetic video, not a production recording. Two completed AID jobs:

| Job | Mode | Actual result |
|---|---|---|
| 623 | two-clip compose | gpu-203, H.264 1080x1920 + AAC, 6.021029 seconds |
| 624 | compliant 2K | gpu-203, H.264 1440x2560 + AAC, 4.000000 seconds |

Both results were downloaded through the authenticated manager API, SHA-256 verified and independently inspected using ffprobe. Both client key files independently see the new 203-only Profile and the unchanged 222-only original. No private worker endpoint or direct GPU execution was used for acceptance. Four targeted local port tests also passed, including Windows-compatible owned-process cancellation. Acceptance artifacts/state are in `output/qianchuan203-profile-verification` (QA files, not committed).

## Backups and rollback

203 node backup:
`C:\ProgramData\AIDGpuScheduler\backups\qianchuan-203-20261026-114328`

Manager configuration/client-scope backup:
`/home/neo/.local/state/aid-gpu-scheduler/backups/qianchuan-203-20261026-034739`

Each contains original configuration, manifests and a guarded rollback script. Revert only when no new-Profile task is running or queued. The manager rollback removes only this Profile's two douyin scope additions and restores its saved profiles/catalog configuration; it refuses concurrent configuration/scope drift. The separate node rollback restores agent configuration and removes the matching new worker, followed by an idle node-agent reload. No recording, output or job-history database restore is required. Model services remain untouched.

## Calling and limitations

Select `profile: "qianchuan-render-203"`; keep using `payload.qianchuanRenderRequest` with owned uploaded artifact IDs and the existing compose or single-clip compliant-2K protocol. Scheduler URL, CA and existing douyin keys remain unchanged. Selecting the original `qianchuan-render` still schedules to 222.

This task copies the **existing** rendering capabilities. The proposed legacy ASS subtitles/transitions/beep protocol was not activated. The Douyin application's old retry/editor routing was not automatically switched, and failed production tasks were not bulk restarted. Profile deployment/permission availability must not be presented as completion of that separate application integration.
