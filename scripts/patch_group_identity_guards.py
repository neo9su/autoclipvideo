"""Minimal guards against unsupported group reuse and discontinuous fallback."""
import ast
from patch_identity_quality import replace_node


def reusable_product_names(existing, incoming):
    """Name equality is only a reuse prerequisite, never SKU verification."""
    import re
    generic={'卷发','直发','长发','短发','长卷发','长直发','大波浪','大波浪卷发','假发','刘海','刘海假发','null','none','未知款','未分类'}
    def names(values):
        result=set()
        for value in values:
            value=str(value or '').strip().casefold()
            if not value or value in generic or re.fullmatch(r'(?:自然)?(?:黑|棕|灰|红|金|浅棕|深棕)(?:色)?',value):
                continue
            result.add(value)
        return result
    a=names(str(existing or '').split(','));b=names(incoming or [])
    # Multiple named products in one recording cannot establish one identity.
    return len(a)==1 and a==b


def patch_analyzer(source):
    import inspect
    source=source.replace('\r\n','\n')
    n=next(n for n in ast.parse(source).body if getattr(n,'name',None)=='_get_or_create_group')
    part=ast.get_source_segment(source,n)
    old='        if row:\n            return await _merge_group_products(db, row, prod, prod_kw)'
    new='        if row and _reusable_product_names(row["product_keywords"], prod):\n            return await _merge_group_products(db, row, prod, prod_kw)'
    if part.count(old)!=1:raise ValueError('Exact group reuse changed')
    part=part.replace(old,new,1)
    old='        for r in rows:\n'
    if part.count(old)!=1:raise ValueError('Fuzzy group reuse changed')
    part=part.replace(old,old+'            if not _reusable_product_names(r["product_keywords"], prod):\n                continue\n',1)
    result=replace_node(source,'_get_or_create_group',part)
    if 'def _reusable_product_names(' in result:raise ValueError('Already patched')
    result+='\n\n'+inspect.getsource(reusable_product_names).replace('def reusable_product_names(', 'def _reusable_product_names(',1)
    compile(result,'group-guard','exec');return result


def patch_editor(source):
    source=source.replace('\r\n','\n')
    n=next(n for n in ast.parse(source).body if getattr(n,'name',None)=='_select_realistic_window')
    part=ast.get_source_segment(source,n)
    old='        chosen = candidates[:REALISTIC_MAX_SEGMENTS]'
    new='''        chosen = []
        for candidate in candidates[:REALISTIC_MAX_SEGMENTS]:
            if chosen and candidate.start - chosen[-1].end > 6.0:
                break
            if chosen and sum(s.duration for s in chosen) + candidate.duration > target_max:
                break
            chosen.append(candidate)'''
    if part.count(old)!=1:raise ValueError('Fallback selection changed')
    return replace_node(source,'_select_realistic_window',part.replace(old,new,1))
