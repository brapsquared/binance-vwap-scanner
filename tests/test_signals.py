import unittest

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

    def test_empirical_probability_uses_beta_smoothing(self):
        result = empirical_probability(wins=8, samples=10, prior_wins=10, prior_samples=20)
        self.assertAlmostEqual(result, 18 / 30)

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


if __name__ == "__main__":
    unittest.main()
