# GPU-only media storage policy

The Mac backend is a control plane: it records source files, uploads them once to the remote GPU, and downloads explicit results. It must not run ffmpeg, ffprobe, local ASR, local TTS, local composition, or local quality checks as a job fallback. If the GPU is offline, the job remains pending and is retried by the remote worker.

## Transfer accounting

Each recording tracks `transfer_node`, `upload_bytes`, `download_bytes`, and `temp_file_count`. Uploads are bounded by `GPU_UPLOAD_CONCURRENCY` (default 1), use a stable `Idempotency-Key`, and retry only transient failures. The file is streamed from disk rather than read into a second full-size memory buffer.

## SMB isolation

`recordings/` is the local capture/input directory and `gpu_storage/` is remote-worker storage; neither is a required SMB share. Do not export either directory from macOS File Sharing. If a share is required for unrelated operations, export a separate non-media directory and keep it outside both paths. Use application download endpoints for results instead of exposing the media directories. This prevents external SMB discovery/scanning from walking large media trees and keeps source recordings isolated from GPU artifacts.

## Audited paths

Classic clipping, director composition, Qianchuan composition, transcription, and TTS now fail/wait at the remote boundary instead of invoking local media fallbacks. Static boundary tests cover the local media guard, loopback GPU rejection, storage policy, and classic clipping fallback reachability.
