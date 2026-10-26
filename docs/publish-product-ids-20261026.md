# Product catalog IDs in publication pickers

Both create-task and batch-scheduling product options now show `ID: <catalog row id> · <product name>` next to the existing room tag. This uses the same `p.id` as the product library and checkbox selection, rather than the platform product ID.

Only the two product-label expressions were changed in the deployed immutable asset, preserving other production features and unrelated local upload work. Vue production build passed. Deployment verified HTTP HTML entry and asset SHA; publish task count stayed 1200. No backend restart, publishing action or database change.

203 backup and guarded rollback:
`C:\Users\neo\douyin_backend\codex_rollbacks\product-ids-20261026-142512`

Asset: `index-product-ids-b5c050e086c1.js`. Run the backup's rollback.py to restore the previous frontend entry. Refresh the browser to load the new entry. Visual browser verification was not performed.
