# Issue 227: Qianchuan diagnosis for groups 4675–4694

## Scope and safety

The diagnosis is read-only. It does not call retry or bulk-retry endpoints,
change SQLite state, stop GPU work, or regenerate any successful video. The
existing Qianchuan queue remains the source of truth and is intentionally not
drained or modified.

## Findings

### Groups 4675–4684: missing source media, not a path-normalization false negative

The deployed preflight recorded the exact source recording IDs 20204–20213 and
the database filenames as unavailable in the backend storage namespace. The
read-only recovery diagnostic checks those exact filenames, their MP4
readability, and both supported SRT sidecar forms. It does not translate an
absolute Windows drive path or substitute a basename, so a missing result is
not silently converted into a different file.

The path contract already normalizes relative Windows separators (for example,
`素材\\源视频.mp4`) below the mounted storage root, while rejecting drive,
absolute, and parent-traversal paths. Therefore these failures should be
treated as genuinely missing from the backend mount until the operator proves
both the source MP4 and a readable SRT sidecar with the read-only diagnostic.

### Group 4687: independent product-match failure

The stored reason `商品强匹配不足: 0.41 < 0.58` is produced by the Qianchuan
matcher using the configured 0.58 threshold. It is not a missing-media error,
and the Qianchuan artifact/status evidence for this group must remain separate
from the 4675–4684 recovery path. Lowering the threshold or retrying it would
turn a data-quality rejection into an unverified ad-material decision; no such
change is safe from this diagnosis.

### Safe code defect fixed

The Python helper recognized the deployed Chinese missing-media message, but
the SQL predicate used by `claim_pipeline_start` did not. After an operator
restores and verifies the exact source media, a narrowly scoped retry would
therefore still be rejected by the atomic claim guard. This PR adds the same
Chinese marker to that SQL predicate and adds a regression test. It does not
make any retry request or alter the status of any group.

## Operator recommendation

Keep successful groups 4685–4686 and 4688–4694 untouched. For 4675–4684,
restore only the exact source MP4/SRT assets through the approved operator
storage-sync process, rerun the read-only diagnosis, and require every source
to report readable before considering individual recovery. Keep 4687 blocked
pending product mapping/matching evidence and an explicit human decision.
