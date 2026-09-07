from __future__ import annotations

import math
from typing import Sequence

ALERT_LABELS = {
    "bullish_flip_watch": "Bullish flip watch",
    "bearish_flip_watch": "Bearish flip watch",
    "bullish_flip_confirmed": "Bullish flip confirmed",
    "bearish_flip_confirmed": "Bearish flip confirmed",
}
NON_DIRECTIONAL_BASES = {"USDC", "FDUSD", "TUSD", "USDP", "USD1", "USDE", "USDS", "RLUSD", "XUSD", "BFUSD", "EURI", "EUR", "U"}


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def point_score(point: dict) -> int | None:
    values = [_finite(point.get(key)) for key in ("close", "vwap_7", "vwap_30", "vwap_90", "vwap_365")]
    if any(value is None for value in values):
        return None
    close, v7, v30, v90, v365 = values
    comparisons = ((close, v7), (v7, v30), (v30, v90), (v90, v365))
    return sum(1 if left > right else -1 if left < right else 0 for left, right in comparisons)


def trend_level(score: int | None) -> str:
    if score is None:
        return "Unavailable"
    return {
        4: "Strong up",
        3: "Up",
        2: "Up",
        1: "Early up",
        0: "Neutral",
        -1: "Early down",
        -2: "Down",
        -3: "Down",
        -4: "Strong down",
    }[score]


def classify_series(series: Sequence[dict]) -> dict:
    valid = [point for point in series if point_score(point) is not None]
    if not valid:
        return {
            "trend_score": None, "trend_level": "Unavailable", "score_change_5d": None,
            "direction": None, "alert_type": None, "alert_label": None, "alert_direction": None,
        }
    current = valid[-1]
    score = point_score(current)
    prior = point_score(valid[-6]) if len(valid) >= 6 else score
    previous = point_score(valid[-2]) if len(valid) >= 2 else score
    delta = score - prior
    close = float(current["close"])
    v7, v30 = float(current["vwap_7"]), float(current["vwap_30"])
    fast_gap_pct = (v7 / v30 - 1) * 100 if v30 else None
    alert_type = None
    alert_direction = None
    if previous <= 0 and score >= 2:
        alert_type, alert_direction = "bullish_flip_confirmed", "long"
    elif previous >= 0 and score <= -2:
        alert_type, alert_direction = "bearish_flip_confirmed", "short"
    elif score <= 1 and delta >= 2 and close > v7 and v7 <= v30 and abs(fast_gap_pct) <= 5:
        alert_type, alert_direction = "bullish_flip_watch", "long"
    elif score >= -1 and delta <= -2 and close < v7 and v7 >= v30 and abs(fast_gap_pct) <= 5:
        alert_type, alert_direction = "bearish_flip_watch", "short"
    direction = "long" if score > 0 else "short" if score < 0 else None
    return {
        "trend_score": score,
        "trend_level": trend_level(score),
        "score_change_5d": delta,
        "direction": direction,
        "fast_gap_pct": fast_gap_pct,
        "alert_type": alert_type,
        "alert_label": ALERT_LABELS.get(alert_type),
        "alert_direction": alert_direction,
    }


def empirical_probability(wins: int, samples: int, prior_wins: int = 10, prior_samples: int = 20) -> float:
    return (wins + prior_wins) / (samples + prior_samples)


def _discussion(symbol: str, state: dict, probability, samples) -> dict:
    score = state["trend_score"]
    alert = state.get("alert_label")
    direction = state.get("alert_direction") or state.get("direction")
    if alert:
        headline = f"{alert}: {symbol.replace('USDT', '')} is transitioning toward {direction} continuation"
    elif score is None:
        headline = "Trend state unavailable"
    else:
        headline = f"{state['trend_level']} trend structure with no fresh flip alert"
    if score is None:
        body = "A complete 365-day VWAP history is required before the multi-timeframe trend state can be evaluated."
    else:
        delta = state["score_change_5d"]
        movement = "strengthened" if delta > 0 else "weakened" if delta < 0 else "held steady"
        structural = "bullish" if score > 0 else "bearish" if score < 0 else "mixed"
        fast_gap = state.get("fast_gap_pct")
        gap_text = f"The 7D VWAP is {abs(fast_gap):.2f}% {'above' if fast_gap >= 0 else 'below'} the 30D VWAP." if fast_gap is not None else "The fast VWAP gap is unavailable."
        alert_text = (
            f"A {alert.lower()} fired because the fast structure moved materially toward the {direction} side over five days."
            if alert else
            "No alert fired because the five-day score transition and fast 7D/30D configuration did not meet the flip threshold together."
        )
        probability_text = (
            f"Historically, comparable states continued in the indicated direction over 20 days {probability*100:.1f}% of the time across {samples} observations."
            if probability is not None and samples else
            "There is not yet a sufficiently populated historical probability bucket for this state."
        )
        body = f"The four comparison layers produce a trend score of {score:+d}/4, a {structural} structure that has {movement} by {abs(delta)} points over five days. {gap_text} {alert_text} {probability_text} This is a state alert, not an entry or exit instruction."
    return {"headline": headline, "body": body}


def enrich_live_signals(rows: list[dict], histories: dict[str, list[dict]], model: dict) -> tuple[list[dict], list[dict]]:
    groups = model.get("groups", {})
    alerts = []
    for row in rows:
        state = classify_series(histories.get(row["symbol"], []))
        base = row["symbol"].removesuffix("USDT")
        if base in NON_DIRECTIONAL_BASES or (row.get("liquidity_30d") is not None and row["liquidity_30d"] < 5_000_000):
            state.update({"alert_type": None, "alert_label": None, "alert_direction": None})
        key = f"alert:{state['alert_type']}" if state.get("alert_type") else f"score:{state['trend_score']}"
        group = groups.get(key, {})
        probability = group.get("probability")
        samples = group.get("samples", 0)
        row.update(state)
        row["continuation_probability"] = probability
        row["probability_samples"] = samples
        row["probability_horizon_days"] = model.get("horizon_days", 20)
        row["signal_discussion"] = _discussion(row["symbol"], state, probability, samples)
        if state.get("alert_type"):
            alert = {
                "id": f"{row['symbol']}:{row.get('as_of')}:{state['alert_type']}",
                "symbol": row["symbol"],
                "as_of": row.get("as_of"),
                "type": state["alert_type"],
                "label": state["alert_label"],
                "direction": state["alert_direction"],
                "trend_score": state["trend_score"],
                "probability": probability,
                "samples": samples,
            }
            alerts.append(alert)
    alerts.sort(key=lambda item: (item["probability"] is not None, item["probability"] or 0, item["samples"]), reverse=True)
    return rows, alerts
