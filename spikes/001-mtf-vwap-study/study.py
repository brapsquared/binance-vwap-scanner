from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"
WINDOWS = (7, 30, 90, 365)
HORIZONS = (1, 3, 5, 10, 20, 30)
STRATEGIES = (
    "fresh_stack",
    "cross_7_30_regime",
    "pullback_recapture",
    "compression_break",
)


def add_vwaps(frame: pd.DataFrame, windows=WINDOWS) -> pd.DataFrame:
    out = frame.copy()
    for window in windows:
        base = out["base_volume"].rolling(window, min_periods=window).sum()
        quote = out["quote_volume"].rolling(window, min_periods=window).sum()
        out[f"vwap_{window}"] = quote / base.replace(0, np.nan)
    return out


def build_signals(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    required = ["close", "vwap_7", "vwap_30", "vwap_90", "vwap_365"]
    valid = out[required].notna().all(axis=1)
    out["stack_long"] = valid & (out.close > out.vwap_7) & (out.vwap_7 > out.vwap_30) & (out.vwap_30 > out.vwap_90) & (out.vwap_90 > out.vwap_365)
    out["stack_short"] = valid & (out.close < out.vwap_7) & (out.vwap_7 < out.vwap_30) & (out.vwap_30 < out.vwap_90) & (out.vwap_90 < out.vwap_365)
    out["fresh_stack_long"] = out.stack_long & ~out.stack_long.shift(1, fill_value=False)
    out["fresh_stack_short"] = out.stack_short & ~out.stack_short.shift(1, fill_value=False)

    regime_long = valid & (out.close > out.vwap_365) & (out.vwap_90 > out.vwap_365)
    regime_short = valid & (out.close < out.vwap_365) & (out.vwap_90 < out.vwap_365)
    out["cross_7_30_regime_long"] = regime_long & (out.vwap_7 > out.vwap_30) & (out.vwap_7.shift(1) <= out.vwap_30.shift(1))
    out["cross_7_30_regime_short"] = regime_short & (out.vwap_7 < out.vwap_30) & (out.vwap_7.shift(1) >= out.vwap_30.shift(1))

    swing_long = regime_long & (out.vwap_30 > out.vwap_90)
    swing_short = regime_short & (out.vwap_30 < out.vwap_90)
    out["pullback_recapture_long"] = swing_long & (out.close > out.vwap_7) & (out.close.shift(1) <= out.vwap_7.shift(1))
    out["pullback_recapture_short"] = swing_short & (out.close < out.vwap_7) & (out.close.shift(1) >= out.vwap_7.shift(1))

    spread = out[["vwap_7", "vwap_30", "vwap_90", "vwap_365"]].max(axis=1) / out[["vwap_7", "vwap_30", "vwap_90", "vwap_365"]].min(axis=1) - 1
    recently_compressed = spread.shift(1).rolling(15, min_periods=5).min() <= 0.04
    out["compression_break_long"] = out.fresh_stack_long & recently_compressed
    out["compression_break_short"] = out.fresh_stack_short & recently_compressed
    return out


def _get_json(url: str, attempts: int = 3):
    last = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode())
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Request failed: {last}")


def current_symbols() -> list[str]:
    payload = _get_json("https://api.binance.com/api/v3/exchangeInfo")
    return sorted({row["symbol"] for row in payload["symbols"] if row.get("status") == "TRADING" and row.get("quoteAsset") == "USDT" and row.get("isSpotTradingAllowed", True)})


def fetch_symbol(symbol: str, limit: int = 1000) -> pd.DataFrame:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": "1d", "limit": limit})
    raw = _get_json(f"https://api.binance.com/api/v3/klines?{query}")
    columns = ["open_time", "open", "high", "low", "close", "base_volume", "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore"]
    frame = pd.DataFrame(raw, columns=columns)
    for column in ("open", "high", "low", "close", "base_volume", "quote_volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["date"] = pd.to_datetime(frame.open_time, unit="ms", utc=True).dt.normalize()
    # Drop the current incomplete UTC candle.
    today = pd.Timestamp.now(tz="UTC").normalize()
    return frame.loc[frame.date < today, ["date", "open", "high", "low", "close", "base_volume", "quote_volume"]].drop_duplicates("date").sort_values("date")


def load_dataset(data_dir: Path, workers: int = 8) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    data_dir.mkdir(parents=True, exist_ok=True)
    symbols = current_symbols()
    frames: dict[str, pd.DataFrame] = {}
    errors = []

    def load_one(symbol):
        path = data_dir / f"{symbol}.csv.gz"
        if path.exists():
            frame = pd.read_csv(path, parse_dates=["date"])
            frame["date"] = pd.to_datetime(frame.date, utc=True)
            return symbol, frame
        frame = fetch_symbol(symbol)
        frame.to_csv(path, index=False, compression="gzip")
        return symbol, frame

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(load_one, symbol): symbol for symbol in symbols}
        for count, future in enumerate(as_completed(futures), start=1):
            symbol = futures[future]
            try:
                name, frame = future.result()
                frames[name] = frame
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})
            if count % 50 == 0 or count == len(symbols):
                print(f"data {count}/{len(symbols)}", flush=True)
    return frames, errors


def evaluate_symbol(symbol: str, frame: pd.DataFrame, cutoff: pd.Timestamp, cost_bps: float = 20.0, min_liquidity: float = 5_000_000) -> list[dict]:
    if len(frame) < 400:
        return []
    work = build_signals(add_vwaps(frame))
    work["quote_median_30"] = work.quote_volume.shift(1).rolling(30, min_periods=20).median()
    events = []
    last_event = {}
    cost = cost_bps / 10_000
    for strategy in STRATEGIES:
        for side in ("long", "short"):
            signal_column = f"{strategy}_{side}"
            if signal_column not in work:
                continue
            direction = 1 if side == "long" else -1
            for index in np.flatnonzero(work[signal_column].fillna(False).to_numpy()):
                if index + max(HORIZONS) >= len(work) or index + 1 >= len(work):
                    continue
                if work.iloc[index].quote_median_30 < min_liquidity:
                    continue
                prior = last_event.get((strategy, side), -999)
                if index - prior < 10:
                    continue
                last_event[(strategy, side)] = index
                entry = float(work.iloc[index + 1].open)
                if not math.isfinite(entry) or entry <= 0:
                    continue
                row = {
                    "symbol": symbol,
                    "strategy": strategy,
                    "side": side,
                    "signal_date": work.iloc[index].date,
                    "entry_date": work.iloc[index + 1].date,
                    "entry": entry,
                    "liquidity_30d": float(work.iloc[index].quote_median_30),
                    "split": "test" if work.iloc[index].date >= cutoff else "train",
                }
                for horizon in HORIZONS:
                    exit_close = float(work.iloc[index + horizon].close)
                    row[f"ret_{horizon}d"] = direction * (exit_close / entry - 1) - cost
                path = work.iloc[index + 1:index + 21]
                if side == "long":
                    row["mfe_20d"] = float(path.high.max() / entry - 1)
                    row["mae_20d"] = float(path.low.min() / entry - 1)
                else:
                    row["mfe_20d"] = float(1 - path.low.min() / entry)
                    row["mae_20d"] = float(1 - path.high.max() / entry)
                events.append(row)
    return events


def summarize(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if events.empty:
        return pd.DataFrame()
    for keys, group in events.groupby(["strategy", "side", "split"], dropna=False):
        strategy, side, split = keys
        for horizon in HORIZONS:
            values = group[f"ret_{horizon}d"].dropna()
            rows.append({
                "strategy": strategy,
                "side": side,
                "split": split,
                "horizon": horizon,
                "n": len(values),
                "mean_return": values.mean(),
                "median_return": values.median(),
                "hit_rate": (values > 0).mean(),
                "p25": values.quantile(.25),
                "p75": values.quantile(.75),
                "median_mfe_20d": group.mfe_20d.median(),
                "median_mae_20d": group.mae_20d.median(),
            })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--cost-bps", type=float, default=20.0)
    parser.add_argument("--min-liquidity", type=float, default=5_000_000)
    args = parser.parse_args()
    args.results_dir.mkdir(parents=True, exist_ok=True)
    frames, errors = load_dataset(args.data_dir)
    latest = max(frame.date.max() for frame in frames.values() if not frame.empty)
    cutoff = latest - pd.Timedelta(days=365)
    records = []
    for count, (symbol, frame) in enumerate(frames.items(), start=1):
        records.extend(evaluate_symbol(symbol, frame, cutoff, args.cost_bps, args.min_liquidity))
        if count % 100 == 0:
            print(f"study {count}/{len(frames)}", flush=True)
    events = pd.DataFrame(records)
    summary = summarize(events)
    events.to_csv(args.results_dir / "events.csv", index=False)
    summary.to_csv(args.results_dir / "summary.csv", index=False)
    metadata = {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "symbols_requested": len(current_symbols()),
        "symbols_loaded": len(frames),
        "errors": errors,
        "first_date": min(frame.date.min() for frame in frames.values() if not frame.empty).isoformat(),
        "last_date": latest.isoformat(),
        "test_cutoff": cutoff.isoformat(),
        "cost_bps_round_trip": args.cost_bps,
        "minimum_trailing_30d_median_quote_volume": args.min_liquidity,
        "events": len(events),
        "strategies": list(STRATEGIES),
        "horizons": list(HORIZONS),
    }
    (args.results_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
