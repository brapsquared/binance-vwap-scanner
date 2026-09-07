"""Conservative daily-only execution sensitivity: enter at next UTC close."""
from pathlib import Path

import numpy as np
import pandas as pd

from study import HORIZONS, STRATEGIES, add_vwaps, build_signals

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULTS = ROOT / "results"
CUTOFF = pd.Timestamp("2025-09-06", tz="UTC")
MIN_LIQ = 5_000_000
COSTS = (0.002, 0.003, 0.006)

records = []
for path in DATA.glob("*.csv.gz"):
    symbol = path.name.removesuffix(".csv.gz")
    frame = pd.read_csv(path, parse_dates=["date"])
    frame["date"] = pd.to_datetime(frame.date, utc=True)
    work = build_signals(add_vwaps(frame))
    work["liq"] = work.quote_volume.shift(1).rolling(30, min_periods=20).median()
    for strategy in STRATEGIES:
        for side in ("long", "short"):
            column = f"{strategy}_{side}"
            direction = 1 if side == "long" else -1
            last = -999
            for index in np.flatnonzero(work[column].fillna(False).to_numpy()):
                if index - last < 10 or index + 1 + max(HORIZONS) >= len(work) or work.iloc[index].liq < MIN_LIQ:
                    continue
                last = index
                entry = float(work.iloc[index + 1].close)
                for cost in COSTS:
                    row = {
                        "symbol": symbol,
                        "strategy": strategy,
                        "side": side,
                        "signal_date": work.iloc[index].date,
                        "entry_date": work.iloc[index + 1].date,
                        "split": "test" if work.iloc[index].date >= CUTOFF else "train",
                        "cost_bps": int(cost * 10_000),
                    }
                    for horizon in HORIZONS:
                        exit_price = float(work.iloc[index + 1 + horizon].close)
                        row[f"ret_{horizon}d"] = direction * (exit_price / entry - 1) - cost
                    records.append(row)

events = pd.DataFrame(records)
summary_rows = []
for keys, group in events.groupby(["strategy", "side", "split", "cost_bps"]):
    strategy, side, split, cost_bps = keys
    for horizon in HORIZONS:
        values = group[f"ret_{horizon}d"]
        summary_rows.append({
            "strategy": strategy,
            "side": side,
            "split": split,
            "cost_bps": cost_bps,
            "horizon": horizon,
            "n": len(values),
            "median_return": values.median(),
            "mean_return": values.mean(),
            "hit_rate": (values > 0).mean(),
        })
summary = pd.DataFrame(summary_rows)
summary.to_csv(RESULTS / "next_close_execution_sensitivity.csv", index=False)
print(summary[(summary.cost_bps == 30) & (summary.horizon.isin([5, 10, 20, 30]))].to_string(index=False))
