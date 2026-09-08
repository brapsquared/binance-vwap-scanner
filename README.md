# Binance Rolling VWAP Scanner

A local read-only market screener for current Binance USDT spot pairs plus coin-underlying USDⓈ-M perpetuals that do not have a spot listing. Spot remains preferred when both exist; scaled futures duplicates and index contracts are excluded. It downloads 455 completed daily candles from Binance, overlays the latest 89 days from the matching Velo spot or futures venue, calculates rolling 7D, 30D, 90D, and 365D VWAPs as `sum(dollar_volume) / sum(coin_volume)`, ranks price distance above/below the selected window, and plots price with VWAP when a ticker is selected.

The scanner also enriches recognized assets with Velo circulating market capitalization. The table can be sorted by market cap and filtered with multi-select buckets: mega-cap (≥$10B), large-cap ($1B–$10B), mid-cap ($100M–$1B), small-cap (<$100M), and Unknown. Bucket combinations persist locally.

Light mode remains the default, with a persistent dark-mode toggle in the header.

The Trend column scores the four ordered comparisons—Close/7D, 7D/30D, 30D/90D, and 90D/365D—from -4 (Strong down) to +4 (Strong up). Flip-watch and confirmed-transition alerts are ranked by an empirically smoothed 20-day continuation probability and sample count. A dedicated persistent Flip watch selector filters Any, Bullish, or Bearish watch classifications and automatically ranks matches by continuation probability. The broader Alerts-only filter includes confirmed transitions as well. Browser notifications are advisory and deduplicated by symbol, candle date, and alert type. Clicking a ticker opens a deterministic signal discussion explaining its structural regime, fast VWAP transition, score change, probability, and uncertainty. Perp-only markets are tagged `PERP`; their continuation probability is explicitly labeled as a lower-confidence transfer from the spot-trained calibration until a dedicated futures model is available.

The persistent Alert tracker stores alerts in SQLite with a ten-day same-symbol/type cooldown. Its slide-over menu loads the complete available history, supports ticker and alert-type filters, and links each historical alert back to the current ticker detail view. The included backfill reconstructs alerts from the cached historical study data. While the dashboard is running it checks hourly and automatically refreshes data once the snapshot is more than 26 hours old.

## Action Queue

The **Action Queue** turns current signals into a review workflow while preserving the full scanner table. It includes:

- lifecycle states: Watching, Confirmed, Persisting, Weakening, and Invalidated;
- first-seen date and exact consecutive days in the displayed lifecycle state;
- minimum continuation-probability and calibration-sample controls;
- Spot, Perp-only, and combined market scope;
- a browser-local New/unviewed-only filter and Mark shown viewed action;
- signed distance-to-confirmation plus the next structural threshold;
- probability horizon, sample size, and calibration scope shown together;
- a five-node Close → 7D → 30D → 90D → 365D state map in ticker detail.

Queue ordering is unviewed first, then Confirmed, Watching, Weakening, Persisting, and Invalidated, followed by continuation probability and sample size. Probabilities are empirical directional associations—not trade-success probabilities. Perp-only rows remain clearly marked as lower-confidence transfers from the spot-trained model.

## Scheduled advisory runner

Run the unattended advisory entry point with:

```bash
python scheduled_runner.py
```

It refreshes completed-candle data, atomically claims new accepted alert IDs, and prints a probability-ranked digest to stdout. It prints **nothing** when no alert is newly deliverable, which makes it suitable for a script-only Hermes cron job. Delivery state is stored locally in ignored `data/advisory-deliveries.db`; no credentials are written to the repository. See [`docs/SCHEDULED_ADVISORY_RUNNER.md`](docs/SCHEDULED_ADVISORY_RUNNER.md) for scheduling and delivery details.

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
npm run check
```

The browser QA harness in `tests/run_frontend_browser_qa.js` verifies the Action Queue at desktop and 390px mobile widths, including responsive containment, calibration-scope visibility, chart rendering, viewed-state persistence, and HTML-injection resistance.
