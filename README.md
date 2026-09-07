# Binance Rolling VWAP Scanner

A local read-only market screener for current Binance USDT spot pairs. It downloads 455 completed daily candles from Binance, overlays the latest 89 days from Velo, calculates rolling 7D, 30D, 90D, and 365D VWAPs as `sum(dollar_volume) / sum(coin_volume)`, ranks price distance above/below the selected window, and plots price with VWAP when a ticker is selected.

The scanner also enriches recognized assets with Velo circulating market capitalization. The table can be sorted by market cap and filtered with multi-select buckets: mega-cap (≥$10B), large-cap ($1B–$10B), mid-cap ($100M–$1B), small-cap (<$100M), and Unknown. Bucket combinations persist locally.

Light mode remains the default, with a persistent dark-mode toggle in the header.

The Trend column scores the four ordered comparisons—Close/7D, 7D/30D, 30D/90D, and 90D/365D—from -4 (Strong down) to +4 (Strong up). Flip-watch and confirmed-transition alerts are ranked by an empirically smoothed 20-day continuation probability and sample count. The Alerts-only filter and browser notifications are advisory and deduplicated by symbol, candle date, and alert type. Clicking a ticker opens a deterministic signal discussion explaining its structural regime, fast VWAP transition, score change, probability, and uncertainty.

The persistent Alert tracker stores alerts in SQLite with a ten-day same-symbol/type cooldown. Its slide-over menu loads the complete available history, supports ticker and alert-type filters, and links each historical alert back to the current ticker detail view. The included backfill reconstructs alerts from the cached historical study data.

The detail panel uses the locally bundled, Apache-2.0 licensed TradingView Lightweight Charts 5.2.1. It supports native wheel/pinch zoom, drag-to-pan, crosshair inspection, responsive resizing, and 1Y/2Y/All range controls without an API key or CDN dependency.

> Why hybrid data? The configured Velo REST entitlement rejects starts older than 90 days. Binance-native klines provide the required 365-day backfill; Velo remains the preferred recent-data layer and overrides matching dates.

## Run

```bash
python app.py --refresh
```

Then open <http://127.0.0.1:8791>.

Subsequent launches can skip the backfill:

```bash
python app.py
```

Refresh data and exit:

```bash
python app.py --refresh-only
```

The Velo key is read from `VELO_API_KEY` or the existing Hermes `.env`; it is never sent to the browser or written into project files.

## Tests

```bash
python -m unittest discover -s tests -v
```
