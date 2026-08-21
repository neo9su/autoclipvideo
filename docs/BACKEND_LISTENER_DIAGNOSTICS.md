# Backend listener diagnostics and rollback

The backend listener diagnostic is read-only. It performs one TCP connect and a
GET to `/health`, classifying results as `healthy`, `port_refused`, `timeout`,
`http_error`, or another sanitized transport error. The diagnostic endpoint and
the Windows startup guard do not kill processes, restart services, retry probes,
flush queues, rerun videos, or modify task/media data.

Before any operator-approved recovery, verify that there are no active recording
tasks and no Qianchuan tasks. This is a safety gate, not an automation trigger;
the default remains no recovery action.

## Rollback

Revert the service-manager/monitoring implementation commit or PR and restore
the prior startup command. Do not modify the task database or media. Do not
stop or restart production during rollback without separate maintenance
approval and read-only verification that no active recording or Qianchuan task
is running.
