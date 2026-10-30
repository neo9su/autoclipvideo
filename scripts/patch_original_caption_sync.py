"""Minimal production compatibility patch: original-audio variants keep raw cues.

Does not change selection, compliance/audio policy, style profiles or GPU routing.
"""
import ast


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Caption patch source drift: ' + before[:90])
    return text.replace(before, after, 1)


def patch(source):
    source = source.replace('\r\n', '\n')
    tree = ast.parse(source)
    edits = []
    for name in ('edit_recording', 'edit_recording_multi'):
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        text = ast.get_source_segment(source, node)
        text = replace_once(text, '    segs = parse_srt(srt_path)',
                            '    source_segs = parse_srt(srt_path)\n    segs = source_segs')
        room_arg = 'room_id' if name == 'edit_recording' else '_room_id_v'
        text = replace_once(text, f'mp4_filename, {room_arg}, selected, segs,',
                            f'mp4_filename, {room_arg}, selected,\n                    source_segs if clip_engine in ("realistic", "conservative") else segs,')
        edits.append((node, text))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_ass')
    text = ast.get_source_segment(source, node)
    text = replace_once(text, '        offset = cursor',
        '        # The incoming clip starts before the previous end for a fade.\n'
        '        overlap = _gpu_xfade_overlap(sel_seg) if sel_idx else 0.0\n'
        '        offset = max(0.0, cursor - overlap)')
    text = replace_once(text, '            raw_text = _truncate(srt.text)',
        '            if realistic:\n'
        '                # Keep original cue timestamps and every spoken word.\n'
        '                # Apply the existing textual sanitization, without re-timing audio.\n'
        '                import compliance as _caption_compliance\n'
        '                caption = _caption_compliance.sanitize_text(srt.text or "")\n'
        '                caption = " ".join(caption.split())\n'
        '                lines = [caption[i:i + MAX_SUB_CHARS] for i in range(0, len(caption), MAX_SUB_CHARS)]\n'
        '                raw_text = r"\\N".join(line.replace("\\\\", "\\\\\\\\").replace("{", "\\\\{").replace("}", "\\\\}") for line in lines)\n'
        '            else:\n'
        '                raw_text = _truncate(srt.text)')
    # Do not omit valid original cues because prior selection scenes overlapped.
    text = replace_once(text,
        '            if sum(a < t1_candidate and t0_candidate < b for a, b in rendered_intervals) >= 3:',
        '            if not realistic and sum(a < t1_candidate and t0_candidate < b for a, b in rendered_intervals) >= 3:')
    edits.append((node, text))
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_edit_via_gpu')
    text = ast.get_source_segment(source, node)
    text = replace_once(text,
        '"idempotency_key": f"clip:{room_id}:{mp4_filename}:{\'realistic\' if realistic else \'stylized\'}:{segment_fingerprint}",',
        '"idempotency_key": f"clip:{room_id}:{mp4_filename}:{\'realistic\' if realistic else \'stylized\'}:{segment_fingerprint}"\n'
        '        + (":captions-v2:" + _hashlib.sha256(ass_content.encode("utf-8")).hexdigest()[:16] if realistic else ""),')
    edits.append((node, text))
    lines = source.splitlines(keepends=True)
    for node, text in sorted(edits, key=lambda e: e[0].lineno, reverse=True):
        lines[node.lineno - 1:node.end_lineno] = [text + '\n']
    result = ''.join(lines)
    compile(result, '<caption-sync-patched-editor>', 'exec')
    return result
