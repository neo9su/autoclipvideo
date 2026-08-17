# GPU service storage admission

Transcription uploads use `DISK_MIN_FREE_GB` (default `20`) and
`DISK_UPLOAD_HEADROOM_GB` (default `5`). The service requires the larger of the
minimum free space or the upload size plus the reserve, so a volume with about
86 GiB free is not rejected solely because an obsolete 80 GiB batch threshold
was configured. Set these variables in the GPU service environment when the
host's storage profile requires a different safety margin. The disk guard may
still clean completed outputs when `DISK_QUOTA_GB` and `DISK_GUARD_GB` indicate
that cleanup is needed.
