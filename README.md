# Binance Rolling VWAP Scanner

A local read-only market screener for current Binance USDT spot pairs. It downloads 455 completed daily candles from Binance, overlays the latest 89 days from Velo, calculates rolling 7D, 30D, 90D, and 365D VWAPs as `sum(dollar_volume) / sum(coin_volume)`, ranks price distance above/below the selected window, and plots price with VWAP when a ticker is selected.

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
