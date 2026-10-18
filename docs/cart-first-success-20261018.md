# Stop after the first confirmed cart attachment

The user clarified that one successful product attachment is sufficient. The previous fallback tried every candidate even after a success; a later ambiguous browser error could abort the task. The helper now returns immediately after the first confirmed success. Known unavailable links before that success continue to the next candidate. With no confirmed success, publication remains blocked. This does not treat an unverified browser action as success.

The latest server task at investigation was still 12313, with the earlier 'product not found' error, not a later new task. Source backup: `C:\Users\neo\douyin_backend\codex_rollbacks\cart-first-success-20261019-051841`. It contains original helper, hashes and rollback.py. Revert that helper and restart only the backend under guarded maintenance, with no live publishing task; do not restore a database or restart GPU.

Validation: eight targeted tests, including unavailable-first/success-next, successful-first/later-error-never-attempted, all candidates unavailable, ambiguous first result, alias matching and review controls. Code change is confined to publish_cart_flow.py; publishing confirmation remains required.
