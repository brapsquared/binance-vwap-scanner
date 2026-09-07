"""Exploratory post-hoc sensitivity: require BTC's macro VWAP regime."""
from pathlib import Path

import pandas as pd

from study import add_vwaps

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
btc = pd.read_csv(ROOT / "data" / "BTCUSDT.csv.gz", parse_dates=["date"])
btc["date"] = pd.to_datetime(btc.date, utc=True)
btc = add_vwaps(btc)
btc["btc_bull"] = (btc.close > btc.vwap_365) & (btc.vwap_90 > btc.vwap_365)
btc["btc_bear"] = (btc.close < btc.vwap_365) & (btc.vwap_90 < btc.vwap_365)
regimes = btc.set_index("date")[["btc_bull", "btc_bear"]]

events = pd.read_csv(RESULTS / "events_with_baseline.csv", parse_dates=["signal_date", "entry_date"])
events["btc_bull"] = events.signal_date.map(regimes.btc_bull).fillna(False)
events["btc_bear"] = events.signal_date.map(regimes.btc_bear).fillna(False)
events["macro_aligned"] = ((events.side == "long") & events.btc_bull) | ((events.side == "short") & events.btc_bear)

rows = []
for (strategy, side, split), group in events.groupby(["strategy", "side", "split"]):
    for gate, sample in (("ungated", group), ("btc_macro_aligned", group[group.macro_aligned])):
        ret = sample.ret_20d.dropna()
        edge = sample.edge_20d.dropna()
        rows.append({
            "strategy": strategy,
            "side": side,
            "split": split,
            "gate": gate,
            "n": len(sample),
            "unique_dates": sample.signal_date.nunique(),
            "median_return_20d": ret.median(),
            "mean_return_20d": ret.mean(),
            "hit_rate_20d": (ret > 0).mean(),
            "median_edge_20d": edge.median(),
            "edge_hit_rate_20d": (edge > 0).mean(),
        })
summary = pd.DataFrame(rows)
summary.to_csv(RESULTS / "btc_regime_sensitivity.csv", index=False)
print(summary[summary.gate == "btc_macro_aligned"].to_string(index=False))
