# 203 LatentSync pilot

User-authorized isolated deployment, 2026-10-30 (America/Edmonton). Preview only; not wired into production video creation or publishing.

- Profile: `latentsync-15-203`, node `gpu-203`, one GPU, maximum 15-second source window, 5–100-character replacement narration.
- Source: official ByteDance LatentSync commit `36ca2a32e942` (1.5-compatible code), model revision `32a20d29aead0498e3e885e90dbbe8027da1b61b`.
- Environment: `F:\aid-models\latentsync-1.5\venv`, Python 3.11, Torch 2.5.1+cu121. Official requirements installed; InsightFace built with existing Windows toolchain. CPU import/help preflight passed.
- Weights fetched through hf-mirror after direct Hugging Face connections failed. Core model SHA-256 `6440b49a7ccceff56cdc001f5f17605216337f5bbd66fa360139768926e23f51`; Whisper tiny `65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9`; both matched official LFS records.
- Adapter accepts only managed input artifact, bounded time window, narration and reference transcript. It uses existing OmniVoice inside the same scheduler lease, releases TTS GPU state, then runs LatentSync. A short freeze (up to 3 seconds) is allowed only for slightly longer new audio. Output is a 720-pixel-high pilot, not a production 2K export.
- No arbitrary commands, caller-supplied filesystem paths, automated publication or default production routing changes.
- Two setup-only Windows tasks were removed after completion.

Backups:
- 203: `F:\aid-models\latentsync-1.5\backups\20261031-042625` contains prior Agent config, hashes and rollback helper.
- Manager: `/home/neo/.local/state/aid-gpu-scheduler/backups/latentsync-20261030-202826` contains prior profiles/services and client scopes. Restore only this profile's additions if other admins have made later changes; do not overwrite newer unrelated configuration.

First test: AID job 943 failed because the adapter expected the wrong TTS-release response field; corrected to require `status=released`. Job 944 is the follow-up, with sub-10-second speech slowed to approximately 10 seconds; recording 45409, source 427.37–439.55 seconds, single-person frontal view. Job 944 SUCCEEDED on gpu-203 in 442 seconds. Output: H.264 408x720, 10.04 seconds, AAC 9.97 seconds, SHA-256 `339cb28038c6b7a0f90a3d36e0afc2b4f24a017e5db40a112f3928b423c9d175`. Full decode passed; three-frame visual inspection found no gross face corruption. Temporal lip-sync and voice naturalness still require playback review; this is a preview, not production approval. No commercial-clearance claim is made for third-party face-analysis weights; review dependencies before enabling paid-ad production.
