# Vue 3 + Vite

This template should help get you started developing with Vue 3 in Vite. The template uses Vue 3 `<script setup>` SFCs, check out the [script setup docs](https://v3.vuejs.org/api/sfc-script-setup.html#sfc-script-setup) to learn more.

Learn more about IDE Support for Vue in the [Vue Docs Scaling up Guide](https://vuejs.org/guide/scaling-up/tooling.html#ide-support).

## Emergency local-frontend / remote-GPU mode

The Mac is a UI-only client in this mode. `VITE_API_BASE` defaults to the remote
GPU backend (`http://10.190.0.203:8899`) and `VITE_WS_BASE` defaults to its
WebSocket endpoint. Do not start the repository backend, worker, model, or
media-processing services on the Mac.

Use the idempotent launchd installer for a supervised production bundle:

```bash
./scripts/install_frontend_launchd.sh
```

The installer rebuilds from the current checkout, replaces the existing
`com.douyin-recorder.frontend-preview` user service, and enables `KeepAlive`.
Open `http://127.0.0.1:5173`; the preview has no worker or model child process.
To inspect the service, use `launchctl print gui/$UID/com.douyin-recorder.frontend-preview`.

Verification from the Mac:

```bash
python3 - <<'PY'
import urllib.request
for path in ('/api/status', '/api/gpu/status'):
    with urllib.request.urlopen('http://10.190.0.203:8899' + path, timeout=8) as response:
        print(path, response.status)
PY
lsof -nP -iTCP:5173 -sTCP:LISTEN
lsof -nP -iTCP:8899 -sTCP:LISTEN
lsof -nP -iTCP:8877 -sTCP:LISTEN
```

Only port 5173 should be listening locally. Ports 8899 and 8877 must remain
owned by the remote GPU host; all API, queue, transcription, TTS, vision,
encoding, quality, and video-generation operations are sent there.
