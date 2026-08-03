# Vue 3 + Vite

This template should help get you started developing with Vue 3 in Vite. The template uses Vue 3 `<script setup>` SFCs, check out the [script setup docs](https://v3.vuejs.org/api/sfc-script-setup.html#sfc-script-setup) to learn more.

Learn more about IDE Support for Vue in the [Vue Docs Scaling up Guide](https://vuejs.org/guide/scaling-up/tooling.html#ide-support).

## Emergency local-frontend / remote-GPU mode

The Mac is a UI-only client in this mode. `VITE_API_BASE` defaults to the remote
GPU backend (`http://10.190.0.203:8899`) and `VITE_WS_BASE` defaults to its
WebSocket endpoint. Do not start the repository backend, worker, model, or
media-processing services on the Mac.

Use the existing production bundle for the smallest local footprint:

```bash
cd frontend
npm ci                 # first time only
npm run build          # first time or after source changes
npm run preview -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. Stop the preview with `Ctrl-C`; it has no worker
or model child process. If it was backgrounded, stop only that preview process,
for example `pkill -f 'vite preview.*5173'`.

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
