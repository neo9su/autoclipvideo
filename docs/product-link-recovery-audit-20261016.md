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
