"""Hash-checked, staged release/rollback. Does not restart any service.

Use a release directory OUTSIDE the backend. Prepare preserves exact old bytes;
apply refuses drift; rollback refuses to overwrite later edits.
"""
import argparse
import hashlib
import json
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


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


def prepare(backend, release, module):
    backend, release, module = Path(backend).resolve(), Path(release).resolve(), Path(module).resolve()
    if release == backend or backend in release.parents:
        raise ValueError("Release must be outside backend")
    before = (backend / "qianchuan_matcher.py").read_bytes()
    after = patch_matcher(before)
    identity = module.read_bytes()
    compile(identity.decode("utf-8-sig"), "wig_identity.py", "exec")
    if (backend / "wig_identity.py").exists():
        raise ValueError("Existing identity module requires a separate reviewed upgrade")
    release.mkdir(parents=True, exist_ok=False)
    (release / "before").mkdir()
    (release / "after").mkdir()
    (release / "before/qianchuan_matcher.py").write_bytes(before)
    (release / "after/qianchuan_matcher.py").write_bytes(after)
    (release / "after/wig_identity.py").write_bytes(identity)
    manifest = {"backend": str(backend), "policy_version": "wig-identity-v1",
                "before": {"qianchuan_matcher.py": digest(before), "wig_identity.py": None},
                "after": {"qianchuan_matcher.py": digest(after), "wig_identity.py": digest(identity)}}
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
    names = ["qianchuan_matcher.py", "wig_identity.py"] if rollback else ["wig_identity.py", "qianchuan_matcher.py"]
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
    args = parser.parse_args()
    if args.action == "prepare":
        if not args.backend or not args.module:
            parser.error("prepare requires --backend and --module")
        prepare(args.backend, args.release, args.module)
    else:
        transition(args.release, rollback=args.action == "rollback")
    print(json.dumps({"action": args.action, "ok": True, "service_restarted": False}))
