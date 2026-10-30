"""Scoped target-routing changes against divergent production source."""
import ast
from patch_identity_quality import replace_node


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Source drift: '+old[:70])
    return text.replace(old,new,1)


def editor(source):
    source=source.replace('\r\n','\n')
    n=next(n for n in ast.parse(source).body if getattr(n,'name',None)=='edit_recording')
    part=ast.get_source_segment(source,n)
    part=once(part,'clip_engine: str = "legacy")','clip_engine: str = "legacy", target_identity: Optional[dict] = None)')
    old='            source_window = pick_best_window(boundaries, min_duration=45.0)'
    new='''            if target_identity is not None:
                from wig_target_window import choose
                from wig_transcript_evidence import parse_srt as parse_evidence_srt
                from pathlib import Path
                source_window = choose(boundaries, target_identity, parse_evidence_srt(Path(srt_path).read_text(encoding="utf-8-sig")))
            else:
                source_window = pick_best_window(boundaries, min_duration=45.0)'''
    part=once(part,old,new)
    part=once(part,'            logger.warning(f"[realistic] Boundary detection skipped: {error}")',
      '            if target_identity is not None:\n                raise ValueError(f"目标款式区间待复核：{error}") from error\n            logger.warning(f"[realistic] Boundary detection skipped: {error}")')
    return replace_node(source,'edit_recording',part)


def transcribe(source):
    source=source.replace('\r\n','\n')
    n=next(n for n in ast.parse(source).body if getattr(n,'name',None)=='_run_variant_pipeline');part=ast.get_source_segment(source,n)
    marker='            # ── Collect source material (already-clipped MP4s + SRT sidecars) ──'
    new='''            # Bind source selection to this group's explicit identity.
            async with aio_connect() as identity_db:
                async with identity_db.execute("SELECT wig_model,wig_color,product_keywords FROM clip_groups WHERE id=?", (group_id,)) as identity_cur:
                    identity_row = await identity_cur.fetchone()
            if not identity_row:
                return await _fail("目标分组不存在")
            target_identity = dict(zip(("wig_model", "wig_color", "product_keywords"), identity_row))
            from wig_target_window import validate_target
            try:
                validate_target(target_identity)
            except ValueError as error:
                return await _fail("目标款式待复核：" + str(error))

'''+marker
    part=once(part,marker,new)
    part=once(part,'                    clip_engine=version,','                    clip_engine=version,\n                    target_identity=target_identity,')
    part=once(part,'            out_path = None','            out_path = None\n            last_identity_error = ""')
    start=part.index('                candidate_out = await edit_recording(')
    end=part.index('                if candidate_out and os.path.exists(candidate_out):',start)
    block=part[start:end]
    wrapped='                try:\n'+''.join('    '+line if line.strip() else line for line in block.splitlines(keepends=True))
    wrapped+='                except ValueError as error:\n                    last_identity_error = str(error)\n                    logger.warning("Variant source identity review: %s", error)\n                    continue\n'
    part=part[:start]+wrapped+part[end:]
    part=once(part,'return await _fail(f"no {version} clip produced from {len(sources)} source(s)")','return await _fail(last_identity_error or f"no {version} clip produced from {len(sources)} source(s)")')
    return replace_node(source,'_run_variant_pipeline',part)


def boundary(source):
    source=source.replace('\r\n','\n')
    source=once(source,'- 出现新的发型名称（大波浪、齐刘海、卷发、直发等）标志新一款开始',
      '- 大波浪、齐刘海、卷发、直发属于外观，不是商品款名。wig填写主播明确介绍的名称，未知留空。\n'
      '- 必须用区间内的原始字幕逐字提供current_evidence，不能编造。下一款、有没有、对比、刚才提及不算当前款确认。\n'
      '- 每个区间只包含一款和一种颜色；摘戴和遮挡保留为不确定过渡，字幕不能证明画面一致。')
    source=once(source,'    "wig": "发型款式名称",','    "wig": "主播明确介绍的款名，未知留空",\n    "current_evidence": "该区间内明确介绍当前款名的字幕原话，未知留空",')
    compile(source,'boundary','exec');return source
