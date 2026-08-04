# Media storage and SMB isolation

The Mac `recordings/` tree is a control-plane cache for source uploads and downloaded
artifacts. It is not required as a network share by the GPU workflow. The GPU worker
uses its own `STORAGE_DIR` (normally `gpu_storage`/`/data/douyin-recordings`) and
receives only explicit HTTP control-plane transfers.

Recommended macOS isolation:

1. Do not include `recordings/`, `recordings/director_outputs/`, `recordings/gpu_storage/`,
   `voice_output/`, or temporary media directories in a Finder/SMB shared folder.
2. If an existing share contains the project root, remove the share or move the
   workflow cache outside that share. Keep the SMB export as a separate, non-media
   directory with read-only access where possible.
3. Verify the active exports in **System Settings → General → Sharing → File Sharing**
   and remove any `recordings` or project-root entry that is not explicitly needed.
4. Keep GPU source/result storage on the GPU host. The Mac should retain only the
   minimum control-plane files and can clean successful downloads after publish.

The application now records the execution node and transfer counters in the transfer
object used by uploads. Jobs wait for the remote GPU instead of invoking local ffmpeg,
ASR, TTS, thumbnail, quality, or final-video processing.
