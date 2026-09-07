"""Trade-level sensitivity for the leading 7D/30D short-cross setup."""
from pathlib import Path

import pandas as pd

from study import add_vwaps, build_signals

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
CUTOFF = pd.Timestamp("2025-09-06", tz="UTC")
COST = .002
MIN_LIQ = 5_000_000
MAX_HOLD = 30


def trades_for(frame, symbol, exit_window):
    work = build_signals(add_vwaps(frame))
    work["liq"] = work.quote_volume.shift(1).rolling(30, min_periods=20).median()
    records = []
    i = 365
    while i < len(work) - 2:
        row = work.iloc[i]
        if not bool(row.cross_7_30_regime_short) or row.liq < MIN_LIQ:
            i += 1
            continue
        entry_i = i + 1
        entry = float(work.iloc[entry_i].open)
        exit_i = min(entry_i + MAX_HOLD, len(work) - 1)
        reason = "max_hold"
        for j in range(entry_i + 1, min(entry_i + MAX_HOLD, len(work) - 2) + 1):
            if work.iloc[j].close > work.iloc[j][f"vwap_{exit_window}"]:
                exit_i = j + 1
                reason = f"close_recaptured_vwap_{exit_window}"
                break
        exit_price = float(work.iloc[exit_i].open if exit_i < len(work) else work.iloc[-1].close)
        records.append({
            "symbol": symbol,
            "exit_rule": f"vwap_{exit_window}_recapture_or_{MAX_HOLD}d",
            "signal_date": row.date,
            "entry_date": work.iloc[entry_i].date,
            "exit_date": work.iloc[exit_i].date,
            "hold_days": exit_i - entry_i,
            "entry": entry,
            "exit": exit_price,
            "net_return": 1 - exit_price / entry - COST,
            "reason": reason,
            "split": "test" if row.date >= CUTOFF else "train",
        })
        i = exit_i + 1
    return records

records = []
for path in DATA.glob("*.csv.gz"):
    frame = pd.read_csv(path, parse_dates=["date"])
    frame["date"] = pd.to_datetime(frame.date, utc=True)
    for exit_window in (7, 30):
        records.extend(trades_for(frame, path.name.removesuffix(".csv.gz"), exit_window))
trades = pd.DataFrame(records)
trades.to_csv(RESULTS / "short_cross_trade_sensitivity.csv", index=False)
summary = trades.groupby(["exit_rule", "split"]).agg(
    n=("net_return", "size"),
    symbols=("symbol", "nunique"),
    median_return=("net_return", "median"),
    mean_return=("net_return", "mean"),
    hit_rate=("net_return", lambda x: (x > 0).mean()),
    median_hold=("hold_days", "median"),
    p25=("net_return", lambda x: x.quantile(.25)),
    p75=("net_return", lambda x: x.quantile(.75)),
).reset_index()
summary.to_csv(RESULTS / "short_cross_trade_summary.csv", index=False)
print(summary.to_string(index=False))
