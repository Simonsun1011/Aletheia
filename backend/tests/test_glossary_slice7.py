"""Slice 7: glossary state machine + Obsidian export (never overwrite 我的笔记)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.app.services.glossary import (
    NOTES_HEADING,
    export_glossary_to_obsidian,
    import_glossary_seed,
    set_glossary_state,
)


def test_glossary_list_and_state_patch(client, store):
    import_glossary_seed(store._conn)
    r = client.get("/api/glossary")
    assert r.status_code == 200
    body = r.json()
    assert "terms" in body
    assert "export_configured" in body
    assert any(t["term"] == "ATR" for t in body["terms"])

    patch = client.patch("/api/glossary/ATR", json={"state": "known"})
    assert patch.status_code == 200
    assert patch.json()["state"] == "known"

    bad = client.patch("/api/glossary/ATR", json={"state": "nope"})
    assert bad.status_code == 422

    missing = client.patch("/api/glossary/not_a_term_xyz", json={"state": "known"})
    assert missing.status_code == 404


def test_glossary_reset_known(client, store):
    import_glossary_seed(store._conn)
    set_glossary_state(store._conn, "ATR", "known")
    set_glossary_state(store._conn, "RSI", "saved")
    r = client.post("/api/glossary/reset-known", json={})
    assert r.status_code == 200
    assert r.json()["reset"] >= 1
    atr = client.get("/api/glossary/ATR").json()
    rsi = client.get("/api/glossary/RSI").json()
    assert atr["state"] == "unknown"
    assert rsi["state"] == "saved"


def test_obsidian_export_and_reexport_preserves_notes(client, store, tmp_path, monkeypatch):
    import_glossary_seed(store._conn)
    vault = tmp_path / "Obsidian Vault" / "Personal Knowledge" / "Aletheia"
    monkeypatch.setenv("OBSIDIAN_EXPORT_DIR", str(vault))

    # unconfigured path before env is set on module — export uses os.getenv at call time
    assert os.getenv("OBSIDIAN_EXPORT_DIR") == str(vault)

    r1 = client.post(
        "/api/glossary/ATR/export",
        json={
            "context": "2026-07-12 于 AMAT 技术面遇到",
            "note": "阶梯限价会用 ATR 定档距。",
        },
    )
    assert r1.status_code == 200
    path = Path(r1.json()["path"])
    assert path.exists()
    text1 = path.read_text(encoding="utf-8")
    assert "term: ATR" in text1
    assert NOTES_HEADING in text1
    assert "溯源：" in text1
    assert "阶梯限价会用 ATR 定档距。" in text1
    assert client.get("/api/glossary/ATR").json()["state"] == "saved"

    # user writes more notes outside the tool
    notes_block = "\n\n这是我自己的理解，工具不得覆盖。\n"
    path.write_text(
        text1.replace(
            "阶梯限价会用 ATR 定档距。\n\n",
            "阶梯限价会用 ATR 定档距。\n\n这是我自己的理解，工具不得覆盖。\n\n",
        ),
        encoding="utf-8",
    )

    r2 = client.post(
        "/api/glossary/ATR/export",
        json={
            "context": "2026-07-13 再次于操作台遇到",
            "note": "第二次补充看法。",
        },
    )
    assert r2.status_code == 200
    text2 = path.read_text(encoding="utf-8")
    assert "再次遇到：" in text2
    assert "这是我自己的理解，工具不得覆盖。" in text2
    assert "第二次补充看法。" in text2
    # 我的笔记仍只出现一次标题
    assert text2.count(NOTES_HEADING) == 1
    assert "阶梯限价会用 ATR 定档距。" in text2


def test_obsidian_export_note_optional(client, store, tmp_path, monkeypatch):
    import_glossary_seed(store._conn)
    vault = tmp_path / "vault"
    monkeypatch.setenv("OBSIDIAN_EXPORT_DIR", str(vault))
    r = client.post("/api/glossary/VIX/export", json={})
    assert r.status_code == 200
    text = Path(r.json()["path"]).read_text(encoding="utf-8")
    assert NOTES_HEADING in text
    # 无 note 时笔记区可为空
    assert "溯源：" in text


def test_obsidian_export_disabled_without_env(client, store, monkeypatch):
    import_glossary_seed(store._conn)
    monkeypatch.delenv("OBSIDIAN_EXPORT_DIR", raising=False)
    r = client.post("/api/glossary/ATR/export", json={})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "OBSIDIAN_NOT_CONFIGURED"


def test_field_labels_meta(client):
    r = client.get("/api/meta/field-labels")
    assert r.status_code == 200
    body = r.json()
    assert "price.chg_1d" in body
    assert body["price.chg_1d"]["family"] == "chg"
    assert body["price.chg_1d"]["format"] == "percent"
