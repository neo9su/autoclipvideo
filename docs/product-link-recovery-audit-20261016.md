> Current policy (user confirmed): identical product names across different URLs are normal. Preserve each real product ID and URL as an option; do not label multiplicity as a conflict. The current manifest has 38 single-link candidates and 16 multiple-link candidates. Earlier conflict/held terminology below is historical and superseded. No option is automatically selected or written to production; source, URL identity, SKU and cart checks remain separate.

# Product link recovery audit — 2026-10-16

Read-only investigation; no production changes, publish retries, browser navigation, or service restarts.

## Confirmed causes

The product API returned 244 products: 176 have no product_url. Of enabled products, 175 lack a URL. Every one of the 175 dom_ identifiers equals dom_ plus the first 12 hexadecimal characters of MD5(product_name UTF-8); these are name-derived placeholders, not platform product IDs.

Production cart_capture.py generates this placeholder when the live cart DOM lacks an ID and sets product_url to an empty string. A historical shop import script uses the same hash and explicitly inserts an empty URL. Production publish_scheduler.py falls back from missing URL to product_id, and its legacy single-product branch uses product_douyin_id directly. This passes placeholders/IDs into a link input.

## Recovery evidence

A historical shop response capture contains product_id, promotion_id, product_info.name, product_info.detail_url and shop_info. A candidate matches one missing-link record by exact full name, shop ID and store name. Its HTTPS haohuo detail URL contains the same product ID as the response. This is an evidence-backed recovery candidate, not live link/cart validation.

The capture retains only 1,500 characters of each response, while the relevant original response was 73,923 characters. Two captures duplicate the same first product; they do not provide two recovered products. A fresh, complete response capture will be needed for bulk recovery unless other full historical artifacts are located.

Four missing-link records have exact-name URL-bearing catalogue counterparts. One has conflicting URLs; the captured candidate also differs from its name-matching catalogue counterpart in platform ID and URL. Therefore exact-name matching alone is unsafe. Keep these as review candidates; do not merge or overwrite based only on names.

All 14,792 historical live_cart_snapshots rows have empty product_url. The inspected single-product backup already corresponds to a record with a URL; the naming backup stores names/keywords rather than URLs.

## Next implementation and release boundary

Preserve full product/URL/shop associations from complete shop response objects, without cookies, tokens or request headers. Join on independently verified identity; retain ambiguous cases for review. Keep placeholder identity separate from actual platform identity. Do not generate URLs from placeholder hashes.

Before production writes, back up the database, create a per-row before/after manifest, check unchanged values, and support conditional rollback. Product link resolution must use stored real URLs for both single and multiple selections, and hold cart-required tasks with missing/invalid links rather than silently substituting IDs. Validate storefront availability and creator cart acceptance separately; syntactic URL checks cannot prove either.

Private catalogue snapshots and the candidate URL remain outside the public repository. No runtime fix or data recovery was applied in this audit.

## Follow-up retrieval attempts

Read-only checks covered 43 local SQLite files (42 with product tables, one without). Only one missing-link product had an exact-name URL candidate in the historical databases; the candidate belonged to a different catalogue identity. These copies do not provide an automatic restoration set.

The existing Buyin service reported online, but its current page had zero cached material-list responses. One historical signed list URL returned HTTP 200 with business error code 10001010A and a risk-environment message, not product data. That URL was not retried.

A normal shop-read request through the existing service failed before navigation with BrowserContext.add_init_script: Target crashed. No service restart, profile modification or production code change was performed. The service's online status is insufficient evidence of browser usability.

A separate temporary browser used the saved storage state without changing the shared profile. It navigated normally to the shop URL, ended at www.douyinec.com/, and captured no material-list responses. The temporary browser was closed. This did not validate the stored login state; it does not establish that all possible sessions are expired.

Bulk recovery still requires a working authenticated Buyin browser and complete list response capture. The existing single candidate remains review-only. No production products, cart snapshots or publishing tasks were updated; no publications were retried. Audit/request/result artifacts remain in a separate private working directory. The read-only GET and normal page navigation do not require production rollback; temporary audit files may be removed after retaining needed evidence.

## Successful authenticated page extraction (supersedes login-blocker diagnosis)

The existing service page still accepted read operations. Ordinary shop navigation succeeded without context-wide init-script injection and displayed the expected store and product cards. Therefore the earlier Target crashed failure does not establish that the whole browser or authenticated session was lost. The saved storage-state copy failed validation; the live persistent session remained usable.

A bounded, read-only React-props reader extracted scoped product objects already loaded by the shop UI. Internal list scrolling expanded the capture from 30 to 94 distinct platform product IDs. It does not fetch signed URLs, modify login state, add items to carts or alter product data. Unsafe numeric IDs are rejected. A stable count is explicitly not proof of catalogue completeness.

Offline matching requires exact full product name, shop ID from existing source metadata, and store name. HTTPS detail URL identity must match the real platform product ID. Of 176 missing-link records, 54 have matching candidates: 38 unique and 16 conflicting. All conflicts involve genuinely distinct platform product IDs, not merely different URL formatting; one title maps to five products. The remaining 122 have no qualified match in this run. Output retains all ambiguous identities for review and the original catalogue values for a later conditional restoration, without changing placeholder IDs.

Validation: five targeted Python unit tests passed; JavaScript syntax check passed; the staged page reader ran successfully against the actual authenticated shop page; the offline tool produced a 54-record review manifest. Private CSV has 73 candidate rows. No live URL availability or creator cart acceptance test has been performed, and no production row has been changed.

Sources evaluated under the solution-reuse workflow: [Playwright network events](https://playwright.dev/python/docs/network), [authentication reuse](https://playwright.dev/python/docs/auth), and [official Douyin Open Platform capability catalogue](https://op.jinritemai.com/docs/guide-docs/193?docLabel=1). The official catalogue lists affiliate material query/conversion capabilities; project app authorization and API compatibility remain unverified. Prefer the now-validated live-page read path for this recovery; evaluate official APIs only after verifying permissions. No dependencies were installed or paid services introduced.
