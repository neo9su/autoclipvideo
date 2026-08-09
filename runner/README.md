# Durable Task Runner

`runner/ops/task_runner.py` is an isolated replacement for Fabrica heartbeat. It only owns its SQLite database and worker processes; it does not change application code, GitHub issues, PRs, or worktrees.

## CLI

```bash
python -m runner.ops.task_runner --db .runner/runner.sqlite3 scan
python -m runner.ops.task_runner --db .runner/runner.sqlite3 run-once --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 status
python -m runner.ops.task_runner --db .runner/runner.sqlite3 recover --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 reconcile --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 reconcile-accepted-idle --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 scan --dry-run  # fetch without persisting
```

`run-once --dry-run` opens the existing database read-only (or uses an in-memory empty store when it does not exist) and reports queued/retryable candidates as JSON. It does not acquire leases, write runs/events/state, or start worker processes. Use it to inspect what the next run would select.

Set `TASK_RUNNER_WORKER` to a trusted command template (supports `{issue_id}`), `TASK_RUNNER_HARD_TIMEOUT`, `TASK_RUNNER_NO_PROGRESS_TIMEOUT`, `TASK_RUNNER_CONFIRM_TIMEOUT`, `TASK_RUNNER_BOOTSTRAP_TIMEOUT`, `TASK_RUNNER_LEASE_SECONDS`, `TASK_RUNNER_MAX_RETRIES`, `TASK_RUNNER_CONCURRENCY`, and `TASK_RUNNER_GH`. The default worker concurrency is one. Workers run in their own process group and are terminated (then killed) on timeout. GitHub scanning uses configurable `gh`; unavailable/invalid output safely yields no issues.
SQLite tables persist issues, runs, leases, sessions, and lifecycle events. Every run has an immutable `run_id`, `generation`, and session key. A run enters `accepted_idle` only while its session is being confirmed; lifecycle events distinguish session request/confirmation/bootstrap/activity and late events are fenced as audit-only. Startup recovery removes expired leases and moves running runs to `interrupted` with the `gateway_restart` error class and their issue `retryable`. `run-once` only selects queued/retryable work, so completed work is idempotent.

## P0 rollout and recovery runbook

1. Stop the old heartbeat and run `recover --dry-run`, then `recover`. Start exactly one coordinator against a persistent writable database; a second coordinator must fail its single-flight preflight rather than competing for slots.
2. Run `reconcile --dry-run` during shadow mode. Records with missing runs, mismatched generations, or accepted-without-readiness are reported. Run without `--dry-run` only after review; it quarantines ambiguous records and never force-closes them.
3. Run `reconcile-accepted-idle` on the heartbeat interval. At 120 seconds it emits one deduplicated alert. At 180 seconds it fences the run, releases its lease, and requeues it once. A second failure becomes `recovery_needed` for manual hold; it never waits indefinitely.
4. For recovery, inspect `status`, preserve the audit events, and verify the issue/PR/worktree before retrying. A stale worker may finish only as an audit event because `(run_id, generation, lease_epoch, seq)` fencing rejects its mutation.

The controlled direct lane is an emergency fallback only: use an isolated managed worktree, validate `WorktreeContract.preflight()` first, and use an explicit trusted tool profile. It is not an alternate completion path and must still produce the same run, artifact, QA, and deployment evidence. Diagnostics are intentionally generic and must not contain credentials or host-specific paths in public notifications.

Trusted workers should validate the assigned worktree before writing. `runner.ops.worktree_contract.WorktreeContract` requires the assigned worktree, repository root, and branch to match; use its `bootstrap_payload()` as the first activity report. This is an application-level allowlist and does not disable the host sandbox or grant access to the main checkout. Session confirmation, bootstrap, first activity, completion, lease release, and recovery are generation-fenced; late events are retained only as audit events. Retry budgets are persisted per issue generation and exhausted runs remain diagnosable instead of being dispatched forever.

## launchd guidance (macOS)

Install a user LaunchAgent that invokes a wrapper script or absolute Python path. Keep the database under a persistent writable directory, set environment variables in the plist, and use `RunAtLoad` plus `StartInterval` (for example 60 seconds). Do not enable Fabrica heartbeat; stop/remove any old heartbeat LaunchAgent before production rollout. Run `recover --dry-run` first, then `recover`, and inspect `status` after deployment.

Example command (adapt paths):

```xml
<key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>/path/to/repo/runner/ops/task_runner.py</string><string>--db</string><string>/path/to/state/runner.sqlite3</string><string>run-once</string></array>
<key>RunAtLoad</key><true/><key>StartInterval</key><integer>60</integer>
```
