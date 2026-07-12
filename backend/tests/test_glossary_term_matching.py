"""Slice 7 term-matching：aliases 入库、碰撞校验、lookup 别名→canonical。"""

from __future__ import annotations

import json

import pytest

from backend.app.services.glossary import (
    GlossarySeedError,
    get_glossary_term,
    import_glossary_seed,
    list_glossary_terms,
    _validate_alias_collisions,
)


def test_glossary_list_includes_aliases(client, store):
    import_glossary_seed(store._conn)
    r = client.get("/api/glossary")
    assert r.status_code == 200
    terms = r.json()["terms"]
    pe = next(t for t in terms if t["term"] == "PE")
    assert "市盈率" in pe["aliases"]
    iv = next(t for t in terms if t["term"] == "隐含波动率")
    assert "IV" in iv["aliases"]
    assert "Implied Volatility" in iv["aliases"]


def test_glossary_lookup_by_alias_pe(client, store):
    import_glossary_seed(store._conn)
    r = client.get("/api/glossary/" + "市盈率")
    assert r.status_code == 200
    body = r.json()
    assert body["term"] == "PE"
    assert "市盈率" in body["aliases"]


def test_glossary_lookup_by_alias_iv(client, store):
    import_glossary_seed(store._conn)
    r = client.get("/api/glossary/IV")
    assert r.status_code == 200
    assert r.json()["term"] == "隐含波动率"


def test_glossary_patch_via_alias(client, store):
    import_glossary_seed(store._conn)
    r = client.patch("/api/glossary/" + "市盈率", json={"state": "known"})
    assert r.status_code == 200
    assert r.json()["term"] == "PE"
    assert r.json()["state"] == "known"
    # canonical 同状态
    assert client.get("/api/glossary/PE").json()["state"] == "known"


def test_seed_import_idempotent_with_aliases(store):
    n1 = import_glossary_seed(store._conn)
    n2 = import_glossary_seed(store._conn)
    assert n1 == n2
    assert n1 >= 100
    rows = list_glossary_terms(store._conn)
    assert any(t["term"] == "Fear & Greed Index" for t in rows)
    fear = next(t for t in rows if t["term"] == "Fear & Greed Index")
    assert "恐惧与贪婪指数" in fear["aliases"]


def test_alias_collision_aborts(tmp_path):
    seed = {
        "terms": [
            {"term": "A", "one_liner": "a", "aliases": ["X"]},
            {"term": "B", "one_liner": "b", "aliases": ["X"]},
        ]
    }
    with pytest.raises(GlossarySeedError, match="claimed by both"):
        _validate_alias_collisions(seed["terms"])


def test_alias_collides_with_canonical_aborts():
    seed = [
        {"term": "PE", "one_liner": "x", "aliases": []},
        {"term": "Other", "one_liner": "y", "aliases": ["PE"]},
    ]
    with pytest.raises(GlossarySeedError, match="collides with canonical"):
        _validate_alias_collisions(seed)


def test_vix_full_md_has_bands_not_greed(store):
    import_glossary_seed(store._conn)
    row = get_glossary_term(store._conn, "VIX")
    assert row is not None
    assert "15–20" in row["full_md"] or "15-20" in row["one_liner"] or "常态约15" in row["one_liner"]
    # 分档在 VIX；并显式与 Fear & Greed 划界（种子文案可出现「贪婪」作否定说明）
    assert "Fear & Greed" in row["full_md"]
    fear = get_glossary_term(store._conn, "恐惧与贪婪指数")
    assert fear is not None
    assert fear["term"] == "Fear & Greed Index"
