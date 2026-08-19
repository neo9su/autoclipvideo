# Orphaned recording clip inventory

Issue #225 concerns `recording_clips` IDs 4675–4694 and their source recording/group lineage. Diagnosis must be performed against database copies, not through the running backend. The inventory tool is intentionally read-only:

```bash
python scripts/inventory_orphaned_recording_clips.py \
  --db /path/to/production-export.db \
  --db /path/to/backup-or-replica.db \
  --clips 4675-4694 > inventory-4675-4694.json
```

The first `--db` is labeled `authoritative_candidate` for report readability only; it is not trusted automatically. The report includes every found clip, referenced recording, recording `group_id`, group row, and the five style status columns (`classic_status`, `director_status`, `creative_status`, `realistic_status`, `conservative_status`). Missing recordings are reported as `orphaned_clip_ids`; missing groups are reported separately as `orphaned_group_clip_ids`.

## Interpretation

- `single_database_only`: no causal conclusion is safe; compare a production export with a backup/replica.
- `consistent_across_supplied_databases`: the same orphan references occur in every supplied copy; inspect restore/migration history and foreign-key enforcement before proposing repair.
- `differs_across_supplied_databases`: likely stale/partial copy, replication/path divergence, or restore/migration discrepancy; identify the authoritative lineage before any repair.
- `no_orphan_in_supplied_databases`: the monitor finding is not reproduced by the supplied copies; inspect database path selection, WAL/export timing, and schema identity.

The command uses SQLite `mode=ro` and `PRAGMA query_only=ON`. It does not run migrations, issue writes, delete rows, retry videos, call services, or interrupt Qianchuan. No data repair should be inferred or performed from the JSON alone. Take a filesystem/database backup before any separately approved repair, and require an explicit duplicate check plus a Qianchuan non-interruption check in that repair's worker/PR.
