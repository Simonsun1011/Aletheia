"""Judgment API acceptance tests (slice-01)."""

from __future__ import annotations

VALID = {
    "object": "AMAT",
    "jtype": "action",
    "direction": "outperform",
    "horizon_days": 40,
    "confidence": 0.6,
    "text": "窗口内相对SOXX不弱即可",
}


def test_create_judgment_201(client):
    r = client.post("/api/judgments", json=VALID)
    assert r.status_code == 201
    body = r.json()
    assert body["id"]
    assert body["root_id"] == body["id"]
    assert body["expires_on"]
    assert body["status"] == "open"
    assert body["kind"] == "original"
    assert body["text"] == VALID["text"]


def test_confidence_out_of_range_422(client):
    bad = {**VALID, "confidence": 1.2}
    r = client.post("/api/judgments", json=bad)
    assert r.status_code == 422


def test_action_missing_horizon_422(client):
    bad = {**VALID}
    del bad["horizon_days"]
    r = client.post("/api/judgments", json=bad)
    assert r.status_code == 422


def test_review_closes_chain_then_amendment_409(client):
    created = client.post("/api/judgments", json=VALID).json()
    root_id = created["root_id"]

    rev = client.post(
        f"/api/judgments/{root_id}/entries",
        json={"kind": "review", "text": "到期复盘：相对QQQ略弱"},
    )
    assert rev.status_code == 201

    chain = client.get(f"/api/judgments/{root_id}").json()
    assert chain["status"] == "closed"

    am = client.post(
        f"/api/judgments/{root_id}/entries",
        json={"kind": "amendment", "text": "不应再追加"},
    )
    assert am.status_code == 409


def test_list_chains_grouped(client):
    a = client.post("/api/judgments", json=VALID).json()
    client.post(
        f"/api/judgments/{a['root_id']}/entries",
        json={"kind": "amendment", "text": "补充：关注财报"},
    )
    chains = client.get("/api/judgments").json()
    assert len(chains) >= 1
    match = next(c for c in chains if c["root_id"] == a["root_id"])
    assert len(match["entries"]) == 2
    assert match["entries"][0]["kind"] == "original"
    assert match["entries"][1]["kind"] == "amendment"
