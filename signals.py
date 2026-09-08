from __future__ import annotations

import math
from datetime import date
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
    return sum(item["score"] for item in comparison_map(point))


def comparison_map(point: dict) -> list[dict]:
    values = [_finite(point.get(key)) for key in ("close", "vwap_7", "vwap_30", "vwap_90", "vwap_365")]
    labels = ("Close", "7D", "30D", "90D", "365D")
    result = []
    for index, (left, right) in enumerate(zip(values, values[1:])):
        if left is None or right is None:
            relation, score, distance, cross_distance = "unavailable", None, None, None
        else:
            relation = "above" if left > right else "below" if left < right else "equal"
            score = 1 if left > right else -1 if left < right else 0
            distance = (left / right - 1) * 100 if right else None
            cross_distance = (right / left - 1) * 100 if left else None
        result.append({
            "key": f"{labels[index].lower()}_to_{labels[index + 1].lower()}",
            "left": labels[index],
            "right": labels[index + 1],
            "left_value": left,
            "right_value": right,
            "relation": relation,
            "score": score,
            "distance_pct": distance,
            "distance_to_cross_pct": cross_distance,
        })
    return result


def _next_structural_threshold(comparisons: list[dict], direction: str | None, alert_type: str | None) -> tuple[dict | None, str]:
    if direction not in {"long", "short"}:
        return None, "No directional structure is established, so the next confirmation threshold is unavailable."
    desired_score = 1 if direction == "long" else -1
    candidates = [item for item in comparisons if item["score"] != desired_score and item["distance_to_cross_pct"] is not None]
    if not candidates:
        return None, f"All four structural comparisons already align {direction}."
    if alert_type and alert_type.endswith("_watch"):
        threshold = next((item for item in candidates if item["key"] == "7d_to_30d"), None)
    else:
        threshold = None
    threshold = threshold or min(candidates, key=lambda item: abs(item["distance_to_cross_pct"]))
    movement = "rise" if threshold["distance_to_cross_pct"] >= 0 else "fall"
    relation = "above" if direction == "long" else "below"
    explanation = (
        f"{threshold['left']} must {movement} {abs(threshold['distance_to_cross_pct']):.2f}% "
        f"to cross {relation} {threshold['right']} at {threshold['right_value']:g} and add one "
        f"{'bullish' if direction == 'long' else 'bearish'} comparison."
    )
    return {**threshold, "direction": direction, "threshold_value": threshold["right_value"]}, explanation


def _inclusive_age_days(first_seen, as_of) -> int | None:
    try:
        return (date.fromisoformat(str(as_of)[:10]) - date.fromisoformat(str(first_seen)[:10])).days + 1
    except (TypeError, ValueError):
        return None


def _state_age(valid: Sequence[dict], score: int, direction: str | None) -> dict:
    score_start = len(valid) - 1
    while score_start > 0 and point_score(valid[score_start - 1]) == score:
        score_start -= 1
    direction_start = len(valid) - 1
    while direction_start > 0:
        prior_score = point_score(valid[direction_start - 1])
        prior_direction = "long" if prior_score > 0 else "short" if prior_score < 0 else None
        if prior_direction != direction:
            break
        direction_start -= 1
    as_of = valid[-1].get("time")
    score_first_seen = valid[score_start].get("time")
    direction_first_seen = valid[direction_start].get("time")
    return {
        "score_first_seen_as_of": score_first_seen,
        "score_age_days": _inclusive_age_days(score_first_seen, as_of),
        "score_age_candles": len(valid) - score_start,
        "direction_first_seen_as_of": direction_first_seen,
        "direction_age_days": _inclusive_age_days(direction_first_seen, as_of),
        "direction_age_candles": len(valid) - direction_start,
    }


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
        partial_comparisons = comparison_map(series[-1]) if series else []
        close_to_7d = partial_comparisons[0]["distance_to_cross_pct"] if partial_comparisons else None
        fast_cross = partial_comparisons[1]["distance_to_cross_pct"] if partial_comparisons else None
        as_of = series[-1].get("time") if series else None
        fast_gap = partial_comparisons[1]["distance_pct"] if partial_comparisons else None
        confirmation = {
            "available": fast_gap is not None,
            "gap_7d_30d_pct": fast_gap,
            "distance_to_cross_pct": fast_cross,
            "next_threshold": "7D / 30D cross",
            "explanation": "A complete 7D and 30D VWAP history is required." if fast_gap is None else "The complete VWAP stack is still unavailable.",
        }
        return {
            "trend_score": None, "trend_level": "Unavailable", "score_change_5d": None,
            "previous_trend_score": None, "trend_score_5d_ago": None,
            "direction": None, "alert_type": None, "alert_label": None, "alert_direction": None,
            "comparison_map": partial_comparisons,
            "distance_to_7d_cross_pct": close_to_7d, "distance_to_30d_cross_pct": fast_cross,
            "distance_to_confirmation_pct": None, "next_structural_threshold": None,
            "next_structural_explanation": "A complete VWAP stack is required before a structural threshold can be calculated.",
            "confirmation": confirmation, "confirmation_distance": confirmation,
            "score_first_seen_as_of": None, "score_age_days": None, "score_age_candles": 0,
            "direction_first_seen_as_of": None, "direction_age_days": None, "direction_age_candles": 0,
            "lifecycle_status_hint": "Inactive", "lifecycle_first_seen": None, "lifecycle_days": None,
            "lifecycle_inputs": {
                "as_of": as_of, "current_alert_type": None, "current_alert_direction": None,
                "current_score": None, "previous_score": None, "score_5d_ago": None,
                "current_direction": None, "score_change_5d": None,
                "strong_direction": False, "score_moved_toward_zero": False,
            },
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
    comparisons = comparison_map(current)
    threshold, threshold_explanation = _next_structural_threshold(comparisons, alert_direction or direction, alert_type)
    close_to_7d = comparisons[0]["distance_to_cross_pct"]
    fast_cross = comparisons[1]["distance_to_cross_pct"]
    if alert_type and alert_type.endswith("_confirmed"):
        confirmation_distance = 0.0
    elif alert_type and alert_type.endswith("_watch"):
        confirmation_distance = fast_cross
    else:
        confirmation_distance = threshold["distance_to_cross_pct"] if threshold else None
    if threshold:
        relation = "above" if threshold["direction"] == "long" else "below"
        next_threshold = f"{threshold['left']} {relation} {threshold['right']}"
    elif alert_type and alert_type.endswith("_confirmed"):
        next_threshold = "Current structural transition confirmed"
    else:
        next_threshold = "7D / 30D cross"
    confirmation = {
        "available": fast_gap_pct is not None,
        "gap_7d_30d_pct": fast_gap_pct,
        "distance_to_cross_pct": fast_cross,
        "next_threshold": next_threshold,
        "explanation": threshold_explanation,
    }
    ages = _state_age(valid, score, direction)
    lifecycle_status_hint = "Watching" if alert_type and alert_type.endswith("_watch") else "Confirmed" if alert_type and alert_type.endswith("_confirmed") else "Inactive"
    lifecycle_first_seen = current.get("time") if alert_type else None
    lifecycle_inputs = {
        "as_of": current.get("time"),
        "current_alert_type": alert_type,
        "current_alert_direction": alert_direction,
        "current_score": score,
        "previous_score": previous,
        "score_5d_ago": prior,
        "current_direction": direction,
        "score_change_5d": delta,
        "strong_direction": abs(score) >= 2,
        "score_moved_toward_zero": bool(score and delta * score < 0),
        **ages,
    }
    return {
        "trend_score": score,
        "trend_level": trend_level(score),
        "score_change_5d": delta,
        "previous_trend_score": previous,
        "trend_score_5d_ago": prior,
        "direction": direction,
        "fast_gap_pct": fast_gap_pct,
        "alert_type": alert_type,
        "alert_label": ALERT_LABELS.get(alert_type),
        "alert_direction": alert_direction,
        "comparison_map": comparisons,
        "distance_to_7d_cross_pct": close_to_7d,
        "distance_to_30d_cross_pct": fast_cross,
        "distance_to_confirmation_pct": confirmation_distance,
        "next_structural_threshold": threshold,
        "next_structural_explanation": threshold_explanation,
        "confirmation": confirmation,
        "confirmation_distance": confirmation,
        **ages,
        "lifecycle_status_hint": lifecycle_status_hint,
        "lifecycle_first_seen": lifecycle_first_seen,
        "lifecycle_days": 0 if lifecycle_first_seen else None,
        "lifecycle_inputs": lifecycle_inputs,
    }


def empirical_probability(wins: int, samples: int, prior_wins: int = 10, prior_samples: int = 20) -> float:
    return (wins + prior_wins) / (samples + prior_samples)


def _discussion(symbol: str, state: dict, probability, samples, market_type: str = "spot", horizon_days: int = 20) -> dict:
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
            f"Historically, comparable states continued in the indicated direction over {horizon_days} days {probability*100:.1f}% of the time across {samples} observations."
            if probability is not None and samples else
            "There is not yet a sufficiently populated historical probability bucket for this state."
        )
        body = f"The four comparison layers produce a trend score of {score:+d}/4, a {structural} structure that has {movement} by {abs(delta)} points over five days. {gap_text} {alert_text} {probability_text} This is a state alert, not an entry or exit instruction."
    if market_type == "perp":
        body += " This is a Binance USDⓈ-M perpetual-only market; the displayed probability is transferred from the spot-trained calibration and should be treated as lower confidence until a dedicated perps calibration is completed."
    return {"headline": headline, "body": body}


def enrich_live_signals(rows: list[dict], histories: dict[str, list[dict]], model: dict) -> tuple[list[dict], list[dict]]:
    groups = model.get("groups", {})
    minimum_samples = int(model.get("minimum_samples", 30))
    alerts = []
    for row in rows:
        state = classify_series(histories.get(row["symbol"], []))
        base = row["symbol"].removesuffix("USDT")
        if base in NON_DIRECTIONAL_BASES:
            suppression_reason = "Non-directional base asset"
        elif row.get("liquidity_30d") is not None and row["liquidity_30d"] < 5_000_000:
            suppression_reason = "Trailing median daily quote volume is below $5M"
        else:
            suppression_reason = None
        if suppression_reason:
            state.update({"alert_type": None, "alert_label": None, "alert_direction": None})
            state["lifecycle_status_hint"] = "Inactive"
            state["lifecycle_first_seen"] = None
            state["lifecycle_days"] = None
            state["lifecycle_inputs"] = {
                **state["lifecycle_inputs"],
                "current_alert_type": None,
                "current_alert_direction": None,
            }
        key = f"alert:{state['alert_type']}" if state.get("alert_type") else f"score:{state['trend_score']}"
        group = groups.get(key, {})
        raw_probability = group.get("probability")
        samples = group.get("samples", 0)
        probability_available = raw_probability is not None and samples >= minimum_samples
        probability = raw_probability if probability_available else None
        if raw_probability is None:
            unavailable_reason = "No calibrated probability is available for this state."
        elif samples < minimum_samples:
            unavailable_reason = f"Calibration has {samples} samples, fewer than {minimum_samples} required."
        else:
            unavailable_reason = None
        market_type = row.get("market_type", "spot")
        is_perp_transfer = market_type == "perp"
        row.update(state)
        row["signal_suppression_reason"] = suppression_reason
        row["market_metadata"] = {
            "market_type": market_type,
            "market_label": row.get("market_label", "Perp-only" if is_perp_transfer else "Spot"),
            "instrument_type": row.get("instrument_type", "perpetual" if is_perp_transfer else "spot"),
            "venue": row.get("venue", "binance-usdm" if is_perp_transfer else "binance-spot"),
            "is_perp_only": bool(row.get("is_perp_only", is_perp_transfer)),
            "base_asset": row.get("base_asset", row["symbol"].removesuffix("USDT")),
            "quote_asset": "USDT",
        }
        row["continuation_probability"] = probability
        row["continuation_probability_raw"] = raw_probability
        row["probability_samples"] = samples
        row["probability_wins"] = group.get("wins")
        row["probability_train_samples"] = group.get("train_samples")
        row["probability_test_samples"] = group.get("test_samples")
        row["probability_available"] = probability_available
        row["probability_group"] = key
        row["probability_min_samples"] = minimum_samples
        row["probability_unavailable_reason"] = unavailable_reason
        row["probability_horizon_days"] = model.get("horizon_days", 20)
        row["probability_definition"] = model.get("definition", "Empirical 20-day directional continuation association; not trade success probability")
        row["probability_model_scope"] = "spot-trained transfer" if is_perp_transfer else "spot-trained"
        row["probability_model_universe"] = model.get("universe")
        row["probability_transfer_lower_confidence"] = is_perp_transfer
        row["probability_scope_note"] = (
            "Transferred from spot calibration; lower confidence because perpetual funding and execution are not modeled."
            if is_perp_transfer else
            "Calibrated on eligible Binance USDT spot history."
        )
        row["signal_discussion"] = _discussion(
            row["symbol"], state, probability, samples, market_type, row["probability_horizon_days"]
        )
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
