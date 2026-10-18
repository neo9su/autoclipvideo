import json
import ast
from pathlib import Path
from typing import Any, Dict, Optional


source = Path(__file__).resolve().parents[1].joinpath("backend/api_v2.py").read_text()
tree = ast.parse(source)
selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
            and node.name in {"_loads_qianchuan_json", "_saved_qianchuan_resume"}]
namespace = {"json": json, "Any": Any, "Dict": Dict, "Optional": Optional}
exec(compile(ast.Module(body=selected, type_ignores=[]), "api_v2.py", "exec"), namespace)
_saved_qianchuan_resume = namespace["_saved_qianchuan_resume"]


def test_resume_keeps_pinned_link_bearing_product():
    script = {"preview_mode": True, "product_context": {
        "id": 740, "product_id": "3829443305008136690",
        "product_url": "https://haohuo.jinritemai.com/ecommerce/trade/detail/index.html?id=3829443305008136690",
    }}
    saved, identity = _saved_qianchuan_resume({"qianchuan_script": json.dumps(script)})
    assert saved == script
    assert identity == "740"


def test_resume_rejects_missing_or_malformed_saved_identity():
    assert _saved_qianchuan_resume({"qianchuan_script": "{}"}) == (None, None)
    assert _saved_qianchuan_resume({"qianchuan_script": json.dumps({
        "product_context": {"product_url": ""}
    })}) == (None, None)


def test_resume_preserves_identity_without_url():
    for url in (None, "", "not-a-link"):
        script = {"preview_mode": False, "product_context": {"id": 740, "product_url": url}}
        saved, identity = _saved_qianchuan_resume({"qianchuan_script": json.dumps(script)})
        assert saved == script and identity == "740"
