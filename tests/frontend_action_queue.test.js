'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  buildStateMap,
  confirmationInfo,
  escapeHTML,
  lifecycleInfo,
  isViewed,
  notificationCopy,
  queueIdentity,
  selectQueueRows,
} = require('../static/action-queue.js');

test('HTML escaping neutralizes provider-derived markup', () => {
  assert.equal(
    escapeHTML(`<img src=x onerror="globalThis.pwned=1">&'`),
    '&lt;img src=x onerror=&quot;globalThis.pwned=1&quot;&gt;&amp;&#39;',
  );
});

test('browser notification copy carries probability context and perp warning', () => {
  const copy = notificationCopy(
    { id: 'event-1', symbol: 'BETAUSDT', label: 'Bearish flip watch', direction: 'short', probability: 0.61, samples: 180, trend_score: -1 },
    { symbol: 'BETAUSDT', market_type: 'perp', probability_horizon_days: 20, probability_model_scope: 'spot-trained transfer' },
  );
  assert.match(copy.body, /61% empirical 20D short continuation association/);
  assert.match(copy.body, /n=180/);
  assert.match(copy.body, /perp-only/);
  assert.match(copy.body, /lower confidence/);
  assert.match(copy.body, /not trade success/);
});

function row(overrides = {}) {
  return {
    symbol: 'AAAUSDT',
    market_type: 'spot',
    continuation_probability: 0.62,
    probability_samples: 140,
    trend_score: 2,
    alert_type: 'bullish_flip_watch',
    as_of: '2026-09-09',
    metrics: {
      '7': { vwap: 104, distance_pct: 1, status: 'above' },
      '30': { vwap: 100, distance_pct: 5, status: 'above' },
      '90': { vwap: 95, distance_pct: 10, status: 'above' },
      '365': { vwap: 90, distance_pct: 16, status: 'above' },
    },
    price: 105,
    ...overrides,
  };
}

test('queue filtering honors probability, samples, market type, and unviewed state', () => {
  const rows = [
    row({ symbol: 'WATCHUSDT', lifecycle_state: 'Watching' }),
    row({ symbol: 'CONFUSDT', lifecycle_state: 'Confirmed', continuation_probability: 0.70, probability_samples: 220, market_type: 'perp' }),
    row({ symbol: 'LOWUSDT', lifecycle_state: 'Persisting', continuation_probability: 0.49 }),
    row({ symbol: 'SMALLUSDT', lifecycle_state: 'Weakening', probability_samples: 20 }),
    row({ symbol: 'IDLEUSDT', lifecycle_state: 'Inactive' }),
  ];
  const viewed = new Set([queueIdentity(rows[0])]);
  const result = selectQueueRows(rows, { minProbability: 0.5, minSamples: 50, marketType: 'all', newOnly: true }, viewed);
  assert.deepEqual(result.map(item => item.symbol), ['CONFUSDT']);
  assert.deepEqual(selectQueueRows(rows, { minProbability: 0.5, minSamples: 50, marketType: 'perp', newOnly: false }, viewed).map(item => item.symbol), ['CONFUSDT']);
});

test('queue keeps unavailable probability visible only when no minimum is set', () => {
  const unrated = row({ symbol: 'UNRATEDUSDT', lifecycle: 'Watching', continuation_probability: null, probability_samples: 0 });
  assert.deepEqual(selectQueueRows([unrated], { minProbability: 0, minSamples: 0, marketType: 'all', newOnly: false }, new Set()).map(item => item.symbol), ['UNRATEDUSDT']);
  assert.deepEqual(selectQueueRows([unrated], { minProbability: 0.5, minSamples: 0, marketType: 'all', newOnly: false }, new Set()), []);
});

test('server-viewed queue events stay viewed until a new event identity arrives', () => {
  const viewed = row({ symbol: 'VIEWEDUSDT', lifecycle: 'Confirmed', event_id: 'event-1', is_new: false });
  assert.equal(isViewed(viewed, new Set()), true);
  assert.deepEqual(selectQueueRows([viewed], { minProbability: 0, minSamples: 0, marketType: 'all', newOnly: true }, new Set()), []);
  assert.equal(isViewed({ ...viewed, event_id: 'event-2', is_new: true }, new Set()), false);
});

test('queue order is unviewed then lifecycle priority, probability, and samples', () => {
  const rows = [
    row({ symbol: 'VIEWEDUSDT', lifecycle_state: 'Confirmed', continuation_probability: 0.99 }),
    row({ symbol: 'PERSISTUSDT', lifecycle_state: 'Persisting', continuation_probability: 0.99 }),
    row({ symbol: 'WATCHUSDT', lifecycle_state: 'Watching', continuation_probability: 0.51 }),
    row({ symbol: 'CONFLOWUSDT', lifecycle_state: 'Confirmed', continuation_probability: 0.60, probability_samples: 500 }),
    row({ symbol: 'CONFHIUSDT', lifecycle_state: 'Confirmed', continuation_probability: 0.60, probability_samples: 700 }),
  ];
  const viewed = new Set([queueIdentity(rows[0])]);
  const result = selectQueueRows(rows, { minProbability: 0, minSamples: 0, marketType: 'all', newOnly: false }, viewed);
  assert.deepEqual(result.map(item => item.symbol), ['CONFHIUSDT', 'CONFLOWUSDT', 'WATCHUSDT', 'PERSISTUSDT', 'VIEWEDUSDT']);
});

test('lifecycle gracefully derives current alerts and exposes age metadata', () => {
  assert.equal(lifecycleInfo(row()).state, 'Watching');
  assert.equal(lifecycleInfo(row({ alert_type: 'bearish_flip_confirmed' })).state, 'Confirmed');
  assert.deepEqual(lifecycleInfo(row({ lifecycle: { state: 'Weakening', first_seen: '2026-09-04', days_in_state: 5 } })), {
    state: 'Weakening', firstSeen: '2026-09-04', days: 5,
  });
  assert.deepEqual(lifecycleInfo(row({ alert_type: null, lifecycle: 'Persisting', first_seen: '2026-09-01', age_days: 8 })), {
    state: 'Persisting', firstSeen: '2026-09-01', days: 8,
  });
  assert.equal(queueIdentity(row({ event_id: 'accepted-event-7' })), 'accepted-event-7');
  assert.equal(lifecycleInfo(row({ alert_type: null })).state, 'Inactive');
});

test('state map models Close to all four VWAP comparisons and missing history', () => {
  const map = buildStateMap(row());
  assert.deepEqual(map.map(point => point.label), ['Close', '7D', '30D', '90D', '365D']);
  assert.deepEqual(map.map(point => point.relation), [null, 'above', 'above', 'above', 'above']);
  assert.equal(map[1].gapPct, 0.9615384615384581);
  const incomplete = buildStateMap(row({ metrics: { '7': { vwap: 104 }, '30': { vwap: null } } }));
  assert.equal(incomplete[2].available, false);
  assert.equal(incomplete[3].available, false);
  const apiMap = buildStateMap(row({ metrics: {}, comparison_map: [
    { left_value: 105, right_value: 104, relation: 'above', distance_pct: 0.96 },
    { left_value: 104, right_value: 100, relation: 'above', distance_pct: 4 },
    { left_value: 100, right_value: 95, relation: 'above', distance_pct: 5.26 },
    { left_value: 95, right_value: 90, relation: 'above', distance_pct: 5.56 },
  ] }));
  assert.deepEqual(apiMap.map(point => point.value), [105, 104, 100, 95, 90]);
});

test('confirmation details prefer API fields and otherwise derive the signed 7D/30D gap', () => {
  assert.deepEqual(confirmationInfo(row({
    alert_type: 'bullish_flip_confirmed',
    distance_to_confirmation_pct: 0,
    confirmation: { gap_7d_30d_pct: 4, next_threshold: '30D above 90D', explanation: 'Next layer remains unresolved.' },
  })), {
    gapPct: 0,
    threshold: 'Current structural transition confirmed',
    explanation: 'The current flip transition is confirmed; no additional confirmation move is required.',
    available: true,
  });
  assert.equal(confirmationInfo(row({
    alert_type: 'bullish_flip_watch',
    distance_to_confirmation_pct: 2.040816,
    confirmation: { gap_7d_30d_pct: -2, distance_to_cross_pct: 2.040816, next_threshold: '7D above 30D' },
  })).gapPct, 2.040816);
  assert.deepEqual(confirmationInfo(row({ confirmation: { gap_7d_30d_pct: -1.25, next_threshold: '7D above 30D', explanation: 'Needs a fast-VWAP recapture.' } })), {
    gapPct: -1.25,
    threshold: '7D above 30D',
    explanation: 'Needs a fast-VWAP recapture.',
    available: true,
  });
  assert.deepEqual(confirmationInfo(row({ fast_gap_pct: -2, next_structural_threshold: { left: '7D', right: '30D', direction: 'long' }, next_structural_explanation: '7D must rise 2.04% to cross above 30D.' })), {
    gapPct: -2,
    threshold: '7D above 30D',
    explanation: '7D must rise 2.04% to cross above 30D.',
    available: true,
  });
  const fallback = confirmationInfo(row());
  assert.ok(Math.abs(fallback.gapPct - 4) < 1e-10);
  assert.equal(fallback.threshold, '7D / 30D cross');
  assert.match(fallback.explanation, /4\.00% above/);
  assert.equal(confirmationInfo(row({ metrics: {} })).available, false);
});
