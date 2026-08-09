# Durable Task Runner

`runner/ops/task_runner.py` is an isolated replacement for Fabrica heartbeat. It only owns its SQLite database and worker processes; it does not change application code, GitHub issues, PRs, or worktrees.

## CLI

```bash
python -m runner.ops.task_runner --db .runner/runner.sqlite3 scan
python -m runner.ops.task_runner --db .runner/runner.sqlite3 run-once --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 status
python -m runner.ops.task_runner --db .runner/runner.sqlite3 recover --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 scan --dry-run  # fetch without persisting
```

`run-once --dry-run` opens the existing database read-only (or uses an in-memory empty store when it does not exist) and reports queued/retryable candidates as JSON. It does not acquire leases, write runs/events/state, or start worker processes. Use it to inspect what the next run would select.

## P0 rollout and recovery runbook

Before rollout, run `reconcile` in read-only mode and verify that exactly one scheduler/heartbeat dispatcher owns the persistent state. Confirm the Gateway/CLI protocol compatibility, that the state directory is writable, and that every configured worker path is an explicitly assigned worktree (never the main checkout). Preflight failures are structured and fail closed; do not widen the allowlist to make a worker start.

The coordinator is authoritative for run, lease, session, event, artifact, QA, deployment, and outbox state. GitHub labels and issue states are a projection. A reconciliation record is marked `quarantine` when remote and durable state disagree or required evidence is ambiguous. Quarantine must be reviewed by an operator; it must not be force-closed or silently requeued.

For recovery, stop duplicate dispatchers, run `recover --dry-run`, inspect `status`, then run `recover`. Expired leases are removed and active runs are interrupted and requeued with an audit trail. A worker may be requeued only after its prior generation is fenced. Late heartbeats, completion, or cleanup from an old generation are audit-only and cannot mutate the new lease or terminal state. Safe cleanup deletes only a lease matching issue, owner, run, and generation; never remove another generation's lease or state database.

Completion requires verified worker readiness/activity plus the required PR artifact, canonical QA evidence, and deployment smoke evidence (or an explicit out-of-scope policy record). External GitHub/PR/deploy effects are queued by idempotent outbox keys and notification delivery is non-authoritative. On rollback, preserve the database and evidence, quarantine affected records, and use a reviewed manual recovery rather than deleting durable history.

Set `TASK_RUNNER_WORKER` to a trusted command template (supports `{issue_id}`), `TASK_RUNNER_HARD_TIMEOUT`, `TASK_RUNNER_NO_PROGRESS_TIMEOUT`, `TASK_RUNNER_CONFIRM_TIMEOUT`, `TASK_RUNNER_BOOTSTRAP_TIMEOUT`, `TASK_RUNNER_LEASE_SECONDS`, `TASK_RUNNER_MAX_RETRIES`, `TASK_RUNNER_CONCURRENCY`, and `TASK_RUNNER_GH`. The default worker concurrency is one. Workers run in their own process group and are terminated (then killed) on timeout. GitHub scanning uses configurable `gh`; unavailable/invalid output safely yields no issues.
SQLite tables persist issues, runs, leases, sessions, and lifecycle events. Every run has an immutable `run_id`, `generation`, and session key. A run enters `accepted_idle` only while its session is being confirmed; lifecycle events distinguish session request/confirmation/bootstrap/activity and late events are fenced as audit-only. Startup recovery removes expired leases and moves running runs to `interrupted` with the `gateway_restart` error class and their issue `retryable`. `run-once` only selects queued/retryable work, so completed work is idempotent.

Trusted workers should validate the assigned worktree before writing. `runner.ops.worktree_contract.WorktreeContract` requires the assigned worktree, repository root, and branch to match; use its `bootstrap_payload()` as the first activity report. This is an application-level allowlist and does not disable the host sandbox or grant access to the main checkout. Session confirmation, bootstrap, first activity, completion, lease release, and recovery are generation-fenced; late events are retained only as audit events. Retry budgets are persisted per issue generation and exhausted runs remain diagnosable instead of being dispatched forever.

## launchd guidance (macOS)

Install a user LaunchAgent that invokes a wrapper script or absolute Python path. Keep the database under a persistent writable directory, set environment variables in the plist, and use `RunAtLoad` plus `StartInterval` (for example 60 seconds). Do not enable Fabrica heartbeat; stop/remove any old heartbeat LaunchAgent before production rollout. Run `recover --dry-run` first, then `recover`, and inspect `status` after deployment.

Example command (adapt paths):

```xml
<key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>/path/to/repo/runner/ops/task_runner.py</string><string>--db</string><string>/path/to/state/runner.sqlite3</string><string>run-once</string></array>
<key>RunAtLoad</key><true/><key>StartInterval</key><integer>60</integer>
```
