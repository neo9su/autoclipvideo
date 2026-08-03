# Remote GPU-only media workflow

The Mac backend is a control plane. It stores incoming recordings and small control-plane artifacts, submits media jobs to the configured remote GPU node, and downloads completed outputs. It must not invoke ffmpeg, ffprobe, local ASR/TTS, local composition, local quality checks, or local post-processing.

## Storage and SMB isolation

`recordings/` is the control-plane input/output cache and must not be used as an SMB share. Keep it outside any macOS File Sharing export, or disable sharing for the parent directory. `gpu_storage/` is GPU-node storage and is not the same directory; it should be private to the GPU service and never mounted into the Mac share. If users need source-video access, export a separate read-only directory containing explicit copies, not the live `recordings/` tree.

Recommended macOS checks:

```sh
sharing -l
smbutil view //localhost
```

Remove `recordings` from File Sharing, and restart sharing only through System Settings after confirming no workflow endpoint depends on SMB. The workflow does not require SMB, CIFS, rsync, or scp.

## Transfer accounting

Every upload carries `X-Idempotency-Key` derived from the input bytes, `execution_node=remote-gpu`, and a bounded retry policy. The `gpu_transfers` table records the input size, uploaded bytes, job id, node, and downloaded bytes. GPU-unavailable states remain queued; they never trigger local media processing.
