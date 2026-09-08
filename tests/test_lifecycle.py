import unittest

from lifecycle import build_action_queue, derive_lifecycle


class LifecycleTests(unittest.TestCase):
    def prior_alert(self, **overrides):
        alert = {
            "id": "AAAUSDT:2026-01-20:bullish_flip_confirmed",
            "symbol": "AAAUSDT",
            "as_of": "2026-01-20",
            "type": "bullish_flip_confirmed",
            "direction": "long",
            "probability": 0.68,
            "samples": 300,
            "viewed": False,
        }
        alert.update(overrides)
        return alert

    def test_current_watch_is_watching(self):
        row = {
            "symbol": "AAAUSDT",
            "as_of": "2026-02-10",
            "alert_type": "bullish_flip_watch",
            "alert_direction": "long",
            "trend_score": 1,
            "score_change_5d": 2,
            "continuation_probability": 0.64,
        }

        state = derive_lifecycle(row, [], as_of="2026-02-10")

        self.assertEqual(state["lifecycle"], "Watching")
        self.assertEqual(state["first_seen"], "2026-02-10")
        self.assertEqual(state["age_days"], 0)
        self.assertEqual(state["highest_probability"], 0.64)

    def test_current_confirmed_alert_is_confirmed(self):
        row = {
            "symbol": "AAAUSDT",
            "as_of": "2026-02-10",
            "alert_type": "bearish_flip_confirmed",
            "alert_direction": "short",
            "trend_score": -2,
            "continuation_probability": 0.72,
        }

        state = derive_lifecycle(row, [], as_of="2026-02-12")

        self.assertEqual(state["lifecycle"], "Confirmed")
        self.assertEqual(state["first_seen"], "2026-02-10")
        self.assertEqual(state["age_days"], 2)
        self.assertEqual(state["highest_probability"], 0.72)

    def test_recent_same_direction_alert_with_strong_score_is_persisting(self):
        row = {
            "symbol": "AAAUSDT",
            "as_of": "2026-02-10",
            "alert_type": None,
            "direction": "long",
            "trend_score": 3,
            "score_change_5d": 1,
            "continuation_probability": 0.62,
        }

        state = derive_lifecycle(row, [self.prior_alert()], as_of="2026-02-10")

        self.assertEqual(state["lifecycle"], "Persisting")
        self.assertEqual(state["first_seen"], "2026-01-20")
        self.assertEqual(state["age_days"], 21)
        self.assertEqual(state["highest_probability"], 0.68)
        self.assertEqual(state["event_id"], "AAAUSDT:2026-01-20:bullish_flip_confirmed")
        self.assertTrue(state["is_new"])

    def test_recent_same_direction_alert_moving_toward_zero_is_weakening(self):
        row = {
            "symbol": "AAAUSDT",
            "as_of": "2026-02-10",
            "alert_type": None,
            "direction": "long",
            "trend_score": 3,
            "score_change_5d": -1,
            "continuation_probability": 0.61,
        }

        state = derive_lifecycle(row, [self.prior_alert()], as_of="2026-02-10")

        self.assertEqual(state["lifecycle"], "Weakening")
        self.assertEqual(state["first_seen"], "2026-01-20")

    def test_recent_alert_with_neutral_current_score_is_invalidated(self):
        row = {
            "symbol": "AAAUSDT",
            "as_of": "2026-02-10",
            "alert_type": None,
            "direction": None,
            "trend_score": 0,
            "score_change_5d": -2,
            "continuation_probability": 0.51,
        }

        state = derive_lifecycle(row, [self.prior_alert()], as_of="2026-02-10")

        self.assertEqual(state["lifecycle"], "Invalidated")
        self.assertEqual(state["first_seen"], "2026-01-20")
        self.assertEqual(state["highest_probability"], 0.68)

    def test_recent_alert_with_opposite_current_direction_is_invalidated(self):
        row = {
            "symbol": "AAAUSDT",
            "as_of": "2026-02-10",
            "alert_type": None,
            "direction": "short",
            "trend_score": -2,
            "score_change_5d": -2,
            "continuation_probability": 0.67,
        }

        state = derive_lifecycle(row, [self.prior_alert()], as_of="2026-02-10")

        self.assertEqual(state["lifecycle"], "Invalidated")
        self.assertEqual(state["first_seen"], "2026-01-20")

    def test_action_queue_orders_new_then_lifecycle_then_probability_and_samples(self):
        rows = [
            {
                "symbol": "VIEWEDUSDT", "as_of": "2026-02-10", "market_type": "spot",
                "alert_type": "bullish_flip_confirmed", "alert_direction": "long",
                "direction": "long", "trend_score": 2, "score_change_5d": 2,
                "continuation_probability": 0.99, "probability_samples": 500,
            },
            {
                "symbol": "WATCHUSDT", "as_of": "2026-02-10", "market_type": "spot",
                "alert_type": "bullish_flip_watch", "alert_direction": "long",
                "direction": "long", "trend_score": 1, "score_change_5d": 2,
                "continuation_probability": 0.90, "probability_samples": 400,
            },
            {
                "symbol": "CONFIRM2USDT", "as_of": "2026-02-10", "market_type": "perp",
                "alert_type": "bearish_flip_confirmed", "alert_direction": "short",
                "direction": "short", "trend_score": -2, "score_change_5d": -2,
                "continuation_probability": 0.70, "probability_samples": 200,
            },
            {
                "symbol": "CONFIRM1USDT", "as_of": "2026-02-10", "market_type": "spot",
                "alert_type": "bullish_flip_confirmed", "alert_direction": "long",
                "direction": "long", "trend_score": 2, "score_change_5d": 2,
                "continuation_probability": 0.70, "probability_samples": 300,
            },
        ]
        alerts = [
            {
                "id": f"{row['symbol']}:2026-02-10:{row['alert_type']}",
                "symbol": row["symbol"], "as_of": "2026-02-10", "type": row["alert_type"],
                "direction": row["alert_direction"], "probability": row["continuation_probability"],
                "samples": row["probability_samples"], "viewed": row["symbol"] == "VIEWEDUSDT",
            }
            for row in rows
        ]

        queue = build_action_queue(rows, alerts, as_of="2026-02-10")

        self.assertEqual(
            [item["symbol"] for item in queue],
            ["CONFIRM1USDT", "CONFIRM2USDT", "WATCHUSDT", "VIEWEDUSDT"],
        )

    def test_action_queue_applies_probability_sample_market_and_new_filters(self):
        specs = [
            ("SPOTNEWUSDT", "spot", 0.80, 200, False),
            ("PERPNEWUSDT", "perp", 0.90, 300, False),
            ("PERPVIEWUSDT", "perp", 0.95, 500, True),
            ("PERPLOWPUSDT", "perp", 0.60, 500, False),
            ("PERPLOWSUSDT", "perp", 0.90, 50, False),
        ]
        rows = [
            {
                "symbol": symbol, "as_of": "2026-02-10", "market_type": market,
                "alert_type": "bullish_flip_confirmed", "alert_direction": "long",
                "direction": "long", "trend_score": 2, "score_change_5d": 2,
                "continuation_probability": probability, "probability_samples": samples,
            }
            for symbol, market, probability, samples, _ in specs
        ]
        alerts = [
            {
                "id": f"{symbol}:2026-02-10:bullish_flip_confirmed", "symbol": symbol,
                "as_of": "2026-02-10", "type": "bullish_flip_confirmed", "direction": "long",
                "probability": probability, "samples": samples, "viewed": viewed,
            }
            for symbol, _, probability, samples, viewed in specs
        ]

        queue = build_action_queue(
            rows,
            alerts,
            as_of="2026-02-10",
            min_probability=0.75,
            min_samples=100,
            market_type="perp",
            new_only=True,
        )

        self.assertEqual([item["symbol"] for item in queue], ["PERPNEWUSDT"])

    def test_current_alert_uses_its_matching_persisted_event_for_view_state(self):
        row = {
            "symbol": "AAAUSDT", "as_of": "2026-02-10",
            "alert_type": "bullish_flip_confirmed", "alert_direction": "long",
            "direction": "long", "trend_score": 2,
            "continuation_probability": 0.70,
        }
        matching = self.prior_alert(
            id="current", as_of="2026-02-10", type="bullish_flip_confirmed",
            direction="long", viewed=False,
        )
        other = self.prior_alert(
            id="other", as_of="2026-02-10", type="bearish_flip_confirmed",
            direction="short", viewed=True,
        )

        state = derive_lifecycle(row, [matching, other], as_of="2026-02-10")

        self.assertEqual(state["event_id"], "current")
        self.assertTrue(state["is_new"])

    def test_alert_older_than_forty_five_days_is_inactive(self):
        row = {
            "symbol": "AAAUSDT", "as_of": "2026-03-07", "alert_type": None,
            "direction": "long", "trend_score": 3, "score_change_5d": 1,
            "continuation_probability": 0.62,
        }

        state = derive_lifecycle(row, [self.prior_alert()], as_of="2026-03-07")

        self.assertEqual(state["lifecycle"], "Inactive")
        self.assertIsNone(state["first_seen"])
        self.assertIsNone(state["age_days"])
        self.assertIsNone(state["highest_probability"])
        self.assertFalse(state["is_new"])


if __name__ == "__main__":
    unittest.main()
