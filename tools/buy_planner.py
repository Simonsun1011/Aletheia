#!/usr/bin/env python3
"""
buy_planner.py — 买入执行计划器（Phase 0 脚本版，DESIGN.md §3.5.8）

定位：不预测低点，只压缩执行方差、消除最差行为（一次性买入撞情绪日）。
全部采用经典公开方法（SMA/布林带/ATR/RSI/VWAP），无原创信号。
工具只生成与记录方案，下单永远人工。本脚本不构成投资建议。

用法:
    pip install yfinance pandas numpy
    python3 tools/buy_planner.py AMAT 5000              # 5000美元，默认5个交易日窗口
    python3 tools/buy_planner.py MRVL 3000 --window 8 --tranches 4

输出:
    1. 经典价位锚点表（纯描述，标注当前价的相对位置）
    2. ATR阶梯限价方案（间距按该股波动自适应）
    3. 事件冲突提醒
    4. 报告存至 data/reports/，方案JSON存至 data/plans/（供日后对比窗口VWAP复盘）
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------- 默认参数（全部经典取值，理由见行内注释） ----------------
DEFAULTS = {
    "window_days": 5,        # 建仓窗口（交易日）
    "tranches": 4,           # 分批档数：3-5档是方差压缩收益递减的拐点
    "atr_period": 14,        # Wilder 原始参数
    "atr_offsets": [0.0, -0.8, -1.6, -2.5],  # 各档距现价的ATR倍数：
    #   5日窗口的预期波动约 ATR×√5≈2.2×ATR，末档-2.5×ATR约为
    #   "窗口内较深回撤才成交"，兼顾成交概率与均价改善
    "sma_short": 50,         # 中期趋势经典均线
    "sma_long": 200,         # 长期趋势经典均线
    "boll_period": 20,       # 布林带经典参数
    "boll_std": 2.0,
    "rsi_period": 14,        # Wilder 原始参数
    "vwap_days": 20,         # 近20日成交量加权均价（滚动VWAP近似）
    "history_days": 400,     # 拉取日线长度（覆盖SMA200+缓冲）
}

# 每个指标一句话知识注释（DESIGN.md 原则9：知识性解读，预写固定版本）
NOTES = {
    "SMA50/200": "50/200日均线：中/长期趋势的经典锚点。价格在其上方视为趋势完好；两线金叉/死叉是最古老的趋势信号之一。",
    "布林带": "20日均线±2倍标准差。价格触及下轨≈近期统计意义上的偏低区，但强趋势中可沿轨运行（'走轨'），不能单独作为买入理由。",
    "ATR": "平均真实波幅(14日)：该股'一天正常波动多少钱'。用它定阶梯间距，使方案自适应个股波动（波动大的股票梯距更宽）。",
    "RSI": "相对强弱指数(14日)：0-100，<30 传统上称超卖、>70 超买。仅作情绪温度计参考，非买卖信号。",
    "VWAP": "成交量加权均价：机构衡量执行质量的标准基准。买入均价优于窗口VWAP=执行合格。",
    "回撤": "距52周最高收盘价的跌幅。描述当前位置，不预示底部。",
    "摆动低点": "近10/20/60日最低价：市场近期实际防守过的价位，常被用作支撑参考。",
}


def fetch(ticker: str, days: int) -> pd.DataFrame:
    """拉取日线OHLCV。独立成函数以便测试时注入合成数据。"""
    import yfinance as yf
    df = yf.download(ticker, period=f"{days}d", interval="1d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        sys.exit(f"错误：未取到 {ticker} 数据，请检查代码拼写或网络。")
    return df.dropna()


def compute_indicators(df: pd.DataFrame, p: dict) -> dict:
    """全部经典指标，纯描述。df须含 Open/High/Low/Close/Volume。"""
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    last = float(c.iloc[-1])

    # ATR (Wilder)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / p["atr_period"], adjust=False).mean().iloc[-1])

    # RSI (Wilder)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / p["rsi_period"], adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / p["rsi_period"], adjust=False).mean()
    rsi = float((100 - 100 / (1 + gain / loss)).iloc[-1])

    boll_mid = c.rolling(p["boll_period"]).mean()
    boll_std = c.rolling(p["boll_period"]).std()

    high_52w = float(c.tail(252).max())
    return {
        "last": last,
        "atr": atr,
        "atr_pct": atr / last * 100,
        "rsi": rsi,
        "sma_short": float(c.rolling(p["sma_short"]).mean().iloc[-1]),
        "sma_long": float(c.rolling(p["sma_long"]).mean().iloc[-1]) if len(c) >= p["sma_long"] else None,
        "boll_lower": float((boll_mid - p["boll_std"] * boll_std).iloc[-1]),
        "boll_mid": float(boll_mid.iloc[-1]),
        "vwap": float((c * v).tail(p["vwap_days"]).sum() / v.tail(p["vwap_days"]).sum()),
        "high_52w": high_52w,
        "drawdown_pct": (last / high_52w - 1) * 100,
        "low_10d": float(l.tail(10).min()),
        "low_20d": float(l.tail(20).min()),
        "low_60d": float(l.tail(60).min()),
        "vol_20d_ann": float(c.pct_change().tail(20).std() * np.sqrt(252) * 100),
    }


def build_ladder(ind: dict, amount: float, p: dict) -> list:
    """ATR阶梯限价方案。各档等金额；末档带时间止损说明。"""
    last, atr = ind["last"], ind["atr"]
    offsets = p["atr_offsets"][: p["tranches"]]
    per = amount / len(offsets)
    anchors = {
        "SMA50": ind["sma_short"], "SMA200": ind["sma_long"],
        "布林下轨": ind["boll_lower"], "20日VWAP": ind["vwap"],
        "10日低点": ind["low_10d"], "20日低点": ind["low_20d"], "60日低点": ind["low_60d"],
    }
    ladder = []
    for i, k in enumerate(offsets):
        price = round(last + k * atr, 2)
        near = [name for name, a in anchors.items()
                if a is not None and abs(price - a) <= 0.5 * atr]
        ladder.append({
            "档": i + 1,
            "限价": price,
            "距现价": f"{(price / last - 1) * 100:+.1f}%",
            "金额": round(per, 2),
            "股数": int(per // price),
            "邻近锚点": "、".join(near) if near else "—",
        })
    return ladder


def render_report(ticker: str, amount: float, ind: dict, ladder: list,
                  p: dict, earnings_note: str) -> str:
    def pos(x):  # 现价相对锚点位置
        return f"{(ind['last'] / x - 1) * 100:+.1f}%" if x else "数据不足"

    L = []
    L.append(f"# {ticker} 买入执行计划  {datetime.now():%Y-%m-%d %H:%M}")
    L.append(f"\n预算 ${amount:,.0f} ｜ 窗口 {p['window_days']} 个交易日 ｜ "
             f"现价 ${ind['last']:.2f} ｜ ATR(14) ${ind['atr']:.2f}（{ind['atr_pct']:.1f}%/日）\n")
    L.append("> 本方案只压缩执行方差，不预测低点；仅供参考，不构成投资建议。下单人工执行。\n")

    L.append("## 一、经典价位锚点（纯描述）\n")
    L.append("| 锚点 | 价位 | 现价相对位置 |")
    L.append("|---|---|---|")
    rows = [
        ("SMA50", ind["sma_short"]), ("SMA200", ind["sma_long"]),
        ("布林带下轨(20,2)", ind["boll_lower"]), ("布林带中轨", ind["boll_mid"]),
        ("20日VWAP", ind["vwap"]), ("10日低点", ind["low_10d"]),
        ("20日低点", ind["low_20d"]), ("60日低点", ind["low_60d"]),
        ("52周高点", ind["high_52w"]),
    ]
    for name, val in rows:
        L.append(f"| {name} | {'$%.2f' % val if val else '—'} | {pos(val)} |")
    L.append(f"\n- 距52周高点回撤：**{ind['drawdown_pct']:+.1f}%**")
    L.append(f"- RSI(14)：**{ind['rsi']:.0f}**（<30超卖/>70超买，仅作情绪参考）")
    L.append(f"- 20日年化波动率：{ind['vol_20d_ann']:.0f}%\n")

    L.append("## 二、ATR阶梯限价方案\n")
    L.append("| 档 | 限价 | 距现价 | 金额 | 股数 | 邻近锚点 |")
    L.append("|---|---|---|---|---|---|")
    for r in ladder:
        L.append(f"| {r['档']} | ${r['限价']:.2f} | {r['距现价']} | "
                 f"${r['金额']:,.0f} | {r['股数']} | {r['邻近锚点']} |")
    L.append(f"\n**时间止损**：窗口最后一天（第{p['window_days']}个交易日）收盘前，"
             "未成交档位按当时市价限价单补齐——分批的目的不是等更低，是消除方差。")
    L.append("**执行纪律**：只用限价单；避开开盘后30分钟（日内波动U型分布，开盘段噪音最大）。\n")

    L.append("## 三、事件冲突检查\n")
    L.append(f"- 财报：{earnings_note}")
    L.append("- 请人工核对窗口内是否有 FOMC / CPI / PCE 发布日"
             "（https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm）。"
             "若横跨重大事件，考虑将末档留到事件后。\n")

    L.append("## 四、复盘预登记\n")
    L.append("窗口结束后，用实际成交均价对比窗口VWAP评估执行质量（判断类型4）；"
             "论点本身用20–60交易日相对QQQ/行业ETF收益另行考核。\n")

    L.append("## 附：指标知识注释\n")
    for k, v in NOTES.items():
        L.append(f"- **{k}**：{v}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="买入执行计划器")
    ap.add_argument("ticker")
    ap.add_argument("amount", type=float, help="总预算（美元）")
    ap.add_argument("--window", type=int, default=DEFAULTS["window_days"])
    ap.add_argument("--tranches", type=int, default=DEFAULTS["tranches"],
                    choices=[3, 4], help="分批档数")
    args = ap.parse_args()

    p = dict(DEFAULTS, window_days=args.window, tranches=args.tranches)
    ticker = args.ticker.upper()

    df = fetch(ticker, p["history_days"])
    ind = compute_indicators(df, p)
    ladder = build_ladder(ind, args.amount, p)

    # 财报日期（尽力而为）
    earnings_note = "未能自动获取，请人工确认"
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
        ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if ed:
            earnings_note = f"{ed[0]}（若落在窗口内，建议绕开或留份额在财报后）"
    except Exception:
        pass

    report = render_report(ticker, args.amount, ind, ladder, p, earnings_note)

    # 相对仓库根解析，不依赖 cwd
    repo_root = Path(__file__).resolve().parent.parent
    reports_dir = repo_root / "data" / "reports"
    plans_dir = repo_root / "data" / "plans"
    reports_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    rpath = reports_dir / f"{ticker}_{stamp}.md"
    rpath.write_text(report, encoding="utf-8")
    # 方案JSON：供日后自动对比窗口VWAP复盘
    (plans_dir / f"{ticker}_{stamp}.json").write_text(json.dumps({
        "ticker": ticker, "created": datetime.now().isoformat(),
        "amount": args.amount, "window_days": p["window_days"],
        "price_at_plan": ind["last"], "atr": ind["atr"],
        "ladder": ladder, "status": "open",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(report)
    print(f"\n[已保存] {rpath}")
    print(f"[已保存] {plans_dir / f'{ticker}_{stamp}.json'}")


if __name__ == "__main__":
    main()
