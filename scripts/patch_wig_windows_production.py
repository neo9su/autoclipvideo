"""Stage, apply, or roll back the strict single-wig production patch."""
from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import shutil
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


METHOD = r'''
    async def _get_group_recordings(self, group_id: int) -> List[Dict]:
        """Constrain every candidate to transcript-approved windows for one wig."""
        recordings = await super()._get_group_recordings(group_id)
        if not recordings:
            return []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT wig_model, wig_color, label FROM clip_groups WHERE id=?", (group_id,)
            ) as cursor:
                group = await cursor.fetchone()
        if not group:
            return []
        target_name = group["wig_model"] or group["label"] or ""
        target_color = group["wig_color"] or ""
        from media_contract import resolve_srt_file
        from wig_boundary import detect_boundaries
        from wig_preprocess import filter_entries_to_windows, select_identity_windows

        constrained = []
        window_cache = getattr(self, "_wig_window_cache", None)
        if window_cache is None:
            window_cache = self._wig_window_cache = {}
        for recording in recordings:
            srt_path = resolve_srt_file(recording.get("source_filename") or recording.get("filename"))
            if not srt_path:
                continue
            cache_key = (
                recording.get("recording_id"), str(srt_path), srt_path.stat().st_mtime_ns,
                target_name, target_color,
            )
            windows = window_cache.get(cache_key)
            if windows is None:
                boundaries = await detect_boundaries(str(srt_path))
                windows = select_identity_windows(boundaries, target_name, target_color)
                window_cache[cache_key] = windows
            entries = filter_entries_to_windows(recording.get("srt_entries") or [], windows)
            if not entries:
                continue
            clone = dict(recording)
            clone["srt_entries"] = entries
            clone["transcript_text"] = " ".join(entry["text"] for entry in entries)
            clone["wig_windows"] = windows
            clone["filename"] = clone.get("source_filename") or clone.get("filename")
            clone["duration"] = max(float(entry["end"]) for entry in entries)
            constrained.append(clone)
        if not constrained:
            self.match_error = "no single-wig source window matched the requested product"
        return constrained

'''


def stage(root: Path, release: Path, wig_module: Path) -> dict:
    backend = root / "backend"
    targets = {
        backend / "qianchuan_matcher.py": release / "after" / "qianchuan_matcher.py",
        backend / "wig_preprocess.py": release / "after" / "wig_preprocess.py",
    }
    before_dir = release / "before"
    after_dir = release / "after"
    before_dir.mkdir(parents=True, exist_ok=False)
    after_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"files": {}}
    for target in targets:
        backup = before_dir / target.name
        shutil.copy2(target, backup)
        manifest["files"][str(target)] = {
            "sha256": digest(target), "backup": str(backup)
        }

    matcher = (backend / "qianchuan_matcher.py").read_text(encoding="utf-8-sig")
    anchor = 'class QianchuanMatcher(SemanticMatcher):\n    """Semantic matcher with Qianchuan shot-bias metadata."""\n\n'
    if matcher.count(anchor) != 1 or "async def _get_group_recordings(self, group_id" in matcher:
        raise RuntimeError("unexpected qianchuan matcher shape")
    (after_dir / "qianchuan_matcher.py").write_text(
        matcher.replace(anchor, anchor + METHOD, 1), encoding="utf-8"
    )
    shutil.copy2(wig_module, after_dir / "wig_preprocess.py")
    for staged in targets.values():
        py_compile.compile(str(staged), doraise=True)
    manifest["after"] = {str(target): digest(staged) for target, staged in targets.items()}
    (release / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def transition(root: Path, release: Path, rollback: bool) -> dict:
    backend = root / "backend"
    targets = [backend / "qianchuan_matcher.py", backend / "wig_preprocess.py"]
    manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
    for target in targets:
        expected = manifest["after" if rollback else "files"][str(target)]
        expected_hash = expected if rollback else expected["sha256"]
        if digest(target) != expected_hash:
            raise RuntimeError(f"source drift: {target}")
    for target in targets:
        source = Path(manifest["files"][str(target)]["backup"]) if rollback else release / "after" / target.name
        shutil.copy2(source, target)
    return {"mode": "rollback" if rollback else "apply", "changed": [str(p) for p in targets]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("stage", "apply", "rollback"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--wig-module", type=Path)
    args = parser.parse_args()
    if args.mode == "stage":
        if not args.wig_module:
            parser.error("--wig-module is required for stage")
        result = stage(args.root, args.release, args.wig_module)
    else:
        result = transition(args.root, args.release, args.mode == "rollback")
    print(json.dumps(result, ensure_ascii=False))
