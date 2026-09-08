from __future__ import annotations

from datetime import date


LIFECYCLE_ORDER = {
    "Confirmed": 0,
    "Watching": 1,
    "Weakening": 2,
    "Persisting": 3,
    "Invalidated": 4,
}


def _probabilities(values):
    return [float(value) for value in values if value is not None]


def _first_seen(alerts: list[dict], direction: str) -> str:
    return min(alert["as_of"] for alert in alerts if alert.get("direction") == direction)


def _moves_toward_zero(row: dict) -> bool:
    change = row.get("score_change_5d") or 0
    return (row.get("direction") == "long" and change < 0) or (
        row.get("direction") == "short" and change > 0
    )


def derive_lifecycle(row: dict, alerts: list[dict], as_of: str | None = None) -> dict:
    """Derive the current advisory lifecycle state for one scanner row."""
    current_date = date.fromisoformat(as_of or row["as_of"])
    alert_type = row.get("alert_type") or ""
    current_probability = row.get("continuation_probability")
    relevant = sorted(
        (
            alert
            for alert in alerts
            if alert.get("symbol") == row.get("symbol")
            and 0 <= (current_date - date.fromisoformat(alert["as_of"])).days <= 45
        ),
        key=lambda alert: (alert["as_of"], alert["id"]),
    )
    latest = relevant[-1] if relevant else None

    if alert_type.endswith("_watch"):
        lifecycle = "Watching"
        first_seen = row["as_of"]
    elif alert_type.endswith("_confirmed"):
        lifecycle = "Confirmed"
        first_seen = row["as_of"]
    elif latest and (
        row.get("direction") is None or latest.get("direction") != row.get("direction")
    ):
        lifecycle = "Invalidated"
        first_seen = _first_seen(relevant, latest["direction"])
    elif (
        latest
        and latest.get("direction") == row.get("direction")
        and _moves_toward_zero(row)
    ):
        lifecycle = "Weakening"
        first_seen = _first_seen(relevant, row["direction"])
    elif (
        latest
        and latest.get("direction") == row.get("direction")
        and abs(row.get("trend_score") or 0) >= 2
    ):
        lifecycle = "Persisting"
        first_seen = _first_seen(relevant, row["direction"])
    else:
        lifecycle = "Inactive"
        first_seen = None

    if lifecycle == "Inactive":
        return {
            "lifecycle": lifecycle,
            "first_seen": None,
            "age_days": None,
            "highest_probability": None,
            "event_id": None,
            "is_new": False,
        }

    episode_direction = (
        latest.get("direction")
        if lifecycle == "Invalidated" and latest
        else row.get("alert_direction") or row.get("direction")
    )
    probabilities = _probabilities(
        [current_probability]
        + [alert.get("probability") for alert in relevant if alert.get("direction") == episode_direction]
    )
    if alert_type:
        matching_events = [
            alert
            for alert in relevant
            if alert.get("type") == alert_type
            and alert.get("direction") == row.get("alert_direction")
        ]
        exact_events = [alert for alert in matching_events if alert.get("as_of") == row.get("as_of")]
        event = (exact_events or matching_events)[-1] if (exact_events or matching_events) else None
    else:
        event = latest
    return {
        "lifecycle": lifecycle,
        "first_seen": first_seen,
        "age_days": (current_date - date.fromisoformat(first_seen)).days,
        "highest_probability": max(probabilities) if probabilities else None,
        "event_id": event.get("id") if event else row.get("alert_id"),
        "is_new": not bool(event.get("viewed")) if event else True,
    }


def build_action_queue(
    rows: list[dict],
    alerts: list[dict],
    as_of: str | None = None,
    min_probability: float = 0.0,
    min_samples: int = 0,
    market_type: str = "all",
    new_only: bool = False,
) -> list[dict]:
    queue = []
    for row in rows:
        if market_type != "all" and row.get("market_type") != market_type:
            continue
        probability = row.get("continuation_probability")
        if probability is None:
            if min_probability > 0:
                continue
        elif probability < min_probability:
            continue
        if (row.get("probability_samples") or 0) < min_samples:
            continue
        item = {**row, **derive_lifecycle(row, alerts, as_of=as_of)}
        if item["lifecycle"] != "Inactive" and (not new_only or item["is_new"]):
            queue.append(item)
    queue.sort(
        key=lambda item: (
            not item["is_new"],
            LIFECYCLE_ORDER[item["lifecycle"]],
            -(item.get("continuation_probability") or 0),
            -(item.get("probability_samples") or 0),
            item["symbol"],
        )
    )
    return queue
