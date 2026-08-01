# Issue #18 deployment verification

## Scope

This verification checks the deployed frontend/backend pair after the latest `master` revision. It does not run a production batch or mutate a video task.

## Evidence

- Backend API: `GET /api/v2/qianchuan/status` returned HTTP 200 and `qianchuan_available: true`, version `1.0.0`, with the expected 18–35 second duration range.
- Group API: `GET /api/groups` returned HTTP 200 and included Qianchuan fields (`qianchuan_status`, `qianchuan_final_video`, `qianchuan_error`) for each group.
- A completed sample group returned from the live API had `qianchuan_status: 2`, a non-empty final video, a non-empty audio path, a match score, and no error.
- The Qianchuan result endpoint for that sample returned HTTP 200 with `status: 2`.
- The Qianchuan download endpoint returned HTTP 200 with `content-type: video/mp4` and a non-zero content length.
- The served SPA index referenced the production JavaScript bundle. The served bundle SHA-256 matched the freshly built bundle from this revision.
- The built bundle contains the visible `千川投流版` label and `qianchuan_status` bindings, confirming that the deployed frontend includes the Qianchuan panel/status rendering.

## Build verification

The frontend was installed from its lockfile and rebuilt successfully with Vite. The production build generated the SPA index, CSS bundle, and JavaScript bundle without compilation errors.

## Result

The deployed environment is serving the current Qianchuan-enabled frontend and backend. The page can display the Qianchuan panel, task status, preview/download controls, and completed group video when the corresponding API state is present. No product-code correction was required for this verification.
