# C drive cleanup — 2026-10-24

203 C drive: 7.36 GiB before, 10.25 GiB after. Archived and removed six MP4-format files from neo AppData/Local/Temp, aged approximately 3 days. Source recordings and model caches were not changed.

Backup host 220: `/Users/claw/douyin-cleanup-archive/c-temp-20261024/`. Each original basename has a data file and JSON containing original absolute path, byte count and SHA-256. All six backups completed before deletion. Windows source hashes were compared with backup hashes immediately before deletion. All TEXT/CHAR/CLOB database columns were checked for references to each filename; none found.

203 audit: `C:\Users\neo\douyin_backend\codex_rollbacks\c-temp-20261024\manifest.json` and `removed.jsonl`.

Rollback: copy each archived file from 220 back to its manifest source path using a temporary destination filename, verify SHA-256 against its JSON, then rename to its original basename. Refuse to overwrite any existing different file. No database rollback required.

Verification: six archived source files removed; HTTP /health returned 200. Remaining 10.25 GiB is still limited headroom; further cleanup should target verified generated/temp artifacts or migrate storage, not source recordings.

AID configuration presence checks: URL, API key and API-key-file settings absent from Machine and SSH-user environment, `_uv3.bat`, project `.env`, backend `.env`. This does not inspect every possible process/user secret store. Scheduler workload submission remains unconfigured; no GPU workloads were manually submitted during cleanup.

## Second batch

Archived 509 files, 2,089,524,201 bytes, from old `_ststage`, `_stmodel.tar.gz`, and two abandoned temporary installer extraction directories. No process command line referenced these candidate paths at inspection time. Active model installations were preserved. Each archived member was hashed on 220 and compared with the manifest; each source was hashed again before removal. Windows removal journal uses flush/fsync.

220 backup: `/Users/claw/douyin-cleanup-archive/c-stage-20261024/archive.tar`, `manifest.json`, `complete.json`. 203 audit: `C:\Users\neo\douyin_backend\codex_rollbacks\c-stage-20261024`.

C available space after second batch: 12.22 GiB. Rollback: copy archive back to an accessible location on 203 and run `scripts/restore_c_stage_archive.py <archive.tar>` with Python 3.11+. It validates restored bytes and refuses to overwrite differing existing files. Restore helper syntax checked; no production restore performed.

A metadata walk of the recording directory timed out; no recording files were changed. The directory is not a junction, but individual network/symlink entries may explain slow inspection. Its actual local allocation and ongoing growth remain unverified.
