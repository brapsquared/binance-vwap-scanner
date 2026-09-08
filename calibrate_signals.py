from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from signals import NON_DIRECTIONAL_BASES, empirical_probability

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "spikes" / "001-mtf-vwap-study" / "data"
OUTPUT = ROOT / "models" / "trend_probability.json"
WINDOWS = (7, 30, 90, 365)
HORIZON = 20
MIN_LIQUIDITY = 5_000_000
MIN_PROBABILITY_SAMPLES = 30


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for window in WINDOWS:
        base = out.base_volume.rolling(window, min_periods=window).sum()
        quote = out.quote_volume.rolling(window, min_periods=window).sum()
        out[f"vwap_{window}"] = quote / base.replace(0, np.nan)
    out["liquidity"] = out.quote_volume.shift(1).rolling(30, min_periods=20).median()
    out["score"] = (
        np.sign(out.close - out.vwap_7)
        + np.sign(out.vwap_7 - out.vwap_30)
        + np.sign(out.vwap_30 - out.vwap_90)
        + np.sign(out.vwap_90 - out.vwap_365)
    )
    out["prior_score"] = out.score.shift(5)
    out["previous_score"] = out.score.shift(1)
    out["score_delta"] = out.score - out.prior_score
    out["fast_gap_pct"] = (out.vwap_7 / out.vwap_30 - 1) * 100
    out["alert_type"] = None
    bull_confirmed = (out.previous_score <= 0) & (out.score >= 2)
    bear_confirmed = (out.previous_score >= 0) & (out.score <= -2)
    bull_watch = (out.score <= 1) & (out.score_delta >= 2) & (out.close > out.vwap_7) & (out.vwap_7 <= out.vwap_30) & (out.fast_gap_pct.abs() <= 5)
    bear_watch = (out.score >= -1) & (out.score_delta <= -2) & (out.close < out.vwap_7) & (out.vwap_7 >= out.vwap_30) & (out.fast_gap_pct.abs() <= 5)
    out.loc[bull_watch, "alert_type"] = "bullish_flip_watch"
    out.loc[bear_watch, "alert_type"] = "bearish_flip_watch"
    out.loc[bull_confirmed, "alert_type"] = "bullish_flip_confirmed"
    out.loc[bear_confirmed, "alert_type"] = "bearish_flip_confirmed"
    out["direction"] = np.where(out.alert_type.str.startswith("bullish", na=False), 1, np.where(out.alert_type.str.startswith("bearish", na=False), -1, np.sign(out.score)))
    out["forward_return"] = out.close.shift(-HORIZON) / out.close - 1
    out["continued"] = out.direction * out.forward_return > 0
    return out


def add_observation(store, key, split, win):
    store[(key, split)]["samples"] += 1
    store[(key, split)]["wins"] += int(bool(win))


def main():
    paths = sorted(DATA.glob("*.csv.gz"))
    if not paths:
        raise SystemExit(f"No cached study data found in {DATA}")
    latest = max(pd.read_csv(path, usecols=["date"], parse_dates=["date"]).date.max() for path in paths)
    latest = pd.Timestamp(latest)
    if latest.tzinfo is None:
        latest = latest.tz_localize("UTC")
    cutoff = latest - pd.Timedelta(days=365)
    store = defaultdict(lambda: {"samples": 0, "wins": 0})
    test_records = []
    for count, path in enumerate(paths, start=1):
        if path.name.removesuffix(".csv.gz").removesuffix("USDT") in NON_DIRECTIONAL_BASES:
            continue
        frame = pd.read_csv(path, parse_dates=["date"])
        frame["date"] = pd.to_datetime(frame.date, utc=True)
        work = prepare(frame)
        eligible = work.vwap_365.notna() & (work.liquidity >= MIN_LIQUIDITY) & work.forward_return.notna() & (work.direction != 0)
        last_alert = {}
        for index in np.flatnonzero(eligible.to_numpy()):
            row = work.iloc[index]
            split = "test" if row.date >= cutoff else "train"
            score_key = f"score:{int(row.score)}"
            # Score probabilities use non-overlapping observations.
            if index % HORIZON == 0:
                add_observation(store, score_key, split, row.continued)
                if split == "test":
                    test_records.append({"key": score_key, "continued": bool(row.continued)})
            if row.alert_type:
                prior = last_alert.get(row.alert_type, -999)
                if index - prior >= 10:
                    last_alert[row.alert_type] = index
                    alert_key = f"alert:{row.alert_type}"
                    add_observation(store, alert_key, split, row.continued)
                    if split == "test":
                        test_records.append({"key": alert_key, "continued": bool(row.continued)})
        if count % 100 == 0:
            print(f"calibration {count}/{len(paths)}", flush=True)

    groups = {}
    for key in sorted({key for key, _ in store}):
        all_samples = store[(key, "train")]["samples"] + store[(key, "test")]["samples"]
        all_wins = store[(key, "train")]["wins"] + store[(key, "test")]["wins"]
        groups[key] = {
            "probability": round(empirical_probability(all_wins, all_samples), 6),
            "samples": all_samples,
            "wins": all_wins,
            "train_samples": store[(key, "train")]["samples"],
            "test_samples": store[(key, "test")]["samples"],
        }

    train_probabilities = {}
    for key in groups:
        values = store[(key, "train")]
        train_probabilities[key] = empirical_probability(values["wins"], values["samples"])
    evaluated = [record for record in test_records if store[(record["key"], "train")]["samples"] >= MIN_PROBABILITY_SAMPLES]
    if evaluated:
        probs = np.array([train_probabilities[record["key"]] for record in evaluated])
        actual = np.array([record["continued"] for record in evaluated], dtype=float)
        brier = float(np.mean((probs - actual) ** 2))
        accuracy = float(np.mean((probs >= .5) == actual))
    else:
        brier = accuracy = None

    payload = {
        "version": "mtf-vwap-state-v1",
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "horizon_days": HORIZON,
        "minimum_samples": MIN_PROBABILITY_SAMPLES,
        "availability_definition": f"Buckets with fewer than {MIN_PROBABILITY_SAMPLES} observations are unavailable",
        "definition": "Probability that the close-to-close 20-day return continues in the indicated trend or flip direction",
        "smoothing": "Beta prior: 10 wins / 20 samples",
        "sampling": "20-day non-overlapping score samples; 10-day cooldown for flip alerts",
        "universe": "Current-survivor Binance USDT spot symbols passing $5M trailing median daily quote volume",
        "test_cutoff": cutoff.isoformat(),
        "oos": {"records": len(evaluated), "brier": brier, "accuracy": accuracy},
        "groups": groups,
        "caveats": [
            "Empirical association, not a guaranteed probability",
            "Current-symbol survivorship bias",
            "Correlated cross-sectional observations",
            "Spot history does not model perpetual funding or short execution",
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"groups": groups, "oos": payload["oos"]}, indent=2))


if __name__ == "__main__":
    main()
