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
last_365 = sorted(merged.values(), key=lambda row: int(row["time"]))[-365:]
manual_vwap = sum(float(row["dollar_volume"]) for row in last_365) / sum(
    float(row["coin_volume"]) for row in last_365
)
print(json.dumps({
    "symbols": len(payload["rows"]),
    "refresh_errors": len(payload["meta"]["errors"]),
    "btc_snapshot_vwap": btc["vwap"],
    "btc_manual_vwap": manual_vwap,
    "absolute_difference": abs(btc["vwap"] - manual_vwap),
    "btc_status": btc["status"],
    "btc_history_days": btc["history_days"],
    "history_files": len(list((data / "history").glob("*.json"))),
}, indent=2))
