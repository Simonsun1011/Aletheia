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


def test_revision_appends_full_field_set_and_keeps_history(client):
    created = client.post("/api/judgments", json=VALID).json()
    root_id = created["root_id"]

    rev = client.post(
        f"/api/judgments/{root_id}/entries",
        json={
            "kind": "revision",
            "jtype": "action",
            "direction": "outperform",
            "horizon_days": 30,
            "confidence": 0.55,
            "text": "修订：窗口缩短为30交易日",
            "falsification": "跌破SMA50且相对SOXX持续落后",
        },
    )
    assert rev.status_code == 201, rev.text
    body = rev.json()
    assert body["kind"] == "revision"
    assert body["jtype"] == "action"
    assert body["horizon_days"] == 30
    assert body["confidence"] == 0.55
    assert body["text"] == "修订：窗口缩短为30交易日"
    assert body["expires_on"]

    chain = client.get(f"/api/judgments/{root_id}").json()
    assert chain["status"] == "open"
    assert len(chain["entries"]) == 2
    assert chain["entries"][0]["kind"] == "original"
    assert chain["entries"][0]["horizon_days"] == 40
    assert chain["entries"][1]["kind"] == "revision"
    assert chain["entries"][1]["horizon_days"] == 30


def test_revision_missing_fields_422(client):
    created = client.post("/api/judgments", json=VALID).json()
    r = client.post(
        f"/api/judgments/{created['root_id']}/entries",
        json={"kind": "revision", "text": "缺字段"},
    )
    assert r.status_code == 422


def test_revision_jtype_immutable_422(client):
    created = client.post("/api/judgments", json=VALID).json()
    r = client.post(
        f"/api/judgments/{created['root_id']}/entries",
        json={
            "kind": "revision",
            "jtype": "fact",
            "text": "试图改类型",
        },
    )
    assert r.status_code == 422


def test_origin_defaults_journal_and_console_filter(client):
    """v1.6: origin defaults to 'journal'; console submissions filter separately."""
    j = client.post("/api/judgments", json=VALID).json()
    assert j["origin"] == "journal"

    c = client.post(
        "/api/judgments", json={**VALID, "origin": "console"}
    ).json()
    assert c["origin"] == "console"

    console_only = client.get("/api/judgments?origin=console").json()
    root_ids = {ch["root_id"] for ch in console_only}
    assert c["root_id"] in root_ids
    assert j["root_id"] not in root_ids

    journal_only = client.get("/api/judgments?origin=journal").json()
    j_roots = {ch["root_id"] for ch in journal_only}
    assert j["root_id"] in j_roots
    assert c["root_id"] not in j_roots


def test_origin_invalid_value_422(client):
    r = client.post("/api/judgments", json={**VALID, "origin": "bogus"})
    assert r.status_code == 422
