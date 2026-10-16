"""Hash-checked, staged release/rollback. Does not restart any service.

Use a release directory OUTSIDE the backend. Prepare preserves exact old bytes;
apply refuses drift; rollback refuses to overwrite later edits.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _encode_like(text, original):
    newline = "\r\n" if b"\r\n" in original else "\n"
    return (b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b"") + text.replace("\n", newline).encode()


def _insert_before(text, function, marker, addition, optional=False):
    # AST is only a structural locator; compile() validates the resulting source.
    nodes = [n for n in ast.parse(text).body if isinstance(n, ast.AsyncFunctionDef) and n.name == function]
    if not nodes and optional:
        return text
    if len(nodes) != 1:
        raise ValueError(f"Unknown function layout: {function}")
    lines = text.splitlines(keepends=True)
    node = nodes[0]
    body = "".join(lines[node.lineno - 1:node.end_lineno])
    if body.count(marker) != 1:
        raise ValueError(f"Ambiguous insertion anchor in {function}")
    body = body.replace(marker, addition + marker, 1)
    return "".join(lines[:node.lineno - 1]) + body + "".join(lines[node.end_lineno:])


def patch_review_api(data):
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    if "wig_identity_review" in text:
        raise ValueError("Review patch already present")
    marker = 'qianchuan_router = APIRouter(prefix="/api/v2/qianchuan", tags=["qianchuan"])\n'
    if text.count(marker) != 1:
        raise ValueError("Unknown Qianchuan router layout")
    text = text.replace(marker, marker + 'from wig_identity_routes import identity_router\n'
                        'from wig_identity_review import REVIEW_REQUIRED, hold_for_review, review_message\n'
                        'qianchuan_router.include_router(identity_router)\n', 1)
    manual = '''    from db import aio_connect
    async with aio_connect() as identity_db:
        if await hold_for_review(identity_db, request.group_id, context.get("identity")):
            return QianchuanGenerateResponse(
                success=False, group_id=request.group_id, status=REVIEW_REQUIRED,
                score=0.0, review={"identity": context.get("identity")},
                error=review_message(context.get("identity")),
            )
'''
    text = _insert_before(text, 'generate_qianchuan', '    match = score_product_match(', manual)
    for name, version in [('_run_qianchuan_pipeline', 'qianchuan'), ('_run_qianchuan_v2', 'qianchuan_v2')]:
        guard = f'''        from db import aio_connect
        async with aio_connect() as identity_db:
            if await hold_for_review(identity_db, group_id, context.get("identity"), {version!r}):
                return
'''
        text = _insert_before(text, name, '        group = context["group"]', guard, optional=name.endswith('_v2'))
    for name, version in [('_qianchuan_generate_bg', 'qianchuan'), ('_qianchuan_v2_bg', 'qianchuan_v2')]:
        guard = f'''            identity_context = await load_group_context(DB_PATH, group_id)
            from db import aio_connect
            async with aio_connect() as identity_db:
                if await hold_for_review(identity_db, group_id, identity_context.get("identity"), {version!r}):
                    return
'''
        text = _insert_before(text, name, '            voice_result = await voice_director.generate_voiceover(', guard, optional=name.endswith('_v2_bg'))
    compile(text, 'api_v2.py', 'exec')
    return _encode_like(text, data)


def patch_review_health(data):
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    old = '(-4, "probe_fail")]'
    if text.count(old) != 1:
        raise ValueError("Unknown health status mapping")
    text = text.replace(old, '(-4, "probe_fail"), (-5, "review_required")]', 1)
    compile(text, 'main.py', 'exec')
    return _encode_like(text, data)


def patch_matcher(data):
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    if "load_identity_evidence" in text:
        raise ValueError("Identity patch already present; choose a new release")
    changes = [
        ('        if not group:\n            return {}\n',
         '        if not group:\n            return {}\n\n'
         '        from wig_identity import load_identity_evidence\n'
         '        identity = await load_identity_evidence(db, group)\n'),
        ('        "group": group_dict,\n', '        "group": group_dict,\n        "identity": identity,\n'),
        ('    best["ok"] = best["score"] >= threshold\n',
         '    best["ok"] = best["score"] >= threshold\n    best["identity"] = identity\n'),
    ]
    for old, new in changes:
        if text.count(old) != 1:
            raise ValueError("Live matcher differs from known anchors; manual review required")
        text = text.replace(old, new, 1)
    start = text.index("def score_product_match(")
    marker = '    group = context.get("group") or {}\n'
    pos = text.index(marker, start)
    guard = '''    # Hard gate: semantic scores cannot override mixed or unknown identity.
    identity = context.get("identity")
    if not identity or not identity.get("ok"):
        return {"ok": False, "score": 0.0, "product": None, "hits": [], "missing": [],
                "threshold": threshold, "identity": identity,
                "reason": "款式一致性待审核：录像款式、颜色或商品证据缺失/冲突，禁止自动混剪"}
'''
    text = text[:pos] + guard + text[pos:]
    compile(text, "qianchuan_matcher.py", "exec")
    newline = "\r\n" if b"\r\n" in data else "\n"
    return (b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b"") + text.replace("\n", newline).encode()


def prepare(backend, release, module, review_sources=None):
    backend, release, module = Path(backend).resolve(), Path(release).resolve(), Path(module).resolve()
    if release == backend or backend in release.parents:
        raise ValueError("Release must be outside backend")
    before = (backend / "qianchuan_matcher.py").read_bytes()
    after = patch_matcher(before)
    identity = module.read_bytes()
    compile(identity.decode("utf-8-sig"), "wig_identity.py", "exec")
    if (backend / "wig_identity.py").exists():
        raise ValueError("Existing identity module requires a separate reviewed upgrade")
    originals = {"qianchuan_matcher.py": before, "wig_identity.py": None}
    payloads = {"qianchuan_matcher.py": after, "wig_identity.py": identity}
    if review_sources:
        for name, patch in [('api_v2.py', patch_review_api), ('main.py', patch_review_health)]:
            originals[name] = (backend / name).read_bytes()
            payloads[name] = patch(originals[name])
        for name in ['wig_identity_review.py', 'wig_identity_routes.py']:
            if (backend / name).exists():
                raise ValueError(f"Existing review module requires a reviewed upgrade: {name}")
            originals[name] = None
            payloads[name] = (Path(review_sources) / name).read_bytes()
            compile(payloads[name].decode('utf-8-sig'), name, 'exec')
    release.mkdir(parents=True, exist_ok=False)
    (release / "before").mkdir()
    (release / "after").mkdir()
    for name, data in originals.items():
        if data is not None:
            (release / "before" / name).write_bytes(data)
    for name, data in payloads.items():
        (release / "after" / name).write_bytes(data)
    manifest = {"backend": str(backend), "policy_version": "wig-identity-review-v2" if review_sources else "wig-identity-v1",
                "before": {name: digest(data) if data is not None else None for name, data in originals.items()},
                "after": {name: digest(data) for name, data in payloads.items()}}
    (release / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def transition(release, rollback=False):
    release = Path(release).resolve()
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    backend = Path(manifest["backend"])
    expected, target = ("after", "before") if rollback else ("before", "after")
    # Validate ALL current and backup bytes before the first mutation.
    for name, sha in manifest[expected].items():
        p = backend / name
        actual = digest(p.read_bytes()) if p.exists() else None
        if actual != sha:
            raise ValueError(f"Refusing to overwrite changed file: {name}")
    for name, sha in manifest[target].items():
        if sha is not None and digest((release / target / name).read_bytes()) != sha:
            raise ValueError(f"Release backup checksum failed: {name}")
    # These two replacements require a maintenance window: do not hot-apply to
    # running workers. An OS failure between replacements needs manual recovery
    # from before/; this is not a transactional multi-file deploy.
    existing = [name for name, sha in manifest['before'].items() if sha is not None]
    introduced = [name for name, sha in manifest['before'].items() if sha is None]
    names = existing + introduced if rollback else introduced + existing
    for name in names:
        p = backend / name
        if manifest[target][name] is None:
            p.unlink()
        else:
            temp = p.with_name(p.name + ".identity-tmp")
            with temp.open("xb") as stream:
                stream.write((release / target / name).read_bytes())
            temp.replace(p)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "apply", "rollback"])
    parser.add_argument("--release", required=True)
    parser.add_argument("--backend")
    parser.add_argument("--module")
    parser.add_argument("--review-sources", help="Directory containing the two review modules")
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.backend or not args.module:
            parser.error("prepare requires --backend and --module")
        prepare(args.backend, args.release, args.module, args.review_sources)
    else:
        transition(args.release, rollback=args.action == "rollback")
    print(json.dumps({"action": args.action, "ok": True, "service_restarted": False}))
