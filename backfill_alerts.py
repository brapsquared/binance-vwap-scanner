from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from alert_store import AlertStore
from calibrate_signals import DATA, MIN_LIQUIDITY, prepare
from signals import ALERT_LABELS, NON_DIRECTIONAL_BASES

ROOT = Path(__file__).resolve().parent
MODEL = json.loads((ROOT / "models" / "trend_probability.json").read_text(encoding="utf-8"))
STORE = AlertStore(ROOT / "data" / "alerts.db")

recorded = 0
for count, path in enumerate(sorted(DATA.glob("*.csv.gz")), start=1):
    symbol = path.name.removesuffix(".csv.gz")
    if symbol.removesuffix("USDT") in NON_DIRECTIONAL_BASES:
        continue
    frame = pd.read_csv(path, parse_dates=["date"])
    frame["date"] = pd.to_datetime(frame.date, utc=True)
    work = prepare(frame)
    candidates = []
    for row in work[work.alert_type.notna() & (work.liquidity >= MIN_LIQUIDITY)].itertuples():
        alert_type = row.alert_type
        group = MODEL["groups"].get(f"alert:{alert_type}", {})
        as_of = row.date.date().isoformat()
        candidates.append({
            "id": f"{symbol}:{as_of}:{alert_type}",
            "symbol": symbol,
            "as_of": as_of,
            "type": alert_type,
            "label": ALERT_LABELS[alert_type],
            "direction": "long" if alert_type.startswith("bullish") else "short",
            "trend_score": int(row.score),
            "probability": group.get("probability"),
            "samples": group.get("samples", 0),
        })
    candidates.sort(key=lambda item: item["as_of"])
    recorded += len(STORE.record(candidates, cooldown_days=10))
    if count % 100 == 0:
        print(f"backfill {count}/487", flush=True)
print(json.dumps({"accepted_this_run": recorded, "history_total": STORE.count()}, indent=2))
