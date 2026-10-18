# Windows launcher console loop: 203

The interactive launcher repeatedly launched Uvicorn despite the SYSTEM backend already listening on 8899. Reproduced on Windows PowerShell: a single CIM result becomes `CimInstance`; its `.Count` is null, whereas `@($result).Count` is 1. The old conflict condition therefore evaluated false. Logs showed starts approximately every 13 seconds.

The fix wraps results at the caller, checks existing TCP listeners before launch (including same-session listeners and inaccessible process command lines), and hides new backend consoles. Production environment, logging, and child retry settings are preserved. Only the interactive launcher task was restarted; serving backend PID 3620 and GPU service PID 13980 were preserved. No model, rendering, or publishing test was submitted.

Production backup: `C:\Users\neo\douyin_backend\codex_rollbacks\launcher-singleton-20261019-025948` (Windows local date). Contains original script, hash manifest, drift-protected rollback.py, verification.json. To revert: execute rollback.py, then restart only DouyinBackend8899SusunInteractive to reload the original launcher. Do not restore the database or restart GPU services.

Validation: targeted launcher tests, Windows PowerShell syntax parse, live scalar-result reproduction, preserved listener PIDs, backend/GPU health HTTP 200, and no repeated start entries after activation.

Initial GPU sample: compute/encoder/decoder all 0%, 4487 MiB used of 16376 MiB, 43 C, 35.44 W. Worker reported all media-job categories idle; Qwen and OmniVoice reported models unloaded. This does not establish the cause of the earlier reported 100% utilization. Python services also include GPU watchdog, scheduler agent, ASR, Qwen, voice, Buyin session service, and encoding subprocesses; their existence alone is not abnormal.

Remaining limitations: no historical per-engine GPU telemetry to attribute the screenshot-time peak; no failover or real publishing exercise. Existing visible terminal windows may remain until closed separately. No broad Python termination was performed.
