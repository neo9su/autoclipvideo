"""Catalogue-derived hairstyle names and time-local spoken identity evidence."""
import re

NO_CURRENT = re.compile(r'过了吗|已过|讲过|介绍过|以后|下[一个款次]|待会|等会|有没有|什么时候|像不像|相比|对比|不是|别拍|换成')
CURRENT = re.compile(r'这[个款顶]?(?:就?是|叫|名字是)|现在[戴带]|正在[戴带]|给你们[戴带]的|我[戴带]的')
MODIFIERS = r'福利款|升级版|升级款|新款推荐|精修版|精修|发型师|手工|新工艺|仿递针工艺|仿递针|免发网假发|免发网|假发'


def hairstyle_name(title):
    title = re.sub(r'^(?:小圆圆不圆|小圆|kuku公主|kuku|lucylee)(?:假发)?\s*[.·：:\-]?\s*', '', title or '', flags=re.I)

    def candidate(text):
        for part in re.split(r'[-·•\s：:]', text):
            part = re.sub(MODIFIERS, '', part).strip('-.·')
            # A specification is not a name, even if removing modifiers leaves
            # a short fragment such as “全” or “套”.
            if len(part) < 2 or re.search(
                r'工艺|头套|发网|假发|进口丝|蕾丝|刘海|长发|短发|卷发|直发|'
                r'大波浪|画染|弹力网|日常|自然|高质量|颜色|推荐|升级|福利', part
            ):
                continue
            return part
        return ''

    # Preserve the prefix boundary: removing brackets and joining the suffix
    # can turn “夺回&人生” into “夺回&人生日常大波浪套”.
    prefix = re.split(r'[【\[]', title, maxsplit=1)[0]
    name = candidate(prefix)
    if name:
        return name
    for block in re.findall(r'【([^】]+)】|\[([^\]]+)\]', title):
        name = candidate(next(part for part in block if part))
        if name:
            return name
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
