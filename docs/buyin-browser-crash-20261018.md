# Buyin resident browser crash on 203

Windows Application Error events repeatedly identify bundled Chromium 151.0.7922.34 (`C:\douyin_login\browsers\chromium-1234\chrome-win64\chrome.exe`), faulting chrome.dll, exception c0000409. The service treated every closed browser as a reason to immediately relaunch at the next 30-second watchdog check; the restart counter reached 168. The exception code alone does not establish a particular memory/security bug.

A controlled comparison in the same scheduled-task user/session and fresh independent profiles reproduced the bundled-browser failure while loading the Buyin login page. Installed Chrome 155.0.8059.80 survived navigation, eight seconds of waiting, and JavaScript evaluation. No publishing or product collection was submitted.

Fix deployed to `C:\douyin_login\buyin_session_service.py` through scripts/prepare_buyin_browser_deploy.py:
- Select the installed Chrome Playwright channel.
- Copy the old profile to chromium_profile_buyin_chrome, leaving the original intact for rollback. Cookies and profile contents stay on the server and are not committed.
- Limit automatic recoveries to three per service run with 60/120/240-second waiting periods. Explicit Show Login Window resets the recovery budget.
- Continue accepting the explicit show request while recovery is paused.

Activated only DouyinBuyinSessionOnLogon after its existing stop flag allowed a graceful exit. New service PID 14240 and Chrome PID 13992; state reports online, reusing the existing login. The user's ordinary Chrome and production backend/GPU services were not restarted.

Backup: `C:\Users\neo\douyin_backend\codex_rollbacks\buyin-browser-20261019-031351` (Windows local date), including original source, before/after hashes, rollback.py. Rollback: gracefully stop this Buyin service, run rollback.py, then start only DouyinBuyinSessionOnLogon. The original profile path is restored by reverting the source. Never restart backend or GPU for this rollback. Retain the new profile for review rather than deleting it.

Validation: production Python compilation, targeted restart-budget/backoff/manual-reset tests, controlled browser comparison, and production online-state verification. The exact underlying bundled Chromium crash remains undetermined; the tested replacement avoids it. Future installed Chrome updates remain a compatibility consideration. No real publishing test was performed.
