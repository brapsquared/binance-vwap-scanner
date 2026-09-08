from __future__ import annotations

import argparse
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Callable

from advisory_delivery import DeliveryLedger
from scanner import refresh

ROOT = Path(__file__).resolve().parent


def rank_alerts(alerts: list[dict]) -> list[dict]:
    """Return alerts in descending empirical-probability order."""
    return sorted(
        alerts,
        key=lambda alert: (
            alert.get("probability") is None,
            -(alert.get("probability") or 0),
            -int(alert.get("samples") or 0),
            alert.get("symbol", ""),
        ),
    )


def format_digest(
    alerts: list[dict],
    horizon_days: int | None,
    market_types: dict[str, str],
    event_id: str | None = None,
) -> str:
    """Format newly deliverable alerts as a concise advisory digest."""
    ranked = rank_alerts(alerts)
    lines = [f"VWAP advisory digest — {len(ranked)} new alerts"]
    if event_id is not None:
        lines.append(f"Delivery event ID: {event_id}")
    horizon = f"{horizon_days}D" if horizon_days is not None else "unknown horizon"
    for position, alert in enumerate(ranked, start=1):
        probability = alert.get("probability")
        probability_text = f"{probability:.1%}" if probability is not None else "unavailable"
        symbol = alert["symbol"]
        market_type = market_types.get(symbol)
        if market_type == "perp":
            scope = "spot-trained transfer to perp-only; lower confidence"
        elif market_type == "spot":
            scope = "spot-trained"
        else:
            scope = "unknown/unclassified market; calibration scope unknown"
        lines.append(
            f"{position}. {symbol} @ {alert['as_of']} | {alert['label']} | {alert['direction']} | "
            f"{probability_text} (n={int(alert.get('samples') or 0)}; "
            f"{horizon} directional continuation; {scope})"
        )
    lines.append(
        "Advisory only — empirical association, not trade success probability or a trading instruction."
    )
    return "\n".join(lines)


def run_daily(
    output_dir: Path,
    refresh_fn: Callable[[Path], dict] = refresh,
    emit: Callable[[str], None] = print,
) -> str | None:
    """Refresh scanner data and emit one digest for previously unseen alert IDs."""
    output_dir = Path(output_dir)
    with redirect_stdout(sys.stderr):
        payload = refresh_fn(output_dir)

    ledger = DeliveryLedger(output_dir / "advisory-deliveries.db")
    event_id, alerts = ledger.claim(payload.get("alerts", []))
    if not alerts:
        return None

    market_types = {
        row["symbol"]: row.get("market_type")
        for row in payload.get("rows", [])
        if row.get("symbol")
    }
    digest = format_digest(
        alerts,
        horizon_days=payload.get("meta", {}).get("signal_probability_horizon_days"),
        market_types=market_types,
        event_id=event_id,
    )
    try:
        emit(digest)
    except BaseException:
        ledger.release(event_id)
        raise
    ledger.acknowledge(event_id)
    return event_id


def main(
    argv: list[str] | None = None,
    run_fn: Callable[[Path], object] = run_daily,
) -> int:
    parser = argparse.ArgumentParser(description="Refresh the VWAP scanner and emit new advisory alerts")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data",
        help="Scanner data and delivery-ledger directory (default: repository data directory)",
    )
    args = parser.parse_args(argv)
    run_fn(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
