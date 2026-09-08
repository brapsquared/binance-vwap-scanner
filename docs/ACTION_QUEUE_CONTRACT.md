# Action Queue implementation contract

## Goal
Turn the rolling-VWAP scanner into a focused review queue without generating trade entries, exits, sizing, or orders.

## In scope

1. **Action Queue** showing current transition states that deserve review.
2. **Lifecycle and age**: Watching, Confirmed, Persisting, Weakening, Invalidated; first-seen date and days in state.
3. **Persistent controls**: minimum continuation probability, minimum calibration sample size, market type (All/Spot/Perp-only), new/unviewed only.
4. **Distance to confirmation**: signed 7D/30D gap, next structural threshold, and concise explanation.
5. **Scheduled daily runner** that refreshes after a completed UTC daily candle and emits a deduplicated advisory digest. No trade execution.
6. **Browser delivery** remains permission-gated and deduplicated; Telegram delivery is via Hermes scheduler, not embedded credentials.
7. **Ticker detail state map** for Close→7D→30D→90D→365D comparisons.
8. Preserve every existing table column/filter, themes, charts, market-cap buckets, alert tracker, and spot/perp tags.

## Lifecycle semantics

- `Watching`: current alert type ends in `_watch`.
- `Confirmed`: current alert type ends in `_confirmed`.
- `Persisting`: the latest accepted alert within 45 days points in the same direction and current score remains at least ±2.
- `Weakening`: a prior same-direction alert exists within 45 days, direction remains the same, but five-day score change moves toward zero.
- `Invalidated`: a prior alert exists within 45 days and current score is neutral or points opposite the alert direction.
- `Inactive`: no current or recent qualifying alert.

Lifecycle values are advisory derived state. Accepted alert events remain immutable and idempotent in SQLite.

## Action Queue ordering

1. Unviewed before viewed.
2. Confirmed, Watching, Weakening, Persisting, Invalidated.
3. Continuation probability descending.
4. Sample size descending.

## Probability truthfulness

- Display probability, sample count, horizon, and scope together.
- `spot-trained transfer` on perp-only markets is visibly lower-confidence.
- Probability means empirical 20-day directional continuation association, not trade success probability.
- Missing/undersampled buckets remain unavailable.

## Delivery

- Scheduled runner writes no credentials and reads `VELO_API_KEY` from the environment/Hermes `.env`.
- Output is silent when no newly accepted alerts exist.
- Alert delivery has its own event IDs; delivery failure must not prevent data refresh or alert persistence.

## Acceptance gates

- Unit tests for lifecycle transitions, cooldown/idempotency, queue filtering/order, confirmation distances, and digest dedupe.
- Full existing test suite remains green.
- JavaScript syntax check passes.
- Live scanner refresh succeeds with zero data errors.
- Browser QA verifies desktop and narrow layouts, Action Queue controls, state map, and existing chart/filter behavior.
- No `.env`, API key, database, or generated cache is committed.
