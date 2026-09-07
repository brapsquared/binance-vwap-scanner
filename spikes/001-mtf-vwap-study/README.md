# 001 — MTF rolling-VWAP swing study

## Question

Given daily Binance USDT spot OHLCV, do relationships among rolling 7D, 30D, 90D, and 365D VWAPs identify repeatable long or short swings after realistic timing and costs?

## Design

- 487 current Binance USDT spot symbols; up to 1,000 completed UTC daily bars each.
- Coverage: 2023-12-06 through 2026-09-06, depending on listing date.
- Signal computed at daily close; next-open entry is retained only as an optimistic diagnostic.
- A conservative sensitivity delays entry to the next completed UTC close and uses 30/60 bps cost cases.
- 20 bps round-trip cost in the original event study.
- Minimum $5M trailing 30-day median quote volume.
- Ten-day same-symbol cooldown for event studies.
- Latest 365 days held out as the test period.
- Same-date liquid-universe cross-sectional return used as a baseline.

## Signal families

1. **Fresh stack**
   - Long: `close > VWAP7 > VWAP30 > VWAP90 > VWAP365`, only on transition into the state.
   - Short: exact reverse.
2. **7/30 cross in structural regime**
   - Long: VWAP7 crosses above VWAP30 while `close > VWAP365` and `VWAP90 > VWAP365`.
   - Short: exact reverse.
3. **Pullback recapture**
   - Long: in a 30/90/365 bull structure, close reclaims VWAP7.
   - Short: exact reverse.
4. **Compression break**
   - Fresh full-stack alignment after the four VWAPs had compressed within 4% during the prior 15 days.

## Main held-out results at 20 days

| Signal | Side | Test n | Median return | Hit rate | Median cross-sectional edge | Edge hit rate |
|---|---:|---:|---:|---:|---:|---:|
| 7/30 regime cross | Short | 259 | +13.45% | 72.6% | +1.39% | 57.5% |
| Fresh stack | Short | 612 | +7.61% | 64.4% | -0.04% | 48.9% |
| Pullback recapture | Short | 668 | +6.48% | 65.0% | -0.09% | 49.1% |
| 7/30 regime cross | Long | 66 | -1.15% | 27.3% | +6.56% | 75.8% |

The long signals often selected relative winners but still lost money outright. Most short-family gains were broad bear-market exposure rather than selection edge.

## Conservative next-close execution sensitivity

To avoid assuming an executable fill at the instantaneous next daily open, entries were delayed to the next completed UTC close and costs increased to 30 bps. Median 20-day returns remained:

| Signal | Side | Train median | Test median | Train hit | Test hit |
|---|---:|---:|---:|---:|---:|
| 7D/30D regime cross | Short | +5.28% | +13.93% | 61.8% | 68.2% |
| Fresh stack | Short | +4.25% | +6.69% | 60.0% | 65.1% |
| Pullback recapture | Short | +3.18% | +5.87% | 55.1% | 66.5% |
| 7D/30D regime cross | Long | -7.80% | -1.22% | 33.3% | 21.5% |

The directional short information survives a full-day delay. This improves confidence in the signal association, but it does not solve the portfolio/exits problem or prove market-relative alpha.

## Trade-level exit sensitivity for the leading short trigger

| Exit | Split | n | Median return | Hit rate | Median hold |
|---|---:|---:|---:|---:|---:|
| Close recaptures VWAP7 or 30 days | Train | 353 | -1.20% | 41.1% | 5d |
| Close recaptures VWAP7 or 30 days | Test | 279 | -0.01% | 49.1% | 6d |
| Close recaptures VWAP30 or 30 days | Train | 352 | -2.32% | 40.9% | 19d |
| Close recaptures VWAP30 or 30 days | Test | 280 | +0.79% | 52.1% | 23d |

The fixed-horizon event return did not survive conversion into a robust, non-overlapping trade rule with VWAP-based exits.

## Verdict: PARTIAL

### What worked

- The four VWAPs form a useful market-state hierarchy.
- Fresh 7D/30D downside crosses inside a bearish 90D/365D regime identify sustained downside episodes.
- Long-side structures contain substantial cross-sectional relative-strength information.

### What did not work

- No strategy passed the strict gate requiring positive train/test absolute returns, positive train/test cross-sectional edge, >50% hit rates, and at least 50 events in both splits.
- Naive VWAP7 and VWAP30 invalidation exits did not preserve the apparent fixed-horizon short returns.
- A BTC macro gate was cycle-confounded: the training sample was predominantly bull-regime and the test sample predominantly bear-regime.
- Compression-break samples were too small.

### Surprises

- The mirror-image long signals behaved more like relative-strength selectors than outright long entries.
- The leading short signal was positive in most quarters but negative in the latest quarter, showing regime decay.

### Recommendation before dashboard alerts

1. Extend to at least 5–6 years with paginated exchange history and regime-balanced walk-forward folds.
2. Use a perpetual-futures universe for short studies, including funding, fees, and executable venue coverage.
3. Remove stablecoins, wrapped assets, tokenized equities, and delisted-survivorship bias.
4. Test a state machine rather than one binary rule:
   - structural regime: price/VWAP365 and VWAP90/VWAP365;
   - swing regime: VWAP30/VWAP90;
   - trigger: VWAP7 cross or recapture;
   - normalized distance and slope confirmation.
5. Add volatility-aware stops and portfolio exposure caps; VWAP-only exits were too weak.
6. Validate the next chosen specification on untouched future data before emitting live alerts.

## Artifacts

- `study.py` — data acquisition, signals, and event study.
- `analyze.py` — same-date cross-sectional baseline and candidate gate.
- `trade_backtest.py` — non-overlapping VWAP-exit sensitivity.
- `execution_sensitivity.py` — delayed next-close entries under 20/30/60 bps costs.
- `regime_sensitivity.py` — explicitly post-hoc BTC regime check.
- `results/REPORT.md`, CSV outputs, and `test_20d_returns_and_edge.png`.

## Caveats

- Current-symbol survivorship bias remains.
- Cross-sectional events on the same date are correlated and are not independent observations.
- Spot data is used to discover patterns; short execution would require perps/borrow and has additional funding costs.
- This is descriptive research, not a deployable trading system or expected-return forecast.
