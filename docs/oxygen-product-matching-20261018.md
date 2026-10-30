# Oxygen hairstyle cart matching

The user confirmed the spoken/ASR name 氧气粒子 means the catalogue name 氧气栗子 and requested prefix matching on 氧气. Previous automatic matching scored catalogue keywords and returned one product only. Product 730's manually supplied keywords included 氧气 despite its name being 夺回&人生, causing irrelevant results.

New matching uses the confirmed 氧气 prefix against product names. It selects all enabled, URL-valid matches in the video's room plus unassigned products, without a cross-room fallback. Distinct product names are not required. URL variants with the same host and platform id are deduplicated; distinct product links remain selectable. Manual search and automatic matching use the same Oxygen prefix. Other explicit searches match product names; unrelated automatic matches retain the prior best-product fallback. Responses retain the legacy product field and additionally return products, query, and the five-product platform limit.

Live group 5344 returns four product rows: 19, 74, 741, 742. The actual production UI was tested: search 氧气, select the oxygen video, click 自动匹配; all four checkboxes became selected and 夺回 was absent. The create modal was cancelled without submitting. Current task 12313 already selected those four products and failed at Douyin link attachment; old task 12311 had been removed concurrently. An attempted guarded update found no old row and changed no task data. No task was recreated or retried.

Publishing additionally tries all explicitly selected related product links. A known ProductLinkUnavailable result is recorded and the next selected link is attempted. Ambiguous/browser errors still abort. At least one confirmed attachment is required; all unavailable links stop publication. The review page reports actual attached count and names/reasons of rejected links before the human confirms. This does not guarantee that a currently unsupported link becomes usable or that account permissions change.

Validation: 17 targeted Python tests (alias, room, disabled/blank URLs, deduplication, attachment fallback, all-failed and ambiguous failures, review replay) and two Node tests; frontend build; live matching API and checkbox UI. No new video was published in this round. Screenshot: outside repository at work/publish-review-evidence/oxygen-products-selected.png.

Production backups (Windows local date):
- Backend matching: publish-catalog-20261019-051108.
- Frontend HTML/assets: publish-selection-20261019-051225; active asset index-publish-selection-b75af74a4673.js, previous asset retained.
- Link fallback and review summary: publish-cart-fallback-20261019-051535.

For rollback, restore the cart-fallback backup first and matching backup second, then restart only the backend through guarded maintenance while no publishing task is active. The matching changes use an optional response field, so restoring the frontend entry independently is safe. Each backup has hashes, original files and rollback.py. Do not restore the database or restart GPU. The shared activation wrapper accepts a failed taskkill only when the captured PID is proven gone, addressing the previously observed scheduled-task shutdown race.

Remaining limitation: the new per-link fallback is unit-tested but was not exercised against Douyin by posting another work. The four selected links may still require account authorization or catalogue correction. More than five matches require reducing the selection; the UI warns rather than silently dropping products or posting duplicate works.

Final cart activation encountered the known taskkill shutdown race while PID 4172 was still listed; the guard restored the original owner. Follow-up verified new backend PID 16244 started after all three fallback/review files were written, source hashes matched the manifest, HTTP health was 200, maintenance was false, and GPU PID stayed 13980. The activation exception is recorded explicitly; verification.json accompanies publish-catalog-activation-20261019-051604. The matching API still returned [19,74,741,742], and task 12313 remained failed without a retry.
