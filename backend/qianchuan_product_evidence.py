"""CPU-only catalogue evidence: group terms cannot score against themselves."""
import re
from wig_catalog_names import hairstyle_name, mention_evidence


def normal(value):
    return re.sub(r"[\s，。！？、；：,.!?;:/|·【】\[\]]+", "", str(value or "")).casefold()


def catalogue_aliases(product):
    # Keywords/specifications alone are not a product identity.
    name = hairstyle_name(product.get("product_name") or "")
    aliases = [a.strip() for a in re.split(r"[&＆/／、]", name) if len(a.strip()) >= 2]
    if "氧气栗子" in aliases or "氧气粒子" in aliases:
        aliases.extend(["氧气栗子", "氧气粒子"])
    return list(dict.fromkeys(aliases))


def product_evidence(context, product_id=None, threshold=0.58):
    group = context.get("group") or {}
    products = [p for p in context.get("products", []) if p.get("enabled", 1)]
    if product_id:
        products = [p for p in products if str(product_id) in {str(p.get("id")), str(p.get("product_id"))}]
    target = normal(group.get("wig_model") or group.get("label"))
    spoken = context.get("srt_text") or ""
    rows = []
    for product in products:
        aliases = catalogue_aliases(product)
        group_hits = [a for a in aliases if normal(a) in target]
        source_hits = [a for a in aliases if mention_evidence(spoken, a)["current"]]
        score = 0.72 if group_hits else 0.66 if source_hits else 0.0
        if group_hits and source_hits:
            score += 0.20
        # The caller's selected ID narrows candidates; it creates no evidence.
        rows.append(dict(product=product, score=round(score, 3), hits=list(dict.fromkeys(group_hits + source_hits)),
                         group_hits=group_hits, source_hits=source_hits, missing=[a for a in aliases if a not in group_hits + source_hits]))
    # Once a specific catalogue style is known from the group, mentions of
    # another style elsewhere in the long transcript cannot override it.
    group_candidates = [r for r in rows if r["group_hits"]]
    candidates = group_candidates or rows
    best = max(candidates, key=lambda r: r["score"], default=dict(product=None, score=0.0, hits=[], missing=[]))
    best = dict(best, threshold=threshold, ok=best["score"] >= threshold,
                evidence_type="catalogue_style_alias", candidates_checked=len(products))
    if best["score"] == 0:
        best["product"] = None
    if not best["ok"]:
        best["reason"] = "商品名称证据不足: 未找到商品款名与分组或当前口播的对应证据"
    return best


def load_transcripts(filenames, resolver):
    texts, audit = [], []
    for filename in filenames:
        item = {"filename": filename, "characters": 0}
        try:
            path = resolver(filename)
            if path is None:
                item["error"] = "subtitle_not_resolved"
            else:
                with open(path, encoding="utf-8-sig") as handle:
                    text = handle.read(2_000_001)
                item.update(path=str(path), characters=min(len(text), 2_000_000), truncated=len(text) > 2_000_000)
                texts.append(text[:2_000_000])
        except (OSError, UnicodeError) as exc:
            item["error"] = type(exc).__name__
        audit.append(item)
    return "\n".join(texts), audit
