# Issue 223: Qianchuan diagnosis for groups 4675–4694

## Read-only production findings

The production checks were limited to `GET` endpoints and did not submit,
cancel, retry, or restart any work. The Qianchuan queue and GPU tasks were
left untouched.

- The Qianchuan service status endpoint reports available and healthy.
- Groups 4675–4684 report `qianchuan_status=-2` with the error
  `录像文件缺失，无法自动补齐。请重新上传或修复素材路径。`. Their result
  payloads contain a missing-media preflight with the exact recording ID and
  database filename, plus an operator action to restore that source MP4 and
  its SRT sidecar to the backend storage namespace.
- Group 4687 is a different failure: `商品强匹配不足: 0.41 < 0.58`.
  Its Qianchuan artifact is present and reported as available, so it must not
  be treated as a missing-media retry.
- Groups 4685–4686 and 4688–4694 report Qianchuan status 2 with ready artifacts.

## #222 deployment/effectiveness

The deployed group response includes the artifact availability fields added by
#222 (`*_file_status` and `*_available`). The Qianchuan result endpoint also
returns the #222-style preflight review and recovery action for 4675.

The recovery preflight is therefore deployed and was invoked. However, the
stored Chinese missing-media error was not included in the retry classifier's
marker list. As a result, a later safe retry would not have been admitted by
`claim_pipeline_start`, even after an operator restored the source media.
This change adds that exact marker and regression coverage; it does not alter
queue state or initiate a retry.

## Five-version reporting

The group endpoint reports the five UI versions independently: classic,
director, realistic, conservative, and Qianchuan. For the requested range,
the available/file-status fields distinguish a completed artifact from a
stale or absent path. A null Qianchuan output path on a `-2` group is
consistent with no Qianchuan result being generated; legacy local artifacts
cannot be associated with that field unless the database contains the artifact
path. Existing successful versions remain available and were not regenerated.

## Safe operational next step

Do not bulk-retry the range. First use the read-only diagnosis procedure from
`docs/QIANCHUAN_MISSING_MEDIA_RECOVERY.md` to restore and verify each listed
source MP4 and readable SRT sidecar. Only after every source reports ready
should an operator retry the affected missing-media groups individually. Keep
4687 separate until its product mapping or matching evidence is corrected.
