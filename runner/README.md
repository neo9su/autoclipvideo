# Durable Task Runner

`runner/ops/task_runner.py` is an isolated replacement for Fabrica heartbeat. It only owns its SQLite database and worker processes; it does not change application code, GitHub issues, PRs, or worktrees.

## CLI

```bash
python -m runner.ops.task_runner --db .runner/runner.sqlite3 scan
python -m runner.ops.task_runner --db .runner/runner.sqlite3 run-once --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 status
python -m runner.ops.task_runner --db .runner/runner.sqlite3 recover --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 preflight
python -m runner.ops.task_runner --db .runner/runner.sqlite3 recover-accepted-idle --dry-run
python -m runner.ops.task_runner --db .runner/runner.sqlite3 scan --dry-run  # fetch without persisting
```

`run-once --dry-run` opens the existing database read-only (or uses an in-memory empty store when it does not exist) and reports queued/retryable candidates as JSON. It does not acquire leases, write runs/events/state, or start worker processes. Use it to inspect what the next run would select.

`reconcile` compares durable non-terminal records and conservatively quarantines
ambiguous records instead of closing or force-requeueing them:

```bash
python -m runner.ops.task_runner --db .runner/runner.sqlite3 reconcile
```

`preflight` is a fail-closed single-flight check. It verifies that the state
directory is writable and that this coordinator can acquire the durable lock;
it never disables the host sandbox or expands the worktree allowlist. Run it
before starting a dispatcher and release the lock during controlled shutdown.

`recover-accepted-idle` bounds the emergency lane that previously caused
accepted-idle deadlocks. It records one deduplicated alert after 120 seconds,
fences the run at 180 seconds, releases its exact lease epoch, and requeues it
once. A second failure enters `recovery_needed` for manual hold rather than
waiting indefinitely. Use the dry-run mode before applying the action.

Set `TASK_RUNNER_WORKER` to a trusted command template (supports `{issue_id}`), `TASK_RUNNER_HARD_TIMEOUT`, `TASK_RUNNER_NO_PROGRESS_TIMEOUT`, `TASK_RUNNER_CONFIRM_TIMEOUT`, `TASK_RUNNER_BOOTSTRAP_TIMEOUT`, `TASK_RUNNER_LEASE_SECONDS`, `TASK_RUNNER_MAX_RETRIES`, `TASK_RUNNER_CONCURRENCY`, and `TASK_RUNNER_GH`. The default worker concurrency is one. Workers run in their own process group and are terminated (then killed) on timeout. GitHub scanning uses configurable `gh`; unavailable/invalid output safely yields no issues.
SQLite tables persist issues, runs, leases, sessions, and lifecycle events. Every run has an immutable `run_id`, `generation`, and session key. A run enters `accepted_idle` only while its session is being confirmed; lifecycle events distinguish session request/confirmation/bootstrap/activity and late events are fenced as audit-only. Startup recovery removes expired leases and moves running runs to `interrupted` with the `gateway_restart` error class and their issue `retryable`. `run-once` only selects queued/retryable work, so completed work is idempotent.

Trusted workers should validate the assigned worktree before writing. `runner.ops.worktree_contract.WorktreeContract` requires the assigned worktree, repository root, and branch to match; `preflight()` emits structured evidence and `bootstrap_payload()` carries the run, generation, nonce, protocol, branch, and tool profile. This is an application-level allowlist and does not disable the host sandbox or grant access to the main checkout. Session confirmation, bootstrap, progress, completion, lease release, and recovery are generation-fenced; late events are retained only as audit events. Retry budgets are persisted per issue generation and exhausted runs remain diagnosable instead of being dispatched forever. Artifacts, QA/deploy records, and external effects are durable and idempotent.

## P0 rollout and recovery runbook

1. **Preflight:** run `reconcile` in read-only operational review, verify the
   coordinator database directory is writable, and confirm only one heartbeat
   dispatcher owns the durable `heartbeat` lock. Do not start a second global
   heartbeat or widen the worktree allowlist.
2. **Startup:** run `recover --dry-run`, inspect the counts and then run
   `recover`. A restart fences active runs, expires old leases, and makes work
   retryable; it never declares a run complete.
3. **Fencing:** every worker envelope must retain its `run_id`, generation,
   lease epoch, protocol, and nonce. Reject stale or out-of-order progress;
   late cleanup is an audit event and cannot mutate newer state.
4. **Quarantine:** if reconciliation reports missing sessions, leases,
   worktrees, or evidence, leave the issue quarantined. Inspect the durable
   status and external artifacts, then explicitly requeue only after identity
   and evidence are verified.
5. **Safe cleanup:** stop the owning dispatcher, preserve the state database
   and audit records, terminate only the recorded worker process group, and
   remove a lease only with matching owner/run/generation. Never delete a
   worktree or state file as a recovery shortcut.
6. **Delivery gate:** completion requires verified PR/branch artifacts and
   canonical QA evidence. Deployment evidence is required when policy says so;
   otherwise record the explicit policy decision. Notifications are asynchronous
   and are never the source of truth.

## Controlled direct lane

The direct lane is an emergency fallback only. It must use a separate managed
worktree, an explicit available tool profile, and the same run/generation/lease
epoch envelope as the normal adapter. Run preflight and reconciliation first;
record remediation in the coordinator audit log, preserve the original run,
and stop the lane after its single bounded retry. Never mark an issue Done from
a direct-lane notification alone.

## launchd guidance (macOS)

Install a user LaunchAgent that invokes a wrapper script or absolute Python path. Keep the database under a persistent writable directory, set environment variables in the plist, and use `RunAtLoad` plus `StartInterval` (for example 60 seconds). Do not enable Fabrica heartbeat; stop/remove any old heartbeat LaunchAgent before production rollout. Run `recover --dry-run` first, then `recover`, and inspect `status` after deployment.

Example command (adapt paths):

```xml
<key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>/path/to/repo/runner/ops/task_runner.py</string><string>--db</string><string>/path/to/state/runner.sqlite3</string><string>run-once</string></array>
<key>RunAtLoad</key><true/><key>StartInterval</key><integer>60</integer>
```
