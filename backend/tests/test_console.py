"""Planner parity with buy_planner.py + console schema tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.console import CONSOLE_TOP_KEYS, build_console
from backend.app.services.glossary import import_glossary_seed
from backend.app.services.planner import build_plan, ladder_prices_and_amounts
from backend.app.stores.sqlite_store import SqliteStore
from buy_planner import DEFAULTS, build_ladder, compute_indicators


def _synthetic_ohlcv(n: int = 260, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.015, size=n)
    close = 100 * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0.001, 0.02, size=n))
    low = close * (1 - rng.uniform(0.001, 0.02, size=n))
    open_ = close * (1 + rng.normal(0, 0.005, size=n))
    volume = rng.integers(1_000_000, 5_000_000, size=n)
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "app.db", tmp_path / "journal")
    s.init_schema()
    yield s
    s.close()


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr("backend.app.main.create_store", lambda: store)
    with TestClient(app) as c:
        app.state.store = store
        yield c


def test_planner_matches_buy_planner_ladder(tmp_path):
    df = _synthetic_ohlcv()
    amount = 5000.0
    p = dict(DEFAULTS)
    ind = compute_indicators(df, p)
    expected = build_ladder(ind, amount, p)

    plan = build_plan(
        ticker="AMAT",
        amount=amount,
        ohlcv=df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        ),
        save=True,
    )
    # redirect save already happened under repo plans/; ok for test
    prices_e, amounts_e = ladder_prices_and_amounts(expected)
    prices_a, amounts_a = ladder_prices_and_amounts(plan["ladder"])
    assert prices_a == prices_e
    assert amounts_a == amounts_e
    assert plan["status"] == "open"
    assert (tmp_path)  # silence
    from pathlib import Path
    from backend.app.config import REPO_ROOT

    assert any(REPO_ROOT.joinpath("plans").glob(f"AMAT_*{plan['id'][-6:]}.json"))


def test_console_schema_whitelist_no_score(store, monkeypatch, tmp_path):
    df = _synthetic_ohlcv()
    # write prices into a temp market db
    from backend.app.config import Settings
    from backend.app.market.db import connect_market_db

    mdb = tmp_path / "market.db"
    conn = connect_market_db(mdb)
    for ts, row in df.iterrows():
        conn.execute(
            "INSERT INTO prices VALUES (?,?,?,?,?,?,?)",
            (
                "AMAT",
                ts.strftime("%Y-%m-%d"),
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                int(row["Volume"]),
            ),
        )
    conn.commit()
    conn.close()

    settings = Settings(
        app_db_path=store.db_path,
        journal_dir=store.journal_dir,
        cors_origins=["http://localhost:3000"],
        log_level="INFO",
        log_dir=tmp_path / "logs",
        market_db_path=mdb,
    )

    def fake_macro(_):
        return {"vix": 15.0, "yield_10y": 4.2, "qqq_chg_20d": 0.01}, []

    def fake_fund(_):
        return {
            "eps_revision_note": "开源数据源无此数据",
            "forward_eps": 1.2,
            "forward_pe": 20.0,
            "recommendation_mean": None,
            "earnings_date": None,
        }, ["EPS修正趋势数据暂缺（开源数据源无此数据）"]

    payload = build_console(
        store,
        "AMAT",
        amount=3000,
        window=5,
        settings=settings,
        macro_fn=fake_macro,
        fundamental_fn=fake_fund,
    )
    assert set(payload.keys()) == CONSOLE_TOP_KEYS
    # pedagogical panel notes may mention 多空；只检查方案与数据块
    plan_blob = str(payload.get("plan"))
    for b in ("建议买入", "建议卖出", "score", "composite_score"):
        assert b not in plan_blob
    assert payload["plan"] is not None
    assert payload["plan"]["status"] == "open"
    assert payload["fundamental"]["data"]["eps_revision_note"]
    assert payload["fundamental"]["note"]["title"]


def test_fundamental_failure_null_others_ok(store, monkeypatch, tmp_path):
    from backend.app.config import Settings

    settings = Settings(
        app_db_path=store.db_path,
        journal_dir=store.journal_dir,
        cors_origins=["http://localhost:3000"],
        log_level="INFO",
        log_dir=tmp_path / "logs",
        market_db_path=tmp_path / "empty_market.db",
    )
    from backend.app.market.db import connect_market_db

    conn = connect_market_db(settings.market_db_path)
    conn.close()
    # Do not hit network in this unit test
    monkeypatch.setattr(
        "backend.app.services.console.ensure_local_market_data",
        lambda *a, **k: ["no local market data for NVDA"],
    )

    def boom(_):
        raise RuntimeError("no fund")

    def ok_macro(_):
        return {"vix": 12.0, "yield_10y": None, "qqq_chg_20d": None}, []

    payload = build_console(
        store,
        "NVDA",
        settings=settings,
        macro_fn=ok_macro,
        fundamental_fn=boom,
    )
    assert payload["fundamental"] is None or payload["fundamental"].get("data") is None
    assert payload["macro"] is not None
    assert payload["macro"].get("data") is not None
    assert any("fundamental" in w for w in payload["warnings"])


def test_console_http_and_judgment_with_plan(client, store, monkeypatch, tmp_path):
    from backend.app.config import Settings
    from backend.app.market.db import connect_market_db

    df = _synthetic_ohlcv()
    mdb = tmp_path / "m.db"
    conn = connect_market_db(mdb)
    for ts, row in df.iterrows():
        conn.execute(
            "INSERT INTO prices VALUES (?,?,?,?,?,?,?)",
            (
                "AMAT",
                ts.strftime("%Y-%m-%d"),
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                int(row["Volume"]),
            ),
        )
    conn.commit()
    conn.close()

    settings = Settings(
        app_db_path=store.db_path,
        journal_dir=store.journal_dir,
        cors_origins=["http://localhost:3000"],
        log_level="INFO",
        log_dir=tmp_path / "logs",
        market_db_path=mdb,
    )
    monkeypatch.setattr(
        "backend.app.services.console.get_settings", lambda: settings
    )
    monkeypatch.setattr(
        "backend.app.routers.console.build_console",
        lambda store, symbol, amount=5000, window=5, live=False: build_console(
            store,
            symbol,
            amount=amount,
            window=window,
            live=live,
            settings=settings,
            macro_fn=lambda _: ({"vix": 14.0, "yield_10y": 4.0, "qqq_chg_20d": 0.02}, []),
            fundamental_fn=lambda _: (
                {
                    "eps_revision_note": "开源数据源无此数据",
                    "forward_eps": None,
                    "forward_pe": None,
                    "recommendation_mean": None,
                    "earnings_date": None,
                },
                ["EPS修正趋势数据暂缺（开源数据源无此数据）"],
            ),
        ),
    )

    r = client.get("/api/console/AMAT?amount=4000&window=5")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AMAT"
    assert body["plan"]["id"]
    plan_id = body["plan"]["id"]

    j = client.post(
        "/api/judgments",
        json={
            "object": "AMAT",
            "jtype": "action",
            "direction": "outperform",
            "horizon_days": 20,
            "confidence": 0.55,
            "text": "这是过度反应，两周内修复",
            "supporting": f"plan_id={plan_id}",
        },
    )
    assert j.status_code == 201
    assert j.json()["supporting"] == f"plan_id={plan_id}"


def test_glossary_seed_idempotent_and_lookup(client, store):
    n1 = import_glossary_seed(store._conn)
    n2 = import_glossary_seed(store._conn)
    assert n1 > 0 and n2 == n1
    r = client.get("/api/glossary/ATR")
    assert r.status_code == 200
    assert "波幅" in r.json()["one_liner"]
    missing = client.get("/api/glossary/not_a_real_term_xyz")
    assert missing.status_code == 404


def test_copy_lint_no_forbidden_advice_words():
    from pathlib import Path

    roots = [
        Path("backend/app/services/console.py"),
        Path("backend/app/services/planner.py"),
        Path("backend/app/routers/console.py"),
    ]
    forbidden = ["建议买入", "建议卖出", "看多", "看空"]
    for p in roots:
        text = p.read_text(encoding="utf-8")
        for f in forbidden:
            assert f not in text, f"{p} contains {f}"
