"""Patch a deployed api_v2.py so restarts retain the originally pinned product."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


HELPER = '''

def _saved_qianchuan_resume(group: Dict) -> tuple[Optional[Dict], Optional[str]]:
    """Return a resumable script and its pinned, link-bearing catalogue row."""
    script = _loads_qianchuan_json(group.get("qianchuan_script"))
    if not isinstance(script, dict):
        return None, None
    product = script.get("product_context")
    if not isinstance(product, dict) or not str(product.get("product_url") or "").startswith(("http://", "https://")):
        return None, None
    identity = product.get("id") or product.get("product_id")
    return (script, str(identity)) if identity else (None, None)
'''


def patch(path: Path, backup_dir: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    before_sha = hashlib.sha256(source.encode()).hexdigest()
    if "def _saved_qianchuan_resume(" not in source:
        anchor = '        return {"raw": str(value)[:1000], "parse_error": True}\n'
        if source.count(anchor) != 1:
            raise RuntimeError("JSON loader anchor drifted")
        source = source.replace(anchor, anchor + HELPER, 1)

    start = source.index("async def _run_qianchuan_pipeline")
    end = source.index("async def _qianchuan_generate_bg", start)
    block = source[start:end]
    old = '''        context = await load_group_context(DB_PATH, group_id)
        if not context:
            raise RuntimeError("group not found")
        group = context["group"]
        match = score_product_match(context, keywords=[group.get("label"), group.get("wig_model"), group.get("wig_color"), hair_feature(group.get("wig_model") or "", group.get("wig_color") or "", group.get("label") or "")], threshold=0.0)
        script = generate_qianchuan_script(
            group, product_context=match.get("product") or {}, selling_points=[]
        )
        script["preview_mode"] = False
'''
    new = '''        context = await load_group_context(DB_PATH, group_id)
        if not context:
            raise RuntimeError("group not found")
        group = context["group"]
        script, pinned_product_id = _saved_qianchuan_resume(group)
        if pinned_product_id:
            context = await load_group_context(DB_PATH, group_id, pinned_product_id)
        match = score_product_match(
            context,
            product_id=pinned_product_id,
            keywords=[group.get("label"), group.get("wig_model"), group.get("wig_color"), hair_feature(group.get("wig_model") or "", group.get("wig_color") or "", group.get("label") or "")],
            threshold=0.58,
        )
        product_context = match.get("product")
        if not match.get("ok") or not product_context or not product_context.get("product_url"):
            raise RuntimeError(match.get("reason") or "商品链接或商品强匹配不足，拒绝自动续跑")
        if script is None:
            script = generate_qianchuan_script(
                group, product_context=product_context, selling_points=[]
            )
            script["preview_mode"] = False
        else:
            script["product_context"] = product_context
'''
    if old in block:
        block = block.replace(old, new, 1)
        source = source[:start] + block + source[end:]
    elif "script, pinned_product_id = _saved_qianchuan_resume(group)" not in block:
        raise RuntimeError("pipeline block drifted")

    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / path.name
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(source, encoding="utf-8")
    result = {"patched_at": datetime.now().isoformat(), "path": str(path),
              "backup": str(backup), "before_sha256": before_sha,
              "after_sha256": hashlib.sha256(source.encode()).hexdigest()}
    (backup_dir / "journal.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("backup_dir", type=Path)
    args = parser.parse_args()
    print(json.dumps(patch(args.path, args.backup_dir), ensure_ascii=False))
