# Issue 250: Qianchuan `scene_type` NameError

## Root cause

The GPU director worker's comparison-scene branch in
`gpu_service/main.py::_do_director_job` reads `scene_type` to decide whether to
build the split-screen filter. The deployed copy did not assign that local
from `clip` before the branch, so a Qianchuan clip entering the branch raised
`NameError: name 'scene_type' is not defined` during preprocessing.

`gpu_service_src/gpu_service.py` already contained the corresponding assignment;
the deployed worker copy had drifted from that source path. The fix restores the
assignment in `gpu_service/main.py` immediately after the clip's start and
duration are parsed, before the comparison check.

## Verification and retry safety

`tests/test_qianchuan_scene_type_regression.py` parses the deployed worker and
asserts that the assignment precedes the comparison branch. No production
worker, queue, database status, or video batch was restarted, interrupted, or
retried while diagnosing or fixing this issue. Group 4684 remains a separate,
operator-reviewed retry decision after this change is merged and deployed.
