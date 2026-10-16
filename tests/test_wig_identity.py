"""Real SQL and matching-gate regressions without loading GPU/LLM libraries."""
import ast
import asyncio
from pathlib import Path
import sqlite3
import sys
from typing import Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from wig_identity import evaluate_identity, load_identity_evidence, audit_database


def group(**overrides):
    return dict(id=7, room_id=2, wig_model="大波浪", wig_color="冷棕色", **overrides)


def recording(**overrides):
    row = dict(id=1, room_id=2, wig_model="大波浪", wig_color="冷棕色", product_hits=None)
    row.update(overrides)
    return row


def test_consistency_is_explicitly_not_visual_or_sku_certification():
    result = evaluate_identity(group(), [recording(), recording(id=2)])
    assert result["ok"] and result["recordings_checked"] == 2
    assert not result["visual_verified"] and not result["sku_verified"]
    assert result["requires_visual_review"]


@pytest.mark.parametrize("changes", [
    {"wig_model": "短直发"}, {"wig_model": "大波浪长款"},
    {"wig_color": "自然黑"}, {"room_id": 3},
    {"wig_model": ["大波浪", "波波头"]},
])
def test_conflicting_styles_colors_rooms_and_substring_aliases_block(changes):
    result = evaluate_identity(group(), [recording(**changes)])
    assert result["status"] == "conflict" and not result["ok"]


@pytest.mark.parametrize("value", [None, "未知", "未分类", "unknown", "  "])
def test_missing_style_requires_review_instead_of_guessing(value):
    result = evaluate_identity(group(), [recording(wig_model=value)])
    assert result["status"] == "review_required" and not result["ok"]


def test_multiple_product_mentions_require_review():
    result = evaluate_identity(group(), [recording(product_hits="元气森林,妲己狐")])
    assert not result["ok"]
    assert result["issues"][0]["code"] == "multiple_products_in_recording"


def test_same_style_color_but_different_product_names_blocks():
    result = evaluate_identity(group(), [recording(product_hits="元气森林"),
                                         recording(id=2, product_hits="妲己狐")])
    assert result["status"] == "conflict"


def test_explicit_target_product_disagreement_blocks():
    result = evaluate_identity(group(product_keywords="元气森林"),
                               [recording(product_hits="妲己狐")])
    assert result["status"] == "conflict"


def test_empty_candidate_pool_requires_review():
    assert not evaluate_identity(group(), [])["ok"]


class Query:
    def __init__(self, cursor):
        self.cursor = cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.cursor.close()

    async def fetchall(self):
        return self.cursor.fetchall()


class Database:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, args=()):
        return Query(self.connection.execute(sql, args))


def test_database_loader_checks_sixth_candidate_not_just_recent_five():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE recordings (id, room_id, wig_model, wig_color, group_id, transcribed)")
        db.executemany("INSERT INTO recordings VALUES (?,?,?,?,?,?)", [
            (i, 2, "波波头" if i == 1 else "大波浪", "冷棕色", 7, 2) for i in range(1, 7)
        ])
        db.execute("INSERT INTO recordings VALUES (100,2,'其他款','黑',8,2)")
        result = asyncio.run(load_identity_evidence(Database(db), group()))
        assert result["recordings_checked"] == 6
        assert result["status"] == "conflict"


def test_legacy_schema_missing_identity_columns_requires_review():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE recordings (id, group_id, transcribed)")
        db.execute("INSERT INTO recordings VALUES (1,7,2)")
        result = asyncio.run(load_identity_evidence(Database(db), group()))
        assert result["status"] == "review_required"


def score_function():
    # Execute the actual matcher functions, omitting module-level GPU imports.
    tree = ast.parse((BACKEND / "qianchuan_matcher.py").read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in {"_tokens", "_contains_score", "score_product_match"}]
    import re
    from typing import Iterable, Tuple
    namespace = dict(Dict=Dict, List=List, Optional=Optional, Iterable=Iterable, Tuple=Tuple, re=re)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "matcher-gate", "exec"), namespace)
    return namespace["score_product_match"]


@pytest.mark.parametrize("identity", [None, {"ok": False, "status": "conflict"},
                                       {"ok": False, "status": "review_required"}])
def test_zero_threshold_and_exact_product_cannot_bypass_identity(identity):
    score = score_function()
    result = score({"group": group(), "products": [{"id": 42, "product_id": "123"}],
                    "identity": identity}, product_id="123", threshold=0.0)
    assert not result["ok"] and "一致性" in result["reason"]


def test_consistent_metadata_preserves_matching_and_audit_evidence():
    identity = evaluate_identity(group(), [recording()])
    result = score_function()({"group": group(), "identity": identity}, threshold=0.0)
    assert result["ok"] and result["identity"] == identity


def test_rollout_audit_reads_real_database_without_mutating_it(tmp_path):
    p = tmp_path / "audit.db"
    with sqlite3.connect(p) as db:
        db.execute("CREATE TABLE clip_groups (id, room_id, wig_model, wig_color)")
        db.execute("INSERT INTO clip_groups VALUES (7,2,'大波浪','冷棕色')")
        db.execute("CREATE TABLE recordings (id, group_id, transcribed, room_id, wig_model, wig_color)")
        db.execute("INSERT INTO recordings VALUES (1,7,2,2,'短直发','冷棕色')")
    before = p.read_bytes()
    report = audit_database(p)
    assert report["statuses"] == {"conflict": 1}
    assert p.read_bytes() == before
