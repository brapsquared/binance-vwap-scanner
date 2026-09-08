import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import app
from alert_store import AlertStore
from app import parse_action_queue_filters


class ActionQueueFilterTests(unittest.TestCase):
    def test_valid_filters_are_normalized(self):
        filters = parse_action_queue_filters(
            {
                "min_probability": ["0.65"],
                "min_samples": ["120"],
                "market_type": ["perp-only"],
                "new_only": ["true"],
            }
        )

        self.assertEqual(
            filters,
            {
                "min_probability": 0.65,
                "min_samples": 120,
                "market_type": "perp",
                "new_only": True,
            },
        )

    def test_invalid_filters_are_rejected(self):
        invalid_queries = [
            {"min_probability": ["-0.1"]},
            {"min_probability": ["1.1"]},
            {"min_probability": ["nan"]},
            {"min_probability": ["high"]},
            {"min_samples": ["-1"]},
            {"min_samples": ["1.5"]},
            {"market_type": ["futures"]},
            {"new_only": ["yes"]},
            {"new_only": ["true", "false"]},
            {"unknown": ["value"]},
        ]

        for query in invalid_queries:
            with self.subTest(query=query), self.assertRaises(ValueError):
                parse_action_queue_filters(query)


class ActionQueueEndpointTests(unittest.TestCase):
    def request(self, server, path):
        url = f"http://127.0.0.1:{server.server_address[1]}{path}"
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_get_action_queue_returns_derived_filtered_items(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            row = {
                "symbol": "AAAUSDT", "as_of": "2026-02-10", "market_type": "spot",
                "alert_type": "bullish_flip_confirmed", "alert_label": "Bullish flip confirmed",
                "alert_direction": "long", "direction": "long", "trend_score": 2,
                "score_change_5d": 2, "continuation_probability": 0.75,
                "probability_samples": 250, "probability_horizon_days": 20,
                "probability_model_scope": "spot-trained",
            }
            (data / "scanner.json").write_text(
                json.dumps({"meta": {"generated_at": "2026-02-10T01:00:00+00:00"}, "rows": [row]}),
                encoding="utf-8",
            )
            AlertStore(data / "alerts.db").record([
                {
                    "id": "AAAUSDT:2026-02-10:bullish_flip_confirmed", "symbol": "AAAUSDT",
                    "as_of": "2026-02-10", "type": "bullish_flip_confirmed",
                    "label": "Bullish flip confirmed", "direction": "long", "trend_score": 2,
                    "probability": 0.75, "samples": 250,
                }
            ])
            original_data = app.DATA
            app.DATA = data
            server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, payload = self.request(
                    server,
                    "/api/action-queue?min_probability=.7&min_samples=200&market_type=spot&new_only=true",
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                app.DATA = original_data

            self.assertEqual(status, 200)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["as_of"], "2026-02-10")
            self.assertEqual(payload["items"][0]["symbol"], "AAAUSDT")
            self.assertEqual(payload["items"][0]["lifecycle"], "Confirmed")
            self.assertEqual(payload["items"][0]["age_days"], 0)
            self.assertTrue(payload["items"][0]["is_new"])

    def test_get_action_queue_rejects_invalid_query_with_json_error(self):
        original_data = app.DATA
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/api/action-queue?min_probability=2"
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(url, timeout=5)
            payload = json.loads(raised.exception.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            app.DATA = original_data

        self.assertEqual(raised.exception.code, 400)
        self.assertIn("min_probability", payload["error"])

    def test_cross_origin_refresh_is_rejected_without_starting_work(self):
        called = threading.Event()
        original_run_refresh = app.run_refresh
        app.run_refresh = called.set
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/api/refresh",
                method="POST",
                headers={"Origin": "https://attacker.example"},
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            app.run_refresh = original_run_refresh
            if called.wait(1) and app.REFRESH_LOCK.locked():
                app.REFRESH_LOCK.release()
            app.REFRESH_STATE["running"] = False

        self.assertEqual(raised.exception.code, 403)
        self.assertFalse(called.is_set())


if __name__ == "__main__":
    unittest.main()
