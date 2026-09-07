"""Independent live-data verification for the generated scanner cache."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from scanner import fetch_binance_klines, fetch_velo_rows, load_velo_key

data = root / "data"
payload = json.loads((data / "scanner.json").read_text(encoding="utf-8"))
btc = next(row for row in payload["rows"] if row["symbol"] == "BTCUSDT")
end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
end_ms = int(end.timestamp() * 1000) - 1
binance = fetch_binance_klines("BTCUSDT", end_ms, 457)
velo = fetch_velo_rows(
    ["BTCUSDT"],
    int((end - timedelta(days=89)).timestamp() * 1000),
    end_ms,
    load_velo_key(),
)
merged = {str(row["time"]): row for row in binance + velo}
manual = {}
for period in (7, 30, 90, 365):
    window = sorted(merged.values(), key=lambda row: int(row["time"]))[-period:]
    manual[str(period)] = sum(float(row["dollar_volume"]) for row in window) / sum(
        float(row["coin_volume"]) for row in window
    )
comparisons = {
    period: {
        "snapshot": btc["metrics"][period]["vwap"],
        "manual": value,
        "absolute_difference": abs(btc["metrics"][period]["vwap"] - value),
    }
    for period, value in manual.items()
}
print(json.dumps({
    "symbols": len(payload["rows"]),
    "refresh_errors": len(payload["meta"]["errors"]),
    "btc_vwap_comparisons": comparisons,
    "btc_statuses": {period: btc["metrics"][period]["status"] for period in manual},
    "btc_history_days": btc["history_days"],
    "history_files": len(list((data / "history").glob("*.json"))),
}, indent=2))
