# Durable Task Runner

`runner/ops/task_runner.py` is an isolated replacement for Fabrica heartbeat. It only owns its SQLite database and worker processes; it does not change application code, GitHub issues, PRs, or worktrees.

## CLI

```bash
python -m runner.ops.task_runner --db .runner/runner.sqlite3 scan
python -m runner.ops.task_runner --db .runner/runner.sqlite3 run-once
python -m runner.ops.task_runner --db .runner/runner.sqlite3 status
python -m runner.ops.task_runner --db .runner/runner.sqlite3 recover --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 scan --dry-run  # fetch without persisting
```

Set `TASK_RUNNER_WORKER` to a command template (supports `{issue_id}`), `TASK_RUNNER_HARD_TIMEOUT`, `TASK_RUNNER_NO_PROGRESS_TIMEOUT`, `TASK_RUNNER_LEASE_SECONDS`, `TASK_RUNNER_CONCURRENCY`, and `TASK_RUNNER_GH`. The default worker concurrency is one. Workers run in their own process group and are terminated (then killed) on timeout. GitHub scanning uses configurable `gh`; unavailable/invalid output safely yields no issues.

SQLite tables persist issues, runs, leases, and events. Startup recovery removes expired leases and moves running runs to `interrupted` with their issue `retryable`. `run-once` only selects queued/retryable work, so completed work is idempotent.

## launchd guidance (macOS)

Install a user LaunchAgent that invokes a wrapper script or absolute Python path. Keep the database under a persistent writable directory, set environment variables in the plist, and use `RunAtLoad` plus `StartInterval` (for example 60 seconds). Do not enable Fabrica heartbeat; stop/remove any old heartbeat LaunchAgent before production rollout. Run `recover --dry-run` first, then `recover`, and inspect `status` after deployment.

Example command (adapt paths):

```xml
<key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>/path/to/repo/runner/ops/task_runner.py</string><string>--db</string><string>/path/to/state/runner.sqlite3</string><string>run-once</string></array>
<key>RunAtLoad</key><true/><key>StartInterval</key><integer>60</integer>
```
