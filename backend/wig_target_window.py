"""Target-aware source-window selection. Text evidence is not visual/SKU approval."""
import math
import re
from wig_transcript_evidence import plain, corroborate_quote

GENERIC={'','null','none','未知款','未分类','直发','卷发','长直发','长卷发','刘海假发','大波浪卷发','中分卷发','高马尾','假发','大波浪'}


def names(value):
    # Only explicitly established spelling alias; no arbitrary fuzzy identity.
    value=str(value or '').replace('氧气粒子','氧气栗子')
    return {plain(p) for p in re.split(r'[&＆]',value) if plain(p) not in GENERIC and len(plain(p))>=2}


def validate_target(target):
    requested=str(target.get('product_keywords') or target.get('wig_model') or '')
    if any(s in requested for s in [',','，','/','、',';','；']):
        raise ValueError('目标款名包含多个候选，需先确认当前款式')
    wanted=names(requested)
    if not wanted:raise ValueError('缺少明确目标款名，外观描述不足以确认当前款式')
    wanted_color=plain(target.get('wig_color')).removesuffix('色')
    if any(s in str(target.get('wig_color') or '') for s in ['/','、',',','或']):
        raise ValueError('目标颜色存在多个候选，需先确认颜色')
    return wanted,wanted_color


def choose(boundaries,target,cues,min_duration=45):
    wanted,wanted_color=validate_target(target)
    candidates=[]
    for b in boundaries:
        start,end=b.get('start_sec'),b.get('end_sec')
        if any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) for t in (start,end)):continue
        if start<0 or end-start<min_duration or not cues or end>max(c['end_sec'] for c in cues)+1:continue
        if not names(b.get('wig')) & wanted:continue
        color=plain(b.get('color')).removesuffix('色')
        if wanted_color and color!=wanted_color:continue
        evidence=corroborate_quote(cues,b.get('current_evidence'),b.get('wig'),start,end)
        if not evidence['verified']:continue
        # Reject explicit conflicting overlapping windows, rather than selecting
        # the longest of contradictory model proposals.
        conflict=False
        for other in boundaries:
            try:
                overlaps=float(other['start_sec'])<end and float(other['end_sec'])>start
            except (KeyError,TypeError,ValueError):continue
            if other is not b and overlaps and names(other.get('wig')) and not (names(other.get('wig')) & wanted):conflict=True
        if not conflict:candidates.append(b)
    if not candidates:raise ValueError('没有找到目标款名、颜色及原始口播证据一致的45秒区间，需复核；未改选其他款')
    if not wanted_color and len({plain(b.get('color')) for b in candidates})>1:
        raise ValueError('同名区间存在不同颜色，需确认目标颜色')
    return max(candidates,key=lambda b:(b.get('complete') is True,b['end_sec']-b['start_sec']))
