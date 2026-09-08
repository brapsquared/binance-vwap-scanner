# Product roadmap

## Current delivery wave

- [x] Action Queue
- [x] Alert lifecycle and age
- [x] Minimum probability and sample controls
- [x] Spot/perp-only market filter
- [x] Distance-to-confirmation explanation
- [x] Scheduled daily advisory scan and delivery hook
- [x] Four-VWAP ticker state map

## Remaining recommendations for future builds

### Signal/model quality

- [ ] Dedicated perpetual-futures probability calibration using funding, premium/basis, OI, and executable venue coverage
- [ ] Regime-conditioned probabilities for BTC bull/bear/neutral and volatility regimes
- [ ] Volatility-normalized VWAP distance (`z_h`)
- [ ] VWAP slope features and slope-alignment confidence
- [ ] Five-to-six-year point-in-time universe with delistings and symbol migrations
- [ ] Walk-forward calibration curves and confidence intervals by alert type
- [ ] Capacity, funding, spread, and 1×/2×/3× cost stress tests

### Ticker investigation

- [x] Independent toggles for all four VWAP lines on one chart
- [ ] Optional volume series on the ticker chart
- [ ] Exact historical outcome panel: 5D/10D/20D hit rates, median move, MFE, and MAE
- [ ] BTC regime, relative strength, sector peers, and market-wide breadth context
- [ ] Alert probability history and local trend sparkline

### Alert operations

- [ ] Immediate-versus-digest delivery policy
- [ ] User snooze/dismiss state synchronized beyond one browser
- [ ] Delivery audit and retry status
- [ ] Telegram formatting and channel configuration UI

### Personalization and UX

- [ ] Named saved scanner presets
- [ ] Customizable/reorderable columns
- [ ] Richer stale, suppression, unavailable, and empty states
- [ ] Threshold-specific alert profiles per saved preset

## Guardrails

The scanner remains advisory. No trading, order placement, position sizing, or account mutation is in scope until separately authorized with frozen risk rules and execution safety controls.
