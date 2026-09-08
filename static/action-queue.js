'use strict';

(function exposeActionQueue(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ActionQueue = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function createActionQueue() {
  const ACTIVE_STATES = ['Confirmed', 'Watching', 'Weakening', 'Persisting', 'Invalidated'];
  const STATE_RANK = new Map(ACTIVE_STATES.map((state, index) => [state, index]));

  function finite(value) {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function titleCase(value) {
    const normalized = String(value || '').trim().toLowerCase();
    return normalized ? normalized[0].toUpperCase() + normalized.slice(1) : '';
  }

  function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[character]);
  }

  function notificationCopy(alert, row = {}, defaultHorizon = 20) {
    const alertProbability = finite(alert.probability ?? alert.continuation_probability);
    const horizon = finite(row.probability_horizon_days ?? alert.probability_horizon_days) || defaultHorizon;
    const sampleCount = finite(alert.samples ?? alert.probability_samples) || 0;
    const direction = alert.direction || alert.alert_direction || row.alert_direction || row.direction || 'directional';
    const marketType = row.market_type === 'perp' ? 'perp-only' : row.market_type === 'spot' ? 'spot' : 'market unclassified';
    const scope = row.probability_model_scope || alert.probability_model_scope || (row.market_type === 'perp' ? 'spot-trained transfer' : 'spot-trained');
    const probabilityText = alertProbability === null
      ? `Probability unavailable for empirical ${horizon}D ${direction} continuation association`
      : `${Math.round(alertProbability * 100)}% empirical ${horizon}D ${direction} continuation association`;
    const confidence = row.market_type === 'perp' || String(scope).includes('transfer') ? ' · lower confidence' : '';
    return {
      title: `${alert.label || 'VWAP alert'} · ${String(alert.symbol || '').replace(/USDT$/, '')}`,
      body: `${probabilityText} · n=${sampleCount} · ${marketType} · ${scope}${confidence} · advisory; not trade success`,
      tag: alert.id,
    };
  }

  function lifecycleInfo(row) {
    const lifecycleValue = row.lifecycle;
    const lifecycle = lifecycleValue && typeof lifecycleValue === 'object' ? lifecycleValue : {};
    const queue = row.action_queue && typeof row.action_queue === 'object' ? row.action_queue : {};
    let state = row.lifecycle_state || row.action_state || (typeof lifecycleValue === 'string' ? lifecycleValue : null) || lifecycle.state || queue.state || queue.lifecycle || row.lifecycle_status_hint;
    if (!state && row.alert_type) {
      if (row.alert_type.endsWith('_watch')) state = 'Watching';
      if (row.alert_type.endsWith('_confirmed')) state = 'Confirmed';
    }
    state = titleCase(state) || 'Inactive';
    if (!STATE_RANK.has(state) && state !== 'Inactive') state = 'Inactive';
    const firstSeen = row.lifecycle_first_seen || row.state_first_seen || row.first_seen || lifecycle.first_seen || queue.first_seen || null;
    const days = finite(row.days_in_state ?? row.lifecycle_days ?? row.age_days ?? lifecycle.days_in_state ?? lifecycle.age_days ?? queue.days_in_state ?? queue.age_days);
    return { state, firstSeen, days };
  }

  function queueIdentity(row) {
    const lifecycle = lifecycleInfo(row);
    return String(
      row.action_queue_id || row.queue_event_id || row.current_alert_id || row.alert_id || row.event_id ||
      `${row.symbol || 'unknown'}:${lifecycle.firstSeen || row.as_of || 'current'}:${lifecycle.state}`
    );
  }

  function isViewed(row, viewedIds) {
    const viewed = viewedIds instanceof Set ? viewedIds : new Set(viewedIds || []);
    return viewed.has(queueIdentity(row)) || row.is_new === false || row.viewed === true || row.viewed === 1;
  }

  function probability(row) {
    return finite(row.continuation_probability ?? row.probability);
  }

  function samples(row) {
    return finite(row.probability_samples ?? row.samples) || 0;
  }

  function selectQueueRows(rows, controls, viewedIds) {
    const options = controls || {};
    const viewed = viewedIds instanceof Set ? viewedIds : new Set(viewedIds || []);
    const minProbability = finite(options.minProbability) || 0;
    const minSamples = finite(options.minSamples) || 0;
    const marketType = options.marketType || 'all';
    return (rows || []).filter(row => {
      const lifecycle = lifecycleInfo(row);
      const rowProbability = probability(row);
      const isRowViewed = isViewed(row, viewed);
      return STATE_RANK.has(lifecycle.state) &&
        (rowProbability === null ? minProbability <= 0 : rowProbability >= minProbability) &&
        samples(row) >= minSamples &&
        (marketType === 'all' || row.market_type === marketType) &&
        (!options.newOnly || !isRowViewed);
    }).sort((left, right) => {
      const viewedDelta = Number(isViewed(left, viewed)) - Number(isViewed(right, viewed));
      if (viewedDelta) return viewedDelta;
      const lifecycleDelta = STATE_RANK.get(lifecycleInfo(left).state) - STATE_RANK.get(lifecycleInfo(right).state);
      if (lifecycleDelta) return lifecycleDelta;
      const probabilityDelta = probability(right) - probability(left);
      if (probabilityDelta) return probabilityDelta;
      const sampleDelta = samples(right) - samples(left);
      if (sampleDelta) return sampleDelta;
      return String(left.symbol || '').localeCompare(String(right.symbol || ''));
    });
  }

  function metricValue(row, period) {
    const metric = row.metrics && row.metrics[String(period)];
    if (metric && finite(metric.vwap) !== null) return finite(metric.vwap);
    return finite(row[`vwap_${period}`]);
  }

  function relation(left, right) {
    if (left === null || right === null) return null;
    return left > right ? 'above' : left < right ? 'below' : 'equal';
  }

  function buildStateMap(row) {
    const comparisons = Array.isArray(row.comparison_map) ? row.comparison_map : [];
    const apiValues = comparisons.length === 4 ? [comparisons[0].left_value, ...comparisons.map(item => item.right_value)] : null;
    const values = (apiValues || [row.price ?? row.close, metricValue(row, 7), metricValue(row, 30), metricValue(row, 90), metricValue(row, 365)]).map(finite);
    const labels = ['Close', '7D', '30D', '90D', '365D'];
    return labels.map((label, index) => {
      const value = values[index];
      const comparedTo = index ? values[index - 1] : null;
      const apiComparison = index ? comparisons[index - 1] : null;
      return {
        label,
        value,
        available: value !== null,
        relation: index ? (apiComparison && apiComparison.relation !== 'unavailable' ? apiComparison.relation : relation(comparedTo, value)) : null,
        gapPct: index ? (finite(apiComparison && apiComparison.distance_pct) ?? (value !== null && comparedTo !== null && value !== 0 ? (comparedTo / value - 1) * 100 : null)) : null,
      };
    });
  }

  function confirmationInfo(row) {
    if (row.distance_to_confirmation_pct === 0 && String(row.alert_type || '').endsWith('_confirmed')) {
      return {
        gapPct: 0,
        threshold: 'Current structural transition confirmed',
        explanation: 'The current flip transition is confirmed; no additional confirmation move is required.',
        available: true,
      };
    }
    const sourceValue = row.confirmation_distance || row.distance_to_confirmation || row.confirmation;
    const source = sourceValue && typeof sourceValue === 'object' ? sourceValue : {};
    const requiredMove = finite(row.distance_to_confirmation_pct ?? source.distance_to_confirmation_pct ?? source.distance_to_cross_pct);
    const explicitGap = requiredMove ?? finite(source.gap_7d_30d_pct ?? source.fast_gap_pct ?? source.signed_gap_pct ?? row.fast_gap_pct);
    const v7 = metricValue(row, 7);
    const v30 = metricValue(row, 30);
    const gapPct = explicitGap !== null ? explicitGap : (v7 !== null && v30 !== null && v30 !== 0 ? (v7 / v30 - 1) * 100 : null);
    const thresholdValue = source.next_threshold || source.threshold || row.next_structural_threshold;
    const threshold = thresholdValue && typeof thresholdValue === 'object'
      ? `${thresholdValue.left || '7D'} ${thresholdValue.direction === 'short' ? 'below' : 'above'} ${thresholdValue.right || '30D'}`
      : thresholdValue || '7D / 30D cross';
    const providedExplanation = source.explanation || row.next_structural_explanation;
    if (gapPct === null) {
      return { gapPct: null, threshold, explanation: providedExplanation || 'A complete 7D and 30D VWAP history is required.', available: false };
    }
    const side = gapPct > 0 ? 'above' : gapPct < 0 ? 'below' : 'at';
    return {
      gapPct,
      threshold,
      explanation: providedExplanation || `The 7D VWAP is ${Math.abs(gapPct).toFixed(2)}% ${side} the 30D VWAP; confirmation requires the next qualifying structural transition.`,
      available: true,
    };
  }

  return { ACTIVE_STATES, buildStateMap, confirmationInfo, escapeHTML, isViewed, lifecycleInfo, notificationCopy, probability, queueIdentity, samples, selectQueueRows };
});
