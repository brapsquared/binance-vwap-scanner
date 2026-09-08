import tempfile
import unittest
from pathlib import Path

from alert_store import AlertStore


class AlertStoreTests(unittest.TestCase):
    def alert(self, alert_id="AAAUSDT:2026-01-10:bearish_flip_watch", as_of="2026-01-10"):
        return {
            "id": alert_id, "symbol": "AAAUSDT", "as_of": as_of,
            "type": "bearish_flip_watch", "label": "Bearish flip watch",
            "direction": "short", "trend_score": -1, "probability": 0.66, "samples": 120,
        }

    def test_same_alert_is_idempotent_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / "alerts.db")
            store.record([self.alert()], recorded_at="2026-01-10T01:00:00+00:00")
            accepted = store.record([self.alert()], recorded_at="2026-01-11T01:00:00+00:00")

            self.assertEqual(accepted, [])
            self.assertEqual(len(store.list()), 1)
            self.assertEqual(store.list()[0]["first_seen"], "2026-01-10T01:00:00+00:00")
            self.assertEqual(store.list()[0]["last_seen"], "2026-01-10T01:00:00+00:00")

    def test_same_symbol_and_type_respects_ten_day_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / "alerts.db")
            store.record([self.alert()])
            accepted = store.record([self.alert("AAAUSDT:2026-01-15:bearish_flip_watch", "2026-01-15")])
            self.assertEqual(accepted, [])
            self.assertEqual(len(store.list()), 1)

    def test_alert_after_cooldown_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / "alerts.db")
            store.record([self.alert()])
            accepted = store.record([self.alert("AAAUSDT:2026-01-21:bearish_flip_watch", "2026-01-21")])
            self.assertEqual(len(accepted), 1)
            self.assertEqual(len(store.list()), 2)

    def test_history_can_filter_by_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / "alerts.db")
            second = self.alert("BBBUSDT:2026-01-10:bearish_flip_watch")
            second["symbol"] = "BBBUSDT"
            store.record([self.alert(), second])
            self.assertEqual([row["symbol"] for row in store.list(symbol="BBBUSDT")], ["BBBUSDT"])

    def test_recent_events_are_bounded_and_parameterized_by_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / "alerts.db")
            old = self.alert("AAAUSDT:2025-12-01:bearish_flip_watch", "2025-12-01")
            recent = self.alert("AAAUSDT:2026-01-20:bearish_flip_watch", "2026-01-20")
            other = self.alert("BBBUSDT:2026-01-25:bearish_flip_watch", "2026-01-25")
            other["symbol"] = "BBBUSDT"
            store.record([old, recent, other], cooldown_days=0)

            rows = store.list_recent(as_of="2026-02-10", days=45, symbols=["AAAUSDT"])

            self.assertEqual([row["id"] for row in rows], [recent["id"]])
            self.assertFalse(rows[0]["viewed"])

    def test_marking_viewed_does_not_mutate_the_alert_event(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / "alerts.db")
            alert = self.alert()
            store.record([alert], recorded_at="2026-01-10T01:00:00+00:00")
            before = store.list()[0]

            store.mark_viewed(alert["id"], viewed_at="2026-01-12T01:00:00+00:00")

            self.assertEqual(store.list()[0], before)
            rows = store.list_recent(as_of="2026-01-12", symbols=["AAAUSDT"])
            self.assertTrue(rows[0]["viewed"])


if __name__ == "__main__":
    unittest.main()
