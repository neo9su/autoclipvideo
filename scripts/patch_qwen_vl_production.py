"""Reversible production wiring for the Qwen-VL wig identity service."""
from __future__ import annotations

import argparse, hashlib, json, py_compile, shutil
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"unexpected {label} anchor count: {text.count(old)}")
    return text.replace(old, new, 1)


def stage(root: Path, release: Path, sources: Path) -> dict:
    backend = root / "backend"
    targets = [
        backend / "qianchuan_matcher.py", backend / "start_windows_backend.ps1",
        backend / "wig_visual_identity.py",
        Path(r"C:\douyin_login\qwen_vl_wig\qwen_vl_wig_service.py"),
        Path(r"C:\douyin_login\qwen_vl_wig\start_qwen_vl_wig_service.ps1"),
    ]
    before, after = release / "before", release / "after"
    before.mkdir(parents=True, exist_ok=False); after.mkdir(parents=True)
    manifest = {"files": {}}
    for target in targets:
        entry = {"exists": target.exists()}
        if target.exists():
            backup = before / target.name
            shutil.copy2(target, backup)
            entry.update(sha256=digest(target), backup=str(backup))
        manifest["files"][str(target)] = entry

    matcher = (backend / "qianchuan_matcher.py").read_text(encoding="utf-8-sig")
    matcher = replace_once(matcher, "import json\n", "import asyncio\nimport json\n", "asyncio import")
    matcher = replace_once(
        matcher, "        from media_contract import resolve_srt_file\n",
        "        from media_contract import resolve_media_file, resolve_srt_file\n", "media import")
    matcher = replace_once(
        matcher, "        from wig_preprocess import filter_entries_to_windows, select_identity_windows\n",
        "        from wig_preprocess import filter_entries_to_windows, select_identity_windows\n"
        "        from wig_visual_identity import VisualIdentityUnavailable, verify_windows\n", "visual import")
    matcher = replace_once(
        matcher,
        "                windows = select_identity_windows(boundaries, target_name, target_color)\n"
        "                window_cache[cache_key] = windows\n",
        "                windows = select_identity_windows(boundaries, target_name, target_color)\n"
        "                media_path = resolve_media_file(recording.get(\"source_filename\") or recording.get(\"filename\"))\n"
        "                if windows and media_path:\n"
        "                    try:\n"
        "                        windows = await asyncio.to_thread(verify_windows, media_path, windows, target_name, target_color)\n"
        "                    except VisualIdentityUnavailable as exc:\n"
        "                        logger.warning(\"Visual identity unavailable for %s: %s\", media_path, exc)\n"
        "                        windows = []\n"
        "                window_cache[cache_key] = windows\n",
        "visual verification",
    )
    (after / "qianchuan_matcher.py").write_text(matcher, encoding="utf-8")

    starter = (backend / "start_windows_backend.ps1").read_text(encoding="utf-8-sig")
    starter = replace_once(
        starter, '$env:TRANSFORMERS_OFFLINE = "1"\n',
        '$env:TRANSFORMERS_OFFLINE = "1"\n        $env:WIG_VISUAL_IDENTITY_URL = "http://127.0.0.1:8897"\n',
        "backend visual URL",
    )
    (after / "start_windows_backend.ps1").write_text(starter, encoding="utf-8")
    shutil.copy2(sources / "wig_visual_identity.py", after / "wig_visual_identity.py")
    shutil.copy2(sources / "qwen_vl_wig_service.py", after / "qwen_vl_wig_service.py")
    shutil.copy2(sources / "start_qwen_vl_wig_service.ps1", after / "start_qwen_vl_wig_service.ps1")
    for path in (after / "qianchuan_matcher.py", after / "wig_visual_identity.py", after / "qwen_vl_wig_service.py"):
        py_compile.compile(str(path), doraise=True)
    staged = {str(target): str(after / target.name) for target in targets}
    manifest["after"] = {target: digest(Path(path)) for target, path in staged.items()}
    (release / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def transition(root: Path, release: Path, rollback: bool) -> dict:
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    for raw, before in manifest["files"].items():
        target = Path(raw)
        expected = manifest["after"][raw] if rollback else before.get("sha256")
        if target.exists() and expected and digest(target) != expected:
            raise RuntimeError(f"source drift: {target}")
        if not rollback and target.exists() != before["exists"]:
            raise RuntimeError(f"existence drift: {target}")
    for raw, before in manifest["files"].items():
        target = Path(raw)
        if rollback and not before["exists"]:
            target.unlink(missing_ok=True); continue
        source = Path(before["backup"]) if rollback else release / "after" / target.name
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
    return {"mode": "rollback" if rollback else "apply", "changed": list(manifest["files"])}


if __name__ == "__main__":
    p = argparse.ArgumentParser(); p.add_argument("mode", choices=("stage", "apply", "rollback"))
    p.add_argument("--root", required=True, type=Path); p.add_argument("--release", required=True, type=Path)
    p.add_argument("--sources", type=Path); a = p.parse_args()
    if a.mode == "stage":
        if not a.sources: p.error("--sources required")
        result = stage(a.root, a.release, a.sources)
    else: result = transition(a.root, a.release, a.mode == "rollback")
    print(json.dumps(result, ensure_ascii=False))
