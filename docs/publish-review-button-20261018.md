# Grey confirmation button across tasks

Live task 12318 was ready=true and clicked=false, with one confirmed attachment. The confirmation page used a global `busy` boolean that stayed true after sending a confirmation for a previous task. It disabled later tasks in the same tab. A screenshot captured before readiness also has no confirmation token, but the old UI gave no explanation.

The UI now records pending confirmation per task, preserves duplicate-submit protection for that task, and releases only known rejected confirmations. Other tasks are unaffected. Disabled-button hints explain missing screenshots, unchecked confirmation, preparation, and an already-sent request. Node VM tests reproduce confirming A then selecting B without network side effects; backend review tests remain green.

To preserve the user's live browser/task, the corrected HTML is served at `/frontend/publish-review.html` through the existing static-file mount. The platform entry and Vue source now use that URL. No backend/GPU restart was performed. The backend HTML constant was also patched for subsequent normal starts; the legacy `/publish-review` route retains its old in-memory HTML until an idle restart. Use the new static URL now.

Backup: `C:\Users\neo\douyin_backend\codex_rollbacks\publish-review-state-20261019-054015` (server local date). It contains originals, source hashes and rollback.py for the module, new static document and HTML entry. Rollback preserves the database and running tasks. No automatic database restore.

Live UI verification: opened the new page for task 12318, loaded its screenshot, checked the existing acknowledgement, and observed the Confirm button enabled. The Publish confirmation button was not clicked. Evidence is outside the repository at work/publish-review-evidence/review-button-enabled.png. Platform quick-check remains indeterminate and must be reviewed by the user.
