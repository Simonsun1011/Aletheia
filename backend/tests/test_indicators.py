"""Indicator formula tests — must match buy_planner.py on synthetic OHLCV."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.market.indicators import buy_planner_compatible_last_row
from tools.buy_planner import DEFAULTS, compute_indicators as bp_compute


def _synthetic_ohlcv(n: int = 260, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # Random walk close
    rets = rng.normal(0.0005, 0.015, size=n)
    close = 100 * np.cumprod(1 + rets)
    high = close * (1 + rng.uniform(0.001, 0.02, size=n))
    low = close * (1 - rng.uniform(0.001, 0.02, size=n))
    open_ = close * (1 + rng.normal(0, 0.005, size=n))
    volume = rng.integers(1_000_000, 5_000_000, size=n)
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        },
        index=idx,
    )


def test_indicators_match_buy_planner():
    df = _synthetic_ohlcv()
    expected = bp_compute(df, DEFAULTS)
    actual = buy_planner_compatible_last_row(df, DEFAULTS)
    for key in expected:
        e, a = expected[key], actual[key]
        if e is None:
            assert a is None, key
        else:
            assert a is not None, key
            assert abs(float(e) - float(a)) < 1e-9, f"{key}: {e} vs {a}"
