'use strict';

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const port = Number(process.argv[2] || 8798);

const metrics = (price, values) => Object.fromEntries(['7', '30', '90', '365'].map((period, index) => {
  const vwap = values[index];
  return [period, { vwap, distance_pct: (price / vwap - 1) * 100, status: price >= vwap ? 'above' : 'below' }];
}));

const rows = [
  {
    symbol: 'ALPHAUSDT', price: 105, market_type: 'spot', market_cap: 12_400_000_000, history_days: 500, as_of: '2026-09-09',
    metrics: metrics(105, [104, 100, 96, 90]), trend_score: 4, trend_level: 'Strong up', score_change_5d: 2,
    alert_type: 'bullish_flip_confirmed', continuation_probability: 0.68, probability_samples: 240,
    probability_horizon_days: 10, probability_model_scope: 'spot-trained', fast_gap_pct: 4,
    next_structural_threshold: null, next_structural_explanation: 'All four structural comparisons already align long.',
    signal_discussion: { headline: 'Confirmed upward transition', body: 'Fixture data for local browser verification. This is an advisory state, not a trade instruction.' },
  },
  {
    symbol: 'BETAUSDT', price: 98, market_type: 'perp', market_cap: null, history_days: 420, as_of: '2026-09-09',
    metrics: metrics(98, [97, 100, 103, 108]), trend_score: -1, trend_level: 'Early down', score_change_5d: -2,
    alert_type: 'bearish_flip_watch', continuation_probability: 0.61, probability_samples: 180,
    probability_horizon_days: 20, probability_model_scope: 'spot-trained transfer', fast_gap_pct: -3,
    next_structural_threshold: { left: '7D', right: '30D', direction: 'short' },
    next_structural_explanation: '<img id="xss-probe" src=x onerror="globalThis.__vwapXss=1">7D must hold below 30D through the next qualifying structural transition.',
    signal_discussion: { headline: 'Bearish flip watch', body: 'Perp-only fixture probability is transferred from spot calibration and should be treated as lower confidence.' },
  },
  {
    symbol: 'GAMMAUSDT', price: 51, market_type: 'spot', market_cap: 600_000_000, history_days: 120, as_of: '2026-09-09',
    metrics: metrics(51, [50, 49, 48, 47]), trend_score: 2, trend_level: 'Up', score_change_5d: 0,
    alert_type: null, continuation_probability: null, probability_samples: 10,
  },
];

const queue = [
  { ...rows[0], lifecycle: 'Confirmed', first_seen: '2026-09-09', age_days: 0, event_id: 'ALPHA:confirmed:2026-09-09', is_new: true },
  { ...rows[1], lifecycle: 'Watching', first_seen: '2026-09-07', age_days: 2, event_id: 'BETA:watching:2026-09-07', is_new: true },
];

const chart = symbol => Array.from({ length: 30 }, (_, index) => {
  const base = symbol === 'BETAUSDT' ? 92 : 88;
  const close = base + index * 0.52 + Math.sin(index / 3);
  return {
    time: `2026-08-${String(index + 1).padStart(2, '0')}`,
    close,
    vwap_7: close - 1,
    vwap_30: close - 3,
    vwap_90: close - 5,
    vwap_365: close - 8,
  };
});

function json(response, value) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(200, { 'Content-Type': 'application/json', 'Content-Length': body.length, 'Cache-Control': 'no-store' });
  response.end(body);
}

function file(response, relativePath, contentType) {
  const body = fs.readFileSync(path.join(root, relativePath));
  response.writeHead(200, { 'Content-Type': contentType, 'Content-Length': body.length, 'Cache-Control': 'no-store' });
  response.end(body);
}

http.createServer((request, response) => {
  const url = new URL(request.url, `http://127.0.0.1:${port}`);
  if (url.pathname === '/' || url.pathname === '/index.html') return file(response, 'static/index.html', 'text/html; charset=utf-8');
  if (url.pathname === '/static/action-queue.js') return file(response, 'static/action-queue.js', 'text/javascript; charset=utf-8');
  if (url.pathname === '/static/vendor/lightweight-charts.standalone.production.js') return file(response, 'static/vendor/lightweight-charts.standalone.production.js', 'text/javascript; charset=utf-8');
  if (url.pathname === '/api/scanner') return json(response, { rows, alerts: [], meta: { generated_at: new Date().toISOString() } });
  if (url.pathname === '/api/action-queue') return json(response, { count: queue.length, items: queue });
  if (url.pathname.startsWith('/api/chart/')) return json(response, chart(url.pathname.split('/').pop()));
  if (url.pathname === '/api/alerts-history') return json(response, { alerts: [], count: 0, total: 0 });
  response.writeHead(404).end('Not found');
}).listen(port, '127.0.0.1', () => console.log(`Frontend fixture ready at http://127.0.0.1:${port}`));
