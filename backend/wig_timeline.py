"""Timestamped transcript evidence, never visual/SKU approval or a render plan."""
import hashlib
import json
import re
import unicodedata

VERSION = "wig-transcript-timeline-v1"
_TIME = re.compile(r"^(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{3})$")
_SWITCH = re.compile(r"换(?:上|成|回).{0,8}(?:款|顶|假发|发型)|换(?:一|另)?(?:个|款|顶)|下一(?:款|顶)|下一个(?:款|发型|假发)|接下来.{0,6}(?:款|顶)|(?:摘下|摘掉|取下来).{0,4}(?:假发|头套)|戴上另一|刚才那(?:款|顶)")
_REFERENCE = re.compile(r"(?<![零〇一二两三四五六七八九十\d])([零〇一二两三四五六七八九十\d]{1,3})号(链接|颜色|色|款)?")
_GENERIC = {"假发", "卷发", "直发", "长发", "短发", "长卷发", "短卷发", "长直发", "短直发",
            "大波浪", "波波头", "自然黑", "黑色", "棕色", "长款", "短款", "免发网", "新款", "同款"}
_TRADITIONAL = str.maketrans({"賣":"卖", "換":"换", "頂":"顶", "號":"号", "鏈":"链", "顏":"颜",
                            "個":"个", "這":"这", "來":"来", "發":"发", "髮":"发", "別":"别",
                            "剛":"刚", "後":"后", "氣":"气", "長":"长", "捲":"卷", "藍":"蓝"})


def normalize(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")).casefold().translate(_TRADITIONAL))


def possible_switch(text):
    # Common actual transcript negatives: packaging/angle changes are not wigs.
    for phrase in ("换个角度", "换一个角度", "换个话题", "换个说法", "换一种说法"):
        text = text.replace(phrase, "")
    return bool(_SWITCH.search(text))


def spoken_references(text):
    types = {"链接": "link", "款": "style", "色": "color", "颜色": "color", "": "unspecified"}
    return [{"spoken": match.group(0), "number_text": match.group(1),
             "number": reference_number(match.group(1)),
             "type": types[match.group(2) or ""], "resolved_product_key": None}
            for match in _REFERENCE.finditer(text)]


def reference_number(text):
    if text.isdecimal():
        return int(text)
    digits = dict(zip("零〇一二两三四五六七八九", [0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
    if "十" in text:
        if text.count("十") != 1:
            return None
        head, tail = text.split("十")
        if len(head) > 1 or len(tail) > 1:
            return None
        return (digits.get(head, 1) if head else 1) * 10 + (digits.get(tail, 0) if tail else 0)
    return int("".join(str(digits[c]) for c in text))


def milliseconds(value):
    match = _TIME.fullmatch(value.strip())
    if not match:
        raise ValueError("Invalid SRT timestamp")
    h, m, s, ms = map(int, match.groups())
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def parse_srt(source):
    """Keep every cue; malformed/overlapping timing never silently passes."""
    cues, errors, max_end = [], [], 0
    blocks = re.split(r"\n[ \t]*\n", source.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip())
    for number, block in enumerate(blocks, 1):
        lines = block.splitlines()
        if not block.strip():
            continue
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        try:
            timing = re.split(r"\s*-->\s*", lines[0])
            if len(timing) != 2:
                raise ValueError("Missing time range")
            start, end = milliseconds(timing[0]), milliseconds(timing[1])
            text = " ".join(line.strip() for line in lines[1:]).strip()
            if end <= start or not text:
                raise ValueError("Empty/reversed cue")
        except (ValueError, IndexError):
            errors.append({"cue": number, "code": "invalid_cue"})
            continue
        overlap = bool(cues and start < max_end)
        if overlap:
            cues[-1]["timing_ambiguous"] = True
            errors.append({"cue": number, "code": "overlapping_or_unsorted_timing"})
        cues.append({"cue": number, "start_ms": start, "end_ms": end, "text": text,
                     "timing_ambiguous": overlap})
        max_end = max(max_end, end)
    return cues, errors


def alias_index(products):
    """Colliding aliases stay ambiguous; generic style terms cannot identify SKU."""
    index, rejected = {}, []
    for product in products:
        key = str(product.get("key") or "").strip()
        aliases = product.get("aliases") or []
        if not key or not isinstance(aliases, list):
            raise ValueError("Each product requires a stable key and an aliases list")
        for raw in aliases:
            alias = normalize(raw)
            if len(alias) < 2 or alias in _GENERIC:
                rejected.append({"key": key, "alias": str(raw), "code": "generic_or_short_alias"})
            else:
                index.setdefault(alias, set()).add(key)
    return index, rejected


def analyze_timeline(source, products, recording_id=None, target_key=None):
    cues, errors = parse_srt(source)
    index, rejected = alias_index(products)
    keys = {str(p.get("key")) for p in products}
    if target_key is not None and target_key not in keys:
        raise ValueError("Target key is not in the catalog")
    segments, counts, reference_count, link_changes, last_link = [], {}, 0, [], None
    for cue in cues:
        text = normalize(cue["text"])
        aliases = [alias for alias in index if alias in text]
        matches = sorted({key for alias in aliases for key in index[alias]})
        ambiguous_alias = any(len(index[alias]) > 1 for alias in aliases)
        switch = possible_switch(text)
        references = spoken_references(text)
        reference_count += len(references)
        links = sorted({r["number"] for r in references if r["type"] == "link" and r["number"] is not None})
        if len(links) > 1:
            last_link = None
        elif links:
            if last_link and last_link[0] != links[0]:
                link_changes.append({"cue": cue["cue"], "start_ms": cue["start_ms"],
                                     "previous_link_number": last_link[0], "link_number": links[0],
                                     "previous_mention_end_ms": last_link[1],
                                     "evidence_type": "spoken_link_reference_change",
                                     "product_key": None, "requires_visual_review": True})
            last_link = (links[0], cue["end_ms"])
        foreign = [key for key in matches if target_key is not None and key != target_key]
        if cue["timing_ambiguous"]:
            state = "ambiguous_timing"
        elif switch and re.search(r"卖完.{0,5}下一款|下次.{0,5}换|以后.{0,5}换", text):
            state = "future_switch_discussion"
        elif switch:
            state = "possible_product_switch"
        elif ambiguous_alias:
            state = "ambiguous_alias"
        elif len(matches) > 1:
            state = "multiple_product_mentions"
        elif foreign:
            state = "other_product_mentioned"
        elif len(matches) == 1:
            state = "single_product_text_evidence"
        else:
            state = "unassigned"
        counts[state] = counts.get(state, 0) + 1
        segments.append({**cue, "state": state, "product_keys": matches, "matched_aliases": sorted(aliases),
                         "target_key": target_key, "foreign_product_keys": foreign,
                         "spoken_references": references,
                         "approval": "review_required", "visual_verified": False,
                         "eligible_for_render": False})
    return {"version": VERSION, "recording_id": recording_id,
            "normalization": "nfkc_casefold_common_wig_traditional_map_v1",
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "catalog_sha256": hashlib.sha256(json.dumps(products, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "cue_count": len(cues), "counts": counts, "parse_errors": errors,
            "unresolved_spoken_reference_count": reference_count,
            "link_reference_changes": link_changes,
            "rejected_aliases": rejected, "segments": segments,
            "read_only": True, "visual_verified": False, "sku_verified": False,
            "eligible_for_render": False, "requires_visual_review": True,
            "scope": "explicit_transcript_mentions_only_no_identity_carry_across_unassigned_cues"}
