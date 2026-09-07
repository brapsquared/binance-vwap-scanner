# Binance 365D VWAP Scanner

A local read-only market screener for current Binance USDT spot pairs. It downloads 455 completed daily candles from Binance, overlays the latest 89 days from Velo, calculates the rolling 365-day VWAP as `sum(dollar_volume) / sum(coin_volume)`, ranks price distance above/below that level, and plots price with VWAP when a ticker is selected.

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
