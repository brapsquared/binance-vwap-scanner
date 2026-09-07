# MTF rolling-VWAP event study

## Scope

- Current Binance USDT spot universe; up to 1,000 completed UTC daily bars per symbol.
- Signals use close-of-day information; entry is next day's open.
- 20 bps round-trip cost and $5M trailing 30-day median quote-volume filter.
- Last 365 days are held out as the test period.
- Same-date cross-sectional baseline uses other liquid Binance USDT symbols.

## Initial 20-day candidate gate

A candidate passes only when train and test median returns and cross-sectional edges are positive, both absolute and edge hit rates exceed 50%, and both samples contain at least 50 events.

| Strategy | Side | Train n | Test n | Test median | Test baseline edge | Test hit | Edge hit | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fresh_stack | long | 176 | 59 | -0.56% | +7.29% | 25.4% | 74.6% | FAIL |
| cross_7_30_regime | long | 99 | 66 | -1.15% | +6.56% | 27.3% | 75.8% | FAIL |
| pullback_recapture | long | 294 | 98 | -2.05% | +6.09% | 22.4% | 74.5% | FAIL |
| compression_break | long | 2 | 14 | -0.23% | +2.56% | 7.1% | 85.7% | FAIL |
| cross_7_30_regime | short | 348 | 259 | +13.45% | +1.39% | 72.6% | 57.5% | FAIL |
| fresh_stack | short | 518 | 612 | +7.61% | -0.04% | 64.4% | 48.9% | FAIL |
| pullback_recapture | short | 568 | 668 | +6.48% | -0.09% | 65.0% | 49.1% | FAIL |
| compression_break | short | 21 | 9 | -0.25% | -7.05% | 22.2% | 11.1% | FAIL |

## Caveats

- Survivorship bias: the universe contains symbols trading today, not delisted historical symbols.
- Cross-sectional events share dates and are correlated; raw event counts are not independent samples.
- Short results ignore borrow/funding constraints and are hypotheses for perpetual-futures execution, not executable spot shorts.
- The period contains strong market regimes; a longer history and venue-specific perps data are required before production alerts.
- This is an event study, not a portfolio equity curve. Passing signals still need explicit stop/exit and exposure rules.