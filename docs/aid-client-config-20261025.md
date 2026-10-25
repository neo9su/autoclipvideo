# AID client authentication configuration — 2026-10-25

Configured manager URL https://10.190.0.222:18120 with API-key-file authentication and strict TLS verification. No credential values belong in Git or logs.

203 private files: C:\ProgramData\AIDGPU\douyin-client (client.key, ca.crt, environment.json). Directory inheritance removed: SYSTEM and Administrators full control, AISTATION\susun read access. Launcher C:\douyin_login\_uv3.bat exports URL, API-key-file path and CA path; no key value embedded. Original launcher retained privately as uv3-before-aid-20261025.bat. Susun user environment settings also installed, with previous values recorded.

CA obtained through an existing strict-host-key SSH trust path from /home/neo/.config/aid-gpu-scheduler/tls/ca.cert.pem on 222. The user-supplied /etc/aid-gpu/aid-gpu-manager-ca.crt path did not exist on that host. SHA-256 certificate fingerprint: 74:3A:64:7F:8E:EA:84:10:13:DF:F5:F1:04:8F:FB:DB:2B:AE:E5:DE:A5:8F:55:AE:C1:7E:33:C1:4C:42:47:FE.

203 susun-context validation: GET /health, /v1/profiles and /v1/snapshot all HTTP 200. TLS verification enabled. Credential scope returned only douyin-gpu-processing, enabled, default priority 45. No job submitted, no artifact uploaded. These read-only checks do not validate a project payload or execution adapter.

Audit: C:\Users\neo\douyin_backend\codex_rollbacks\aid-config-20261025\verification.json and user-env-before.json. Rollback helper deployed there; must run as elevated susun and refuses to overwrite a subsequently modified launcher. Private credential files are retained during rollback. Syntax checked; production rollback not executed.

Local Codex client configuration stored outside repository under ~/.config/aid-gpu/douyin-203; environment.sh exports only URL and credential/CA file paths. Credential file permissions 0600, directory 0700.

No backend restart performed for this configuration-only change. Existing backend processes do not retroactively gain new environment variables; patched launcher applies on next normal restart. This configuration does not convert the existing legacy direct-worker pipeline into an AID adapter. Project-specific payload integration and an explicitly authorized execution test remain separate work.
