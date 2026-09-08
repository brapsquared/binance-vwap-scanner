import json
import unittest
from pathlib import Path

from signals import classify_series, empirical_probability, enrich_live_signals


class TrendSignalTests(unittest.TestCase):
    def point(self, close, v7, v30, v90, v365, time="2026-01-01"):
        return {"time": time, "close": close, "vwap_7": v7, "vwap_30": v30, "vwap_90": v90, "vwap_365": v365}

    def test_full_bull_stack_is_strong_up_level_four(self):
        series = [self.point(110, 105, 100, 95, 90)] * 6
        state = classify_series(series)
        self.assertEqual(state["trend_score"], 4)
        self.assertEqual(state["trend_level"], "Strong up")
        self.assertEqual(state["direction"], "long")

    def test_full_bear_stack_is_strong_down_level_minus_four(self):
        series = [self.point(80, 85, 90, 95, 100)] * 6
        state = classify_series(series)
        self.assertEqual(state["trend_score"], -4)
        self.assertEqual(state["trend_level"], "Strong down")
        self.assertEqual(state["direction"], "short")

    def test_crossing_from_negative_to_positive_confirms_bullish_flip(self):
        series = [self.point(94, 95, 96, 97, 98, f"2026-01-0{i+1}") for i in range(5)]
        series.append(self.point(101, 100, 99, 98, 97, "2026-01-06"))
        state = classify_series(series)
        self.assertEqual(state["alert_type"], "bullish_flip_confirmed")
        self.assertEqual(state["alert_direction"], "long")

    def test_tight_fast_gap_and_improving_score_creates_bullish_watch(self):
        series = [self.point(94, 95, 100, 105, 110, f"2026-01-0{i+1}") for i in range(5)]
        series.append(self.point(99, 98, 100, 105, 110, "2026-01-06"))
        state = classify_series(series)
        self.assertEqual(state["alert_type"], "bullish_flip_watch")

    def test_state_map_exposes_all_four_ordered_comparisons(self):
        state = classify_series([self.point(110, 105, 100, 101, 90)])
        comparisons = state["comparison_map"]
        self.assertEqual(
            [(item["left"], item["right"], item["relation"], item["score"]) for item in comparisons],
            [
                ("Close", "7D", "above", 1),
                ("7D", "30D", "above", 1),
                ("30D", "90D", "below", -1),
                ("90D", "365D", "above", 1),
            ],
        )
        self.assertAlmostEqual(comparisons[0]["distance_pct"], (110 / 105 - 1) * 100)

    def test_incomplete_history_still_exposes_partial_four_comparison_map(self):
        state = classify_series([self.point(12, 10, None, None, None)])
        self.assertIsNone(state["trend_score"])
        self.assertEqual(len(state["comparison_map"]), 4)
        self.assertEqual(state["comparison_map"][0]["relation"], "above")
        self.assertEqual(state["comparison_map"][1]["relation"], "unavailable")
        self.assertAlmostEqual(state["distance_to_7d_cross_pct"], (10 / 12 - 1) * 100)
        self.assertIsNone(state["distance_to_30d_cross_pct"])

    def test_bullish_watch_reports_signed_fast_cross_distance_and_next_threshold(self):
        series = [self.point(94, 95, 100, 105, 110, f"2026-01-0{i+1}") for i in range(5)]
        series.append(self.point(99, 98, 100, 105, 110, "2026-01-06"))
        state = classify_series(series)
        self.assertAlmostEqual(state["distance_to_7d_cross_pct"], (98 / 99 - 1) * 100)
        self.assertAlmostEqual(state["distance_to_30d_cross_pct"], (100 / 98 - 1) * 100)
        self.assertAlmostEqual(state["distance_to_confirmation_pct"], (100 / 98 - 1) * 100)
        self.assertEqual(state["next_structural_threshold"]["key"], "7d_to_30d")
        self.assertEqual(state["next_structural_threshold"]["direction"], "long")
        self.assertIn("7D", state["next_structural_explanation"])
        self.assertIn("rise", state["next_structural_explanation"])
        self.assertAlmostEqual(state["confirmation"]["gap_7d_30d_pct"], (98 / 100 - 1) * 100)
        self.assertEqual(state["confirmation"]["next_threshold"], "7D above 30D")
        self.assertEqual(state["confirmation"]["explanation"], state["next_structural_explanation"])
        self.assertEqual(state["lifecycle_first_seen"], "2026-01-06")
        self.assertEqual(state["lifecycle_days"], 0)

    def test_bearish_watch_cross_distance_is_negative_for_required_fall(self):
        series = [self.point(110, 105, 100, 95, 90, f"2026-01-0{i+1}") for i in range(5)]
        series.append(self.point(101, 102, 100, 95, 90, "2026-01-06"))
        state = classify_series(series)
        self.assertEqual(state["alert_type"], "bearish_flip_watch")
        self.assertAlmostEqual(state["distance_to_confirmation_pct"], (100 / 102 - 1) * 100)
        self.assertEqual(state["next_structural_threshold"]["direction"], "short")
        self.assertIn("fall", state["next_structural_explanation"])

    def test_lifecycle_inputs_include_contiguous_score_and_direction_age(self):
        series = [
            self.point(110, 105, 100, 110, 90, "2026-01-01"),
            self.point(111, 106, 101, 111, 91, "2026-01-02"),
            self.point(112, 107, 102, 97, 92, "2026-01-03"),
            self.point(113, 108, 103, 98, 93, "2026-01-04"),
            self.point(114, 109, 104, 99, 94, "2026-01-05"),
            self.point(115, 110, 105, 100, 95, "2026-01-06"),
        ]
        state = classify_series(series)
        self.assertEqual(state["score_first_seen_as_of"], "2026-01-03")
        self.assertEqual(state["score_age_days"], 4)
        self.assertEqual(state["score_age_candles"], 4)
        self.assertEqual(state["direction_first_seen_as_of"], "2026-01-01")
        self.assertEqual(state["direction_age_days"], 6)
        self.assertEqual(state["lifecycle_inputs"]["previous_score"], 4)
        self.assertEqual(state["lifecycle_inputs"]["score_5d_ago"], 2)
        self.assertEqual(state["lifecycle_inputs"]["score_change_5d"], 2)
        self.assertTrue(state["lifecycle_inputs"]["strong_direction"])
        self.assertFalse(state["lifecycle_inputs"]["score_moved_toward_zero"])

    def test_empirical_probability_uses_beta_smoothing(self):
        result = empirical_probability(wins=8, samples=10, prior_wins=10, prior_samples=20)
        self.assertAlmostEqual(result, 18 / 30)

    def test_bundled_probability_model_declares_availability_threshold(self):
        model_path = Path(__file__).resolve().parents[1] / "models" / "trend_probability.json"
        model = json.loads(model_path.read_text(encoding="utf-8"))
        self.assertEqual(model["minimum_samples"], 30)
        self.assertIn("unavailable", model["availability_definition"].lower())

    def test_live_enrichment_uses_alert_probability_and_sample_count(self):
        rows = [{"symbol": "AAAUSDT"}]
        histories = {"AAAUSDT": [self.point(94, 95, 100, 105, 110)] * 5 + [self.point(99, 98, 100, 105, 110)]}
        model = {"groups": {"alert:bullish_flip_watch": {"probability": 0.64, "samples": 120}}}
        enriched, alerts = enrich_live_signals(rows, histories, model)
        self.assertEqual(enriched[0]["continuation_probability"], 0.64)
        self.assertEqual(enriched[0]["probability_samples"], 120)
        self.assertEqual(len(alerts), 1)
        self.assertIn("Bullish flip watch", enriched[0]["signal_discussion"]["headline"])
        self.assertIn("7D", enriched[0]["signal_discussion"]["body"])

    def test_discussion_uses_the_models_declared_probability_horizon(self):
        rows = [{"symbol": "AAAUSDT"}]
        histories = {"AAAUSDT": [self.point(94, 95, 100, 105, 110)] * 5 + [self.point(99, 98, 100, 105, 110)]}
        model = {
            "horizon_days": 10,
            "groups": {"alert:bullish_flip_watch": {"probability": 0.64, "samples": 120}},
        }
        enriched, _ = enrich_live_signals(rows, histories, model)
        self.assertIn("over 10 days", enriched[0]["signal_discussion"]["body"])

    def test_undersampled_probability_is_explicitly_unavailable(self):
        rows = [{"symbol": "AAAUSDT", "market_type": "spot"}]
        histories = {"AAAUSDT": [self.point(110, 100, 105, 95, 100)]}
        model = {
            "minimum_samples": 30,
            "horizon_days": 20,
            "definition": "Directional continuation association",
            "groups": {"score:0": {"probability": 0.51, "samples": 29, "wins": 15}},
        }
        enriched, _ = enrich_live_signals(rows, histories, model)
        row = enriched[0]
        self.assertIsNone(row["continuation_probability"])
        self.assertEqual(row["probability_samples"], 29)
        self.assertFalse(row["probability_available"])
        self.assertEqual(row["probability_group"], "score:0")
        self.assertEqual(row["probability_min_samples"], 30)
        self.assertIn("fewer than 30", row["probability_unavailable_reason"])
        self.assertEqual(row["probability_definition"], "Directional continuation association")

    def test_perp_row_carries_market_metadata_and_transfer_warning(self):
        rows = [{
            "symbol": "AAAUSDT", "market_type": "perp", "market_label": "Perp-only",
            "instrument_type": "perpetual", "venue": "binance-usdm", "is_perp_only": True,
        }]
        histories = {"AAAUSDT": [self.point(94, 95, 100, 105, 110)] * 5 + [self.point(99, 98, 100, 105, 110)]}
        model = {"groups": {"alert:bullish_flip_watch": {"probability": 0.64, "samples": 120}}}
        enriched, _ = enrich_live_signals(rows, histories, model)
        row = enriched[0]
        self.assertEqual(row["market_metadata"]["market_type"], "perp")
        self.assertEqual(row["market_metadata"]["venue"], "binance-usdm")
        self.assertTrue(row["market_metadata"]["is_perp_only"])
        self.assertEqual(row["probability_model_scope"], "spot-trained transfer")
        self.assertTrue(row["probability_transfer_lower_confidence"])
        self.assertIn("lower confidence", row["probability_scope_note"])

    def test_suppressed_alert_is_also_removed_from_lifecycle_inputs(self):
        rows = [{"symbol": "AAAUSDT", "liquidity_30d": 1_000_000}]
        histories = {"AAAUSDT": [self.point(94, 95, 100, 105, 110)] * 5 + [self.point(99, 98, 100, 105, 110)]}
        enriched, alerts = enrich_live_signals(rows, histories, {"groups": {}})
        row = enriched[0]
        self.assertIsNone(row["alert_type"])
        self.assertEqual(row["lifecycle_status_hint"], "Inactive")
        self.assertIsNone(row["lifecycle_inputs"]["current_alert_type"])
        self.assertEqual(alerts, [])


if __name__ == "__main__":
    unittest.main()
