from __future__ import annotations

import base64
import csv
import io
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from alert_store import AlertStore
from signals import enrich_live_signals

VELO_BASE = "https://api.velo.xyz"
BINANCE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_FUTURES_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
WINDOW_DAYS = 365
VWAP_WINDOWS = (7, 30, 90, 365)
HISTORY_DAYS = 455
VALUE_LIMIT = 22_500
COLUMNS = ("close_price", "coin_volume", "dollar_volume")
MODEL_PATH = Path(__file__).resolve().parent / "models" / "trend_probability.json"


def chunked(items: Sequence[str], size: int) -> Iterator[list[str]]:
    for index in range(0, len(items), size):
        yield list(items[index:index + size])


def time_windows(begin: datetime, end: datetime, max_days: int = 89) -> Iterator[tuple[datetime, datetime]]:
    cursor = begin
    while cursor < end:
        stop = min(cursor + timedelta(days=max_days), end)
        yield cursor, stop
        cursor = stop


def fetch_resilient(products: Sequence[str], fetcher) -> tuple[list[dict], list[str]]:
    """Split rejected product batches until only unsupported symbols remain."""
    if not products:
        return [], []
    try:
        return fetcher(products), []
    except Exception as exc:
        message = str(exc).lower()
        if not any(fragment in message for fragment in ("invalid products or coins", "invalid products", "invalid coins param")):
            raise
        if len(products) == 1:
            return [], [products[0]]
        midpoint = len(products) // 2
        left_rows, left_bad = fetch_resilient(products[:midpoint], fetcher)
        right_rows, right_bad = fetch_resilient(products[midpoint:], fetcher)
        return left_rows + right_rows, left_bad + right_bad


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def trailing_median_quote_volume(rows: Sequence[dict], days: int = 30) -> float | None:
    deduped = {str(row.get("time")): row for row in rows}
    ordered = sorted(deduped.values(), key=lambda row: int(row.get("time", 0)) if str(row.get("time", "")).isdigit() else str(row.get("time", "")))
    values = [_number(row.get("dollar_volume")) for row in ordered[-days:]]
    values = [value for value in values if value is not None and value >= 0]
    return float(statistics.median(values)) if values else None


def compute_multi_series(rows: Iterable[dict], windows: Sequence[int] = VWAP_WINDOWS) -> list[dict]:
    """Build close plus multiple rolling VWAPs from quote/base volume."""
    windows = tuple(sorted(set(int(value) for value in windows)))
    deduped = {str(row.get("time")): row for row in rows}
    ordered = sorted(deduped.values(), key=lambda row: int(row.get("time", 0)) if str(row.get("time", "")).isdigit() else str(row.get("time", "")))
    base_prefix = [0.0]
    quote_prefix = [0.0]
    result = []
    for index, row in enumerate(ordered):
        close = _number(row.get("close_price", row.get("close")))
        base = _number(row.get("coin_volume"))
        quote = _number(row.get("dollar_volume"))
        base = base if base is not None and base >= 0 else 0.0
        quote = quote if quote is not None and quote >= 0 else 0.0
        base_prefix.append(base_prefix[-1] + base)
        quote_prefix.append(quote_prefix[-1] + quote)
        raw_time = row.get("time")
        if str(raw_time).isdigit():
            date = datetime.fromtimestamp(int(raw_time) / 1000, tz=timezone.utc).date().isoformat()
        else:
            date = str(raw_time)
        point = {"time": date, "close": close}
        for window in windows:
            if index + 1 >= window:
                base_sum = base_prefix[index + 1] - base_prefix[index + 1 - window]
                quote_sum = quote_prefix[index + 1] - quote_prefix[index + 1 - window]
                point[f"vwap_{window}"] = quote_sum / base_sum if base_sum > 0 else None
            else:
                point[f"vwap_{window}"] = None
        result.append(point)
    return result


def compute_series(rows: Iterable[dict], window: int = WINDOW_DAYS) -> list[dict]:
    """Backward-compatible single-window series."""
    return [
        {"time": point["time"], "close": point["close"], "vwap": point[f"vwap_{window}"]}
        for point in compute_multi_series(rows, windows=(window,))
    ]


def _metric(price, vwap):
    if price is None or vwap is None or vwap <= 0:
        return {"vwap": vwap, "distance_pct": None, "status": "insufficient"}
    distance = (price / vwap - 1) * 100
    return {"vwap": vwap, "distance_pct": distance, "status": "above" if distance >= 0 else "below"}


def signal_model_metadata(model: dict) -> dict:
    return {
        "signal_model": model.get("version"),
        "signal_probability_horizon_days": model.get("horizon_days"),
        "signal_probability_min_samples": model.get("minimum_samples", 30),
        "signal_probability_definition": model.get("definition"),
        "signal_probability_scope": model.get("universe"),
        "signal_oos": model.get("oos"),
    }


def build_snapshot(histories: dict[str, list[dict]], windows: Sequence[int] | None = None) -> list[dict]:
    rows = []
    for symbol, series in histories.items():
        latest = next((point for point in reversed(series) if point.get("close") is not None), None)
        if not latest:
            row = {"symbol": symbol, "price": None, "vwap": None, "distance_pct": None, "status": "unavailable", "as_of": None, "metrics": {}}
            if windows:
                row["metrics"] = {str(period): {"vwap": None, "distance_pct": None, "status": "unavailable"} for period in windows}
            rows.append(row)
            continue
        price = _number(latest.get("close"))
        valid_days = sum(1 for point in series if point.get("close") is not None)
        if windows is None:
            metric = _metric(price, _number(latest.get("vwap")))
            rows.append({"symbol": symbol, "price": price, **metric, "as_of": latest.get("time"), "history_days": valid_days})
        else:
            metrics = {str(period): _metric(price, _number(latest.get(f"vwap_{period}"))) for period in windows}
            default_metric = metrics[str(max(windows))]
            rows.append({"symbol": symbol, "price": price, **default_metric, "metrics": metrics, "as_of": latest.get("time"), "history_days": valid_days})
    rank = {"above": 0, "below": 1, "insufficient": 2, "unavailable": 3}
    rows.sort(key=lambda row: (rank[row["status"]], -(row["distance_pct"] if row["distance_pct"] is not None else -math.inf), row["symbol"]))
    return rows


def load_velo_key() -> str:
    key = os.environ.get("VELO_API_KEY")
    if key:
        return key
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "hermes" / ".env"
    if local.exists():
        for line in local.read_text(encoding="utf-8").splitlines():
            if line.startswith("VELO_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("VELO_API_KEY is not configured in the environment or Hermes .env")


def _open_json(url: str, headers: dict | None = None, attempts: int = 3):
    last_error = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Request failed: {url}: {last_error}")


def build_market_universe(spot_payload: dict, futures_payload: dict) -> dict[str, dict]:
    spot_rows = [
        row for row in spot_payload.get("symbols", [])
        if row.get("status") == "TRADING" and row.get("quoteAsset") == "USDT" and row.get("isSpotTradingAllowed", True)
    ]
    spot_bases = {row["baseAsset"] for row in spot_rows}
    universe = {
        row["symbol"]: {
            "symbol": row["symbol"], "base_asset": row["baseAsset"], "market_type": "spot",
            "market_label": "Spot", "instrument_type": "spot", "venue": "binance-spot",
            "is_perp_only": False,
        }
        for row in spot_rows
    }
    for row in futures_payload.get("symbols", []):
        if not (row.get("status") == "TRADING" and row.get("quoteAsset") == "USDT" and row.get("contractType") == "PERPETUAL" and row.get("underlyingType") == "COIN"):
            continue
        base = row["baseAsset"]
        canonical = base
        for prefix in ("1000000", "1000"):
            if base.startswith(prefix) and base[len(prefix):] in spot_bases:
                canonical = base[len(prefix):]
                break
        if canonical in spot_bases:
            continue
        universe.setdefault(row["symbol"], {
            "symbol": row["symbol"], "base_asset": base, "market_type": "perp",
            "market_label": "Perp-only", "instrument_type": "perpetual", "venue": "binance-usdm",
            "is_perp_only": True,
        })
    return dict(sorted(universe.items()))


def get_binance_market_universe() -> dict[str, dict]:
    return build_market_universe(_open_json(BINANCE_INFO), _open_json(BINANCE_FUTURES_INFO))


def get_binance_usdt_symbols() -> list[str]:
    """Backward-compatible spot symbol discovery."""
    payload = _open_json(BINANCE_INFO)
    return sorted({item["symbol"] for item in payload.get("symbols", []) if item.get("status") == "TRADING" and item.get("quoteAsset") == "USDT" and item.get("isSpotTradingAllowed", True)})


def normalize_binance_klines(symbol: str, raw: Sequence[Sequence]) -> list[dict]:
    return [
        {"product": symbol, "time": str(row[0]), "close_price": str(row[4]), "coin_volume": str(row[5]), "dollar_volume": str(row[7])}
        for row in raw
        if len(row) >= 8
    ]


def scale_compatible(primary_rows: Sequence[dict], overlay_rows: Sequence[dict], max_ratio: float = 2.0) -> bool:
    if not primary_rows or not overlay_rows:
        return True
    primary = _number(max(primary_rows, key=lambda row: int(row.get("time", 0)))["close_price"])
    overlay = _number(max(overlay_rows, key=lambda row: int(row.get("time", 0)))["close_price"])
    if primary is None or overlay is None or primary <= 0 or overlay <= 0:
        return False
    ratio = overlay / primary
    return 1 / max_ratio <= ratio <= max_ratio


def fetch_binance_klines(symbol: str, end_ms: int, limit: int, market_type: str = "spot") -> list[dict]:
    params = urllib.parse.urlencode({"symbol": symbol, "interval": "1d", "endTime": end_ms, "limit": min(limit, 1000)})
    base = "https://fapi.binance.com/fapi/v1/klines" if market_type == "perp" else "https://api.binance.com/api/v3/klines"
    return normalize_binance_klines(symbol, _open_json(f"{base}?{params}"))


def fetch_velo_rows(products: Sequence[str], begin_ms: int, end_ms: int, key: str, market_type: str = "spot") -> list[dict]:
    params = urllib.parse.urlencode({
        "type": "futures" if market_type == "perp" else "spot",
        "exchanges": "binance-futures" if market_type == "perp" else "binance",
        "products": ",".join(products),
        "columns": ",".join(COLUMNS), "begin": begin_ms, "end": end_ms, "resolution": 1440,
    })
    auth = base64.b64encode(f"api:{key}".encode()).decode()
    req = urllib.request.Request(f"{VELO_BASE}/api/v1/rows?{params}", headers={"Authorization": f"Basic {auth}", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return list(csv.DictReader(io.StringIO(response.read().decode())))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Velo HTTP {exc.code}: {body}") from exc


def fetch_velo_caps(coins: Sequence[str], key: str) -> list[dict]:
    params = urllib.parse.urlencode({"coins": ",".join(coins)})
    auth = base64.b64encode(f"api:{key}".encode()).decode()
    req = urllib.request.Request(f"{VELO_BASE}/api/v1/caps?{params}", headers={"Authorization": f"Basic {auth}", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return list(csv.DictReader(io.StringIO(response.read().decode())))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Velo caps HTTP {exc.code}: {body}") from exc


def enrich_market_caps(snapshot: list[dict], coin_by_product: dict[str, str], cap_rows: Sequence[dict]) -> list[dict]:
    caps = {}
    for row in cap_rows:
        coin = row.get("coin")
        if coin:
            caps[coin] = {
                "market_cap": _number(row.get("circ_dollars")),
                "fdv": _number(row.get("fdv_dollars")),
                "market_cap_as_of": row.get("time"),
            }
    for row in snapshot:
        cap = caps.get(coin_by_product.get(row["symbol"]), {})
        row["market_cap"] = cap.get("market_cap")
        row["fdv"] = cap.get("fdv")
        row["market_cap_as_of"] = cap.get("market_cap_as_of")
    return snapshot


def refresh(output_dir: Path, history_days: int = HISTORY_DAYS, window: int = WINDOW_DAYS) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    histories_dir = output_dir / "history"
    histories_dir.mkdir(exist_ok=True)
    key = load_velo_key()
    universe = get_binance_market_universe()
    symbols = list(universe)
    # Only completed UTC daily candles count toward the rolling window.
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end_ms = int(end.timestamp() * 1000) - 1
    rows_by_symbol = {symbol: [] for symbol in symbols}
    errors = []

    # Exchange-native history is the complete backfill source. One request per
    # symbol covers the whole retained chart window.
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(fetch_binance_klines, symbol, end_ms, history_days + 2, universe[symbol]["market_type"]): symbol
            for symbol in symbols
        }
        completed = 0
        for future in as_completed(futures):
            symbol = futures[future]
            completed += 1
            try:
                rows_by_symbol[symbol].extend(future.result())
            except Exception as exc:
                errors.append({"stage": "binance_history", "symbols": [symbol], "error": str(exc)})
            if completed % 50 == 0 or completed == len(symbols):
                print(f"Binance history: {completed}/{len(symbols)} symbols", flush=True)

    # Velo product support is validated and cached independently for spot and perps.
    validation_begin = end - timedelta(days=7)
    unsupported_by_type = {}
    for market_type in ("spot", "perp"):
        typed_symbols = [symbol for symbol in symbols if universe[symbol]["market_type"] == market_type]
        cache_name = "velo_universe.json" if market_type == "spot" else "velo_universe_perp.json"
        universe_cache = output_dir / cache_name
        if universe_cache.exists():
            cached = json.loads(universe_cache.read_text(encoding="utf-8"))
            unsupported = [symbol for symbol in cached.get("unsupported", []) if symbol in typed_symbols]
        else:
            unsupported = []
            for batch_no, batch in enumerate(chunked(typed_symbols, 50), start=1):
                try:
                    _, rejected = fetch_resilient(
                        batch,
                        lambda products, kind=market_type: fetch_velo_rows(products, int(validation_begin.timestamp() * 1000), end_ms, key, kind),
                    )
                    unsupported.extend(rejected)
                    print(f"Velo {market_type} universe {batch_no}: {len(batch) - len(rejected)} supported, {len(rejected)} unsupported", flush=True)
                except Exception as exc:
                    errors.append({"stage": f"velo_{market_type}_universe", "symbols": batch, "error": str(exc)})
            universe_cache.write_text(json.dumps({"unsupported": unsupported}, separators=(",", ":")), encoding="utf-8")
        unsupported_by_type[market_type] = unsupported

    # This REST entitlement exposes the latest 90 days. Append Velo after
    # Binance so timestamp deduplication prefers the normalized provider row.
    recent_begin = end - timedelta(days=89)
    batch_size = max(1, VALUE_LIMIT // (89 * len(COLUMNS)))
    scale_mismatches = []
    velo_coin_by_product = {}
    velo_symbols = []
    for market_type in ("spot", "perp"):
        unsupported_set = set(unsupported_by_type[market_type])
        typed_symbols = [symbol for symbol in symbols if universe[symbol]["market_type"] == market_type and symbol not in unsupported_set]
        velo_symbols.extend(typed_symbols)
        for request_no, batch in enumerate(chunked(typed_symbols, batch_size), start=1):
            try:
                fetched = fetch_velo_rows(batch, int(recent_begin.timestamp() * 1000), end_ms, key, market_type)
                fetched_by_symbol = {}
                for row in fetched:
                    product = row.get("product")
                    fetched_by_symbol.setdefault(product, []).append(row)
                    if product and row.get("coin"):
                        velo_coin_by_product[product] = row["coin"]
                for product, product_rows in fetched_by_symbol.items():
                    if product in rows_by_symbol and scale_compatible(rows_by_symbol[product], product_rows):
                        rows_by_symbol[product].extend(product_rows)
                    elif product in rows_by_symbol:
                        scale_mismatches.append(product)
                print(f"Velo {market_type} recent request {request_no}: {len(batch)} symbols, {len(fetched)} rows", flush=True)
            except Exception as exc:
                errors.append({"stage": f"velo_{market_type}_recent", "symbols": batch, "error": str(exc)})
                print(f"Velo {market_type} recent request {request_no} failed: {exc}", flush=True)

    unsupported = sorted(set(unsupported_by_type["spot"] + unsupported_by_type["perp"]))

    coin_by_product = {symbol: velo_coin_by_product.get(symbol, universe[symbol]["base_asset"]) for symbol in symbols}
    cap_rows = []
    cap_rejected = []
    cap_coins = sorted(set(coin_by_product.values()))
    for batch_no, batch in enumerate(chunked(cap_coins, 10), start=1):
        try:
            rows, rejected = fetch_resilient(batch, lambda coins: fetch_velo_caps(coins, key))
            cap_rows.extend(rows)
            cap_rejected.extend(rejected)
            if batch_no % 10 == 0 or batch_no * 10 >= len(cap_coins):
                print(f"Velo market caps: {min(batch_no * 10, len(cap_coins))}/{len(cap_coins)} coin ids", flush=True)
        except Exception as exc:
            errors.append({"stage": "velo_caps", "coins": batch, "error": str(exc)})

    histories = {}
    for symbol, rows in rows_by_symbol.items():
        series = compute_multi_series(rows, windows=VWAP_WINDOWS)
        histories[symbol] = series
        (histories_dir / f"{symbol}.json").write_text(json.dumps(series, separators=(",", ":")), encoding="utf-8")
    snapshot = build_snapshot(histories, windows=VWAP_WINDOWS)
    for row in snapshot:
        row.update(universe[row["symbol"]])
        row["liquidity_30d"] = trailing_median_quote_volume(rows_by_symbol.get(row["symbol"], []), days=30)
    snapshot = enrich_market_caps(snapshot, coin_by_product, cap_rows)
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8")) if MODEL_PATH.exists() else {"groups": {}}
    snapshot, alert_candidates = enrich_live_signals(snapshot, histories, model)
    alert_store = AlertStore(output_dir / "alerts.db")
    alerts = alert_store.record(alert_candidates, cooldown_days=10)
    generated = datetime.now(timezone.utc).isoformat()
    payload = {
        "meta": {
            "generated_at": generated,
            "source": "Binance spot/perpetual native history + Velo latest 89 days",
            "window_days": window,
            "history_days_requested": history_days,
            "universe": "Current Binance USDT spot plus coin-underlying perp-only markets",
            "symbols": len(symbols),
            "spot_symbols": sum(1 for item in universe.values() if item["market_type"] == "spot"),
            "perp_only_symbols": sum(1 for item in universe.values() if item["market_type"] == "perp"),
            "velo_supported_symbols": len(velo_symbols),
            "velo_unsupported_symbols": unsupported,
            "velo_scale_mismatches": sorted(set(scale_mismatches)),
            "market_cap_source": "Velo circulating market cap snapshot",
            "market_cap_coverage": sum(1 for row in snapshot if row.get("market_cap") is not None),
            "market_cap_unavailable_coin_ids": sorted(set(cap_rejected)),
            **signal_model_metadata(model),
            "alert_count": len(alerts),
            "alert_history_count": alert_store.count(),
            "batch_size": batch_size,
            "errors": errors,
        },
        "alerts": alerts,
        "rows": snapshot,
    }
    (output_dir / "scanner.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload
