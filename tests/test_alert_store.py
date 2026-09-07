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

    def test_same_alert_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlertStore(Path(directory) / "alerts.db")
            store.record([self.alert()])
            store.record([self.alert()])
            self.assertEqual(len(store.list()), 1)

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


if __name__ == "__main__":
    unittest.main()
