"""Catalogue-derived hairstyle names and time-local spoken identity evidence."""
import re

NO_CURRENT = re.compile(r'过了吗|已过|讲过|介绍过|以后|下[一个款次]|待会|等会|有没有|什么时候|像不像|相比|对比|不是|别拍|换成')
CURRENT = re.compile(r'这[个款顶]?(?:就?是|叫|名字是)|现在[戴带]|正在[戴带]|给你们[戴带]的|我[戴带]的')
MODIFIERS = r'福利款|升级版|升级款|新款推荐|精修版|精修|发型师|手工|新工艺|仿递针工艺|仿递针|免发网假发|免发网|假发'


def hairstyle_name(title):
    title = re.sub(r'^(?:小圆圆不圆|小圆|kuku公主|kuku|lucylee)\s*[.·：:\-]?\s*', '', title or '', flags=re.I)
    # Brackets containing a distinctive name (e.g. "免发网仿递针假发-布蕾兔")
    # take precedence over generic prose outside them.
    for block in re.findall(r'【([^】]+)】', title):
        parts = re.split(r'[-·：:]', block)
        named = [p.strip() for p in parts if p.strip() and not re.fullmatch(MODIFIERS, p.strip())]
        if len(parts) > 1 and named:
            candidate = named[-1]
            if not re.search(r'工艺|头套|发网|假发|精修', candidate):
                return candidate
    title = re.sub(r'【[^】]*】|\[[^\]]*\]', '', title)
    for part in re.split(r'[·\s：:]', title):
        part = re.sub(MODIFIERS, '', part).strip('-.·')
        if not part:
            continue
        # Specification prose starts after the distinctive spoken name.
        part = re.split(r'混进口丝|进口丝|全头套|齐刘海|中长发|长卷发|长直发|短卷发|短直发', part)[0]
        if part and not re.search(r'颜色|自然日常|高质量', part):
            return part
    return ''


def mention_evidence(text, name):
    aliases = [p for p in re.split(r'[&＆/、]', name or '') if len(p) >= 2]
    hits = [a for a in aliases if a in text]
    if not hits:
        return {'current': False, 'reason': 'absent', 'aliases': []}
    # Evaluate the cue around the actual name, not a different clause.
    local = []
    for alias in hits:
        for m in re.finditer(re.escape(alias), text):
            local.append(text[max(0, m.start()-14):m.end()+12])
    if any(NO_CURRENT.search(t) for t in local):
        return {'current': False, 'reason': 'historical_future_comparison_or_question', 'aliases': hits}
    return {'current': any(CURRENT.search(t) for t in local),
            'reason': 'current_assertion' if any(CURRENT.search(t) for t in local) else 'mention_only', 'aliases': hits}


def resolution_policy(width, height, rotation=0):
    if not width or not height:
        return {'usable': False, 'action': 'review', 'reason': 'probe_failed'}
    # 1080p includes 1920x1080 landscape and 1080x1920 portrait.
    usable = min(width, height) >= 1080 and max(width, height) >= 1920
    return {'usable': usable, 'action': 'keep' if usable else 'quarantine',
            'reason': '1080p_or_higher' if usable else 'below_1080p'}
