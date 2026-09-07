import json
import math
import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timezone

from scanner import (
    build_snapshot,
    chunked,
    compute_multi_series,
    compute_series,
    enrich_market_caps,
    fetch_resilient,
    normalize_binance_klines,
    scale_compatible,
    time_windows,
)


class RollingVwapTests(unittest.TestCase):
    def test_rolling_vwap_uses_quote_divided_by_base_volume(self):
        rows = [
            {"time": f"2026-01-{day:02d}", "close_price": str(10 + day), "coin_volume": "2", "dollar_volume": str(20 + day * 2)}
            for day in range(1, 5)
        ]
        series = compute_series(rows, window=3)
        self.assertIsNone(series[1]["vwap"])
        self.assertAlmostEqual(series[2]["vwap"], 12.0)
        self.assertAlmostEqual(series[3]["vwap"], 13.0)

    def test_zero_volume_window_is_not_ranked(self):
        rows = [
            {"time": f"2026-01-{day:02d}", "close_price": "10", "coin_volume": "0", "dollar_volume": "0"}
            for day in range(1, 4)
        ]
        series = compute_series(rows, window=3)
        self.assertIsNone(series[-1]["vwap"])

    def test_snapshot_classifies_above_and_below_and_sorts_by_distance(self):
        histories = {
            "AAAUSDT": [{"time": "t", "close": 110.0, "vwap": 100.0}],
            "BBBUSDT": [{"time": "t", "close": 80.0, "vwap": 100.0}],
        }
        snapshot = build_snapshot(histories)
        self.assertEqual([row["symbol"] for row in snapshot], ["AAAUSDT", "BBBUSDT"])
        self.assertEqual(snapshot[0]["status"], "above")
        self.assertEqual(snapshot[1]["status"], "below")
        self.assertAlmostEqual(snapshot[0]["distance_pct"], 10.0)
        self.assertAlmostEqual(snapshot[1]["distance_pct"], -20.0)

    def test_snapshot_preserves_insufficient_history(self):
        histories = {"NEWUSDT": [{"time": "t", "close": 2.0, "vwap": None}]}
        row = build_snapshot(histories)[0]
        self.assertEqual(row["status"], "insufficient")
        self.assertIsNone(row["distance_pct"])

    def test_chunked_respects_requested_batch_size(self):
        self.assertEqual(list(chunked(list(range(7)), 3)), [[0, 1, 2], [3, 4, 5], [6]])

    def test_resilient_fetch_isolates_an_unsupported_symbol(self):
        def fake_fetch(symbols):
            if "BADUSDT" in symbols:
                raise RuntimeError("invalid products")
            return [{"product": symbol} for symbol in symbols]
        rows, rejected = fetch_resilient(["AAAUSDT", "BADUSDT", "CCCUSDT"], fake_fetch)
        self.assertEqual([row["product"] for row in rows], ["AAAUSDT", "CCCUSDT"])
        self.assertEqual(rejected, ["BADUSDT"])

    def test_time_windows_never_exceed_ninety_days(self):
        begin = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2025, 12, 31, tzinfo=timezone.utc)
        windows = list(time_windows(begin, end))
        self.assertGreater(len(windows), 1)
        self.assertTrue(all((stop - start).days <= 89 for start, stop in windows))
        self.assertEqual(windows[0][0], begin)
        self.assertEqual(windows[-1][1], end)

    def test_binance_kline_normalization_uses_base_and_quote_volume(self):
        raw = [[1704067200000, "9", "12", "8", "11", "100", 0, "1050"]]
        rows = normalize_binance_klines("AAAUSDT", raw)
        self.assertEqual(rows, [{"product": "AAAUSDT", "time": "1704067200000", "close_price": "11", "coin_volume": "100", "dollar_volume": "1050"}])

    def test_scale_guard_rejects_provider_unit_mismatch(self):
        binance = [{"time": "1", "close_price": "0.00001"}]
        velo = [{"time": "1", "close_price": "0.01"}]
        self.assertFalse(scale_compatible(binance, velo))
        self.assertTrue(scale_compatible(binance, [{"time": "1", "close_price": "0.000011"}]))

    def test_multi_series_emits_each_requested_rolling_window(self):
        rows = [
            {"time": str(day), "close_price": str(day), "coin_volume": "1", "dollar_volume": str(day)}
            for day in range(1, 11)
        ]
        latest = compute_multi_series(rows, windows=(3, 7))[-1]
        self.assertAlmostEqual(latest["vwap_3"], 9.0)
        self.assertAlmostEqual(latest["vwap_7"], 7.0)

    def test_snapshot_contains_metrics_for_every_window(self):
        histories = {
            "AAAUSDT": [{"time": "t", "close": 12.0, "vwap_7": 10.0, "vwap_30": None}]
        }
        row = build_snapshot(histories, windows=(7, 30))[0]
        self.assertEqual(row["metrics"]["7"]["status"], "above")
        self.assertAlmostEqual(row["metrics"]["7"]["distance_pct"], 20.0)
        self.assertEqual(row["metrics"]["30"]["status"], "insufficient")

    def test_market_caps_follow_velo_canonical_coin_mapping(self):
        snapshot = [{"symbol": "PEPEUSDT"}, {"symbol": "UNKNOWNUSDT"}]
        mapped = enrich_market_caps(
            snapshot,
            {"PEPEUSDT": "1000PEPE"},
            [{"coin": "1000PEPE", "circ_dollars": "1500000000", "fdv_dollars": "1600000000"}],
        )
        self.assertEqual(mapped[0]["market_cap"], 1_500_000_000.0)
        self.assertEqual(mapped[0]["fdv"], 1_600_000_000.0)
        self.assertIsNone(mapped[1]["market_cap"])


if __name__ == "__main__":
    unittest.main()
