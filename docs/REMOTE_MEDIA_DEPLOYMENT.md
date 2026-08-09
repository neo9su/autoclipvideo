# Remote route and media deployment contract

The GPU backend is the only media worker. The host directory configured by
`BACKEND_RECORDINGS_DIR` is mounted as `/app/recordings`; the process uses
`STORAGE_DIR=/app/recordings`. Database media values are basenames or container
paths, never macOS, SMB, or Windows paths. No SMB mount is required.

## Reproducible deployment

On the GPU host, first capture the current container, route, volume, health,
and database state. Save stdout, stderr, and the exit code in the deployment
audit record. Then build and recreate only the backend service from the target
commit:

```sh
git fetch origin
git checkout <commit>
docker compose --env-file deploy/gpu-backend.env -f deploy/docker-compose.gpu-backend.yml config
docker compose --env-file deploy/gpu-backend.env -f deploy/docker-compose.gpu-backend.yml up -d --build douyin-backend
docker compose --env-file deploy/gpu-backend.env -f deploy/docker-compose.gpu-backend.yml ps
deploy/verify-remote.sh http://127.0.0.1:8899
```

`verify-remote.sh` checks both status routes, the actual POST route contract,
the deployment role, and the container-only media contract. A status response
is not a substitute for a real generation run: a group request must return a
business response or a documented 4xx validation response.

## Media evidence

Before a run, select a database recording whose source exists in the mounted
directory and record its basename, byte size, and SRT sidecar byte size. The
supported sidecars are `<name>.srt` and `<name>.mp4.srt`; an empty SRT is not
valid evidence. Do not copy or delete source recordings during verification.
