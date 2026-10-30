# Production identity and edit-quality audit — 2026-10-30

## Findings verified against live203 source and twelve recent recordings

1. `analyzer._srt_to_text` destructively used `text[::step][:4000]`. Eleven sampled transcripts exceeded4,000 characters. This removed characters inside names and sentences before both LLM analysis and product-short-name matching. It is a deterministic preprocessing defect, independent of ASR quality.
2. The prompt explicitly suggests generic appearances such as 大波浪卷发 as `wig_model`. This field is therefore not an authenticated product name. Eleven of twelve recording rows had null `product_hits`; the remaining row only had 大波浪,卷发.
3. Production `product_keywords.load_short_names` reads only enabled products with manually populated short_name, globally rather than per room. Blank short_name excludes a title from this route. Historical disabled products can still be valid naming references even when ineligible for a cart.
4. Existing timestamped catalogue and homophone review helpers are not called by this production analysis path. Full-cue retrieval found candidate mentions in11/12 samples; this is NOT11 confirmed identities. Generic title fragments (一顶,爆款) and conversational 人生 demonstrate candidate false positives.
5. Source45497/group5595 has1,838 cues and12,996 characters in the audit's normalized text. It mentions 人生/夺回&人生 and 琥珀精灵, while the stored model is 刘海假发 and product_hits is null. Multiple mentions cannot be assigned to the entire recording: speech time and worn object must be verified.
6. Group reuse is based on model/color and substring similarity, then merges product keywords. This can join different named products that share appearance. Variant generation chooses from original full recordings without passing the group's target name/window into selection, then keeps the first successful result. Both require interval-level identity integration before claiming same-SKU output.
7. `build_opening_hook` searched all recording scenes and estimated spoken-word times by character ratio. This can introduce another identity and fragment spoken sentences. The pool defect is now fixed; word-alignment and visual-effect ranking remain open.
8. `cart_capture.match_group` marks `consistent` for appearance/style OR a loose first-four-character name hit. It stores ALL cart IDs from the time window, separately from `matched`. These fields describe historical cart presence/loose retrieval, not proof that every listed product matches the video. Do not infer actual published cart contents from this field alone.

## Applied repairs

- Replaced destructive character sampling with complete contiguous cue passages across the recording, explicitly separated as excerpts, capped at4,000 characters. This is bounded context sampling, not full-transcript identification; names outside the sampled passages can still be missed.
- Opening candidates now come only from selected segments, respecting their exact boundaries and gaps. This prevents introduction of additional source regions; it does not prove the existing selected segments share an identity.
- Added a repeatable read-only full-cue catalogue audit with timestamps, raw speech context and product IDs. It never renames a group, edits subtitles or authorizes a cart.

Production backup: `C:\Users\neo\douyin_backend\codex_rollbacks\identity-quality-20261030-223720`.
Source changes: `backend/analyzer.py::_srt_to_text`, `backend/editor.py::build_opening_hook` only, applied to actual production files with hash guards. Existing caption repair preserved. Rollback includes before/after files, manifest and rollback.py.
Activated with the existing idle-guarded interactive backend maintenance helper. No GPU restart, new GPU submission, media replacement or explicit database migration. Backend startup may resume normal queues.

## Validation

26 targeted tests passed (new sampling/selection guard, catalogue evidence and subtitle regression suites). Both deployed file hashes match staged files. Actual deployed sampling of45497 produced3,972 characters with7 explicit excerpt boundaries. Rooms/products APIs returned200 in0.02s each after activation.

No new video was rendered or fully played during this audit. Old generated assets remain unchanged. No improvement in conversion/retention has been measured.

## Required next integration, in order

1. Retrieve names from ALL original timestamped cues against room-specific catalogue title-derived names and user-confirmed aliases. Preserve raw ASR, title IDs and ambiguity; reject generic names. Use tone-insensitive candidates only to select small audio spans for neutral re-transcription/review, never as automatic corrections or SKU proof. Do not inject the full catalogue into ASR prompts.
2. Through AID on203, correlate these spans with continuous wearing/removal sequences and colour/bangs/length/curl evidence. Distinguish future/comparison/customer requests from current-product declarations. Whole-recording naming cannot solve multi-product source files.
3. Store stable per-source intervals with name candidates, quote/time, visual state and unresolved gaps. Pass an explicit target interval/identity into every variant and hook. Only merge intervals with supported same-product evidence; appearance alone is insufficient.
4. Separate candidate cart retrieval from confirmed identity, and from actual successful platform attachment. Keep all user-selected same-product links eligible for attempts, preserving the existing at-least-one-success rule; don't treat unrelated links from the entire broadcast as the same product.
5. Within verified intervals: show tangible result at0–3s, explain the benefit by5s, show hairline/parting or movement proof by10s, address a real purchase question at15–30s, end with truthful action guidance. Preserve complete original-audio sentences; cut visuals only where audio remains coherent. No invented price, material or performance promises.
6. Validate an independent sample end to end (audio, subtitles, cuts, product identity), then compare measured3/5/10s retention and conversion across alternative openings before expanding regeneration.

AID203's base render profile still requires a verified caption-capable extension for scheduler-based rerenders. This audit did not upgrade222 or bypass the scheduler.
