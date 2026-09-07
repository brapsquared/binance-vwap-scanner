from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HORIZONS = (1, 3, 5, 10, 20, 30)
COST = 0.002
MIN_LIQUIDITY = 5_000_000

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"

events = pd.read_csv(RESULTS / "events.csv", parse_dates=["signal_date", "entry_date"])
frames = []
for path in DATA.glob("*.csv.gz"):
    frame = pd.read_csv(path, parse_dates=["date"])
    frame["date"] = pd.to_datetime(frame.date, utc=True)
    frame["symbol"] = path.name.removesuffix(".csv.gz")
    frame["liq_30"] = frame.quote_volume.shift(1).rolling(30, min_periods=20).median()
    frames.append(frame[["date", "symbol", "open", "close", "liq_30"]])
market = pd.concat(frames, ignore_index=True)
opens = market.pivot(index="date", columns="symbol", values="open")
closes = market.pivot(index="date", columns="symbol", values="close")
liquidity = market.pivot(index="date", columns="symbol", values="liq_30")

def market_median(entry_date, exit_date):
    if entry_date not in opens.index or exit_date not in closes.index:
        return np.nan
    values = closes.loc[exit_date] / opens.loc[entry_date] - 1
    liquid = liquidity.loc[entry_date] >= MIN_LIQUIDITY
    return values[liquid].replace([np.inf, -np.inf], np.nan).median()

baseline_cache = {}
for horizon in HORIZONS:
    baseline = []
    edge = []
    for row in events.itertuples():
        exit_date = row.signal_date + pd.Timedelta(days=horizon)
        key = (row.entry_date, exit_date)
        if key not in baseline_cache:
            baseline_cache[key] = market_median(*key)
        market_return = baseline_cache[key]
        direction = 1 if row.side == "long" else -1
        side_baseline = direction * market_return - COST if pd.notna(market_return) else np.nan
        signal_return = getattr(row, f"ret_{horizon}d")
        baseline.append(side_baseline)
        edge.append(signal_return - side_baseline if pd.notna(side_baseline) else np.nan)
    events[f"baseline_{horizon}d"] = baseline
    events[f"edge_{horizon}d"] = edge

events.to_csv(RESULTS / "events_with_baseline.csv", index=False)
rows = []
for keys, group in events.groupby(["strategy", "side", "split"]):
    strategy, side, split = keys
    for horizon in HORIZONS:
        signal = group[f"ret_{horizon}d"].dropna()
        base = group[f"baseline_{horizon}d"].dropna()
        edge = group[f"edge_{horizon}d"].dropna()
        rows.append({
            "strategy": strategy,
            "side": side,
            "split": split,
            "horizon": horizon,
            "n": len(edge),
            "unique_dates": group.signal_date.nunique(),
            "median_return": signal.median(),
            "hit_rate": (signal > 0).mean(),
            "median_baseline": base.median(),
            "median_edge": edge.median(),
            "edge_hit_rate": (edge > 0).mean(),
            "mean_edge": edge.mean(),
        })
summary = pd.DataFrame(rows)
summary.to_csv(RESULTS / "summary_with_baseline.csv", index=False)

pivot = summary[summary.horizon == 20].copy()
train = pivot[pivot.split == "train"].set_index(["strategy", "side"])
test = pivot[pivot.split == "test"].set_index(["strategy", "side"])
candidates = []
for key in train.index.intersection(test.index):
    tr, te = train.loc[key], test.loc[key]
    candidates.append({
        "strategy": key[0], "side": key[1],
        "train_n": int(tr.n), "test_n": int(te.n),
        "train_median_return": tr.median_return,
        "test_median_return": te.median_return,
        "train_median_edge": tr.median_edge,
        "test_median_edge": te.median_edge,
        "test_hit_rate": te.hit_rate,
        "test_edge_hit_rate": te.edge_hit_rate,
        "passes_initial_gate": bool(
            tr.n >= 50 and te.n >= 50
            and tr.median_return > 0 and te.median_return > 0
            and tr.hit_rate > .5 and te.hit_rate > .5
            and tr.median_edge > 0 and te.median_edge > 0
            and te.edge_hit_rate > .5
        ),
    })
candidates = pd.DataFrame(candidates).sort_values("test_median_edge", ascending=False)
candidates.to_csv(RESULTS / "candidate_gate.csv", index=False)

chart = test.reset_index().sort_values("median_edge")
labels = [f"{r.strategy}\n{r.side}" for r in chart.itertuples()]
fig, ax = plt.subplots(figsize=(11, 6.5), facecolor="#f3f7fb")
ax.set_facecolor("#ffffff")
y = np.arange(len(chart))
ax.barh(y - .18, chart.median_return * 100, height=.34, label="Signal return", color="#007f91")
ax.barh(y + .18, chart.median_edge * 100, height=.34, label="Cross-sectional edge", color="#6558c7")
ax.set_yticks(y, labels)
ax.axvline(0, color="#63758b", lw=.8)
ax.set_xlabel("Median 20-day return / edge after 20 bps (%)")
ax.set_title("MTF rolling-VWAP signals — held-out test year")
ax.grid(axis="x", alpha=.18)
ax.legend()
fig.tight_layout()
fig.savefig(RESULTS / "test_20d_returns_and_edge.png", dpi=170)
plt.close(fig)

lines = [
    "# MTF rolling-VWAP event study", "",
    "## Scope", "",
    "- Current Binance USDT spot universe; up to 1,000 completed UTC daily bars per symbol.",
    "- Signals use close-of-day information; entry is next day's open.",
    "- 20 bps round-trip cost and $5M trailing 30-day median quote-volume filter.",
    "- Last 365 days are held out as the test period.",
    "- Same-date cross-sectional baseline uses other liquid Binance USDT symbols.", "",
    "## Initial 20-day candidate gate", "",
    "A candidate passes only when train and test median returns and cross-sectional edges are positive, both absolute and edge hit rates exceed 50%, and both samples contain at least 50 events.", "",
    "| Strategy | Side | Train n | Test n | Test median | Test baseline edge | Test hit | Edge hit | Gate |",
    "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for row in candidates.itertuples():
    lines.append(f"| {row.strategy} | {row.side} | {row.train_n} | {row.test_n} | {row.test_median_return*100:+.2f}% | {row.test_median_edge*100:+.2f}% | {row.test_hit_rate*100:.1f}% | {row.test_edge_hit_rate*100:.1f}% | {'PASS' if row.passes_initial_gate else 'FAIL'} |")
lines += ["", "## Caveats", "", "- Survivorship bias: the universe contains symbols trading today, not delisted historical symbols.", "- Cross-sectional events share dates and are correlated; raw event counts are not independent samples.", "- Short results ignore borrow/funding constraints and are hypotheses for perpetual-futures execution, not executable spot shorts.", "- The period contains strong market regimes; a longer history and venue-specific perps data are required before production alerts.", "- This is an event study, not a portfolio equity curve. Passing signals still need explicit stop/exit and exposure rules."]
(RESULTS / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
print(candidates.to_string(index=False))
