import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from threading import Barrier

from advisory_delivery import DeliveryLedger
from scheduled_runner import format_digest, main, rank_alerts, run_daily


class ScheduledRunnerTests(unittest.TestCase):
    def test_probability_ranking_puts_unavailable_probabilities_last(self):
        alerts = [
            {"symbol": "LOWUSDT", "probability": 0.55, "samples": 500},
            {"symbol": "UNKNOWNUSDT", "probability": None, "samples": 0},
            {"symbol": "HIGHUSDT", "probability": 0.72, "samples": 80},
        ]

        ranked = rank_alerts(alerts)

        self.assertEqual([alert["symbol"] for alert in ranked], ["HIGHUSDT", "LOWUSDT", "UNKNOWNUSDT"])

    def test_digest_is_ranked_and_states_probability_scope_and_guardrail(self):
        alerts = [
            {
                "id": "PERPUSDT:2026-09-08:bearish_flip_watch",
                "symbol": "PERPUSDT",
                "label": "Bearish flip watch",
                "direction": "short",
                "as_of": "2026-09-08",
                "probability": 0.61,
                "samples": 44,
            },
            {
                "id": "SPOTUSDT:2026-09-08:bullish_flip_confirmed",
                "symbol": "SPOTUSDT",
                "label": "Bullish flip confirmed",
                "direction": "long",
                "as_of": "2026-09-08",
                "probability": 0.73,
                "samples": 120,
            },
        ]

        digest = format_digest(
            alerts,
            horizon_days=20,
            market_types={"PERPUSDT": "perp", "SPOTUSDT": "spot"},
        )

        self.assertEqual(
            digest.splitlines(),
            [
                "VWAP advisory digest — 2 new alerts",
                "1. SPOTUSDT @ 2026-09-08 | Bullish flip confirmed | long | 73.0% (n=120; 20D directional continuation; spot-trained)",
                "2. PERPUSDT @ 2026-09-08 | Bearish flip watch | short | 61.0% (n=44; 20D directional continuation; spot-trained transfer to perp-only; lower confidence)",
                "Advisory only — empirical association, not trade success probability or a trading instruction.",
            ],
        )

    def test_digest_labels_missing_or_unrecognized_market_type_unclassified(self):
        alerts = [
            {
                "id": "MISSINGUSDT:2026-09-08:bullish_flip_watch",
                "symbol": "MISSINGUSDT",
                "label": "Bullish flip watch",
                "direction": "long",
                "as_of": "2026-09-08",
                "probability": 0.6,
                "samples": 10,
            },
            {
                "id": "ODDUSDT:2026-09-08:bearish_flip_watch",
                "symbol": "ODDUSDT",
                "label": "Bearish flip watch",
                "direction": "short",
                "as_of": "2026-09-08",
                "probability": 0.5,
                "samples": 10,
            },
        ]

        digest = format_digest(alerts, horizon_days=20, market_types={"ODDUSDT": "futures"})

        self.assertEqual(digest.count("unknown/unclassified market; calibration scope unknown"), 2)
        self.assertNotIn("MISSINGUSDT @ 2026-09-08 | Bullish flip watch | long | 60.0% (n=10; 20D directional continuation; spot-trained)", digest)

    def test_delivery_ledger_atomically_claims_alerts_across_overlapping_runners(self):
        alert = {"id": "AAAUSDT:2026-09-08:bullish_flip_watch"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "advisory-deliveries.db"
            first = DeliveryLedger(path)
            second = DeliveryLedger(path)
            barrier = Barrier(2)

            def claim(ledger):
                barrier.wait()
                return ledger.claim([alert])

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(claim, (first, second)))

        claimed_batches = [claimed for _event_id, claimed in results if claimed]
        self.assertEqual(claimed_batches, [[alert]])

    def test_overlapping_daily_runs_emit_one_claimed_batch(self):
        alert = {
            "id": "AAAUSDT:2026-09-08:bullish_flip_watch",
            "symbol": "AAAUSDT",
            "label": "Bullish flip watch",
            "direction": "long",
            "as_of": "2026-09-08",
            "probability": 0.64,
            "samples": 90,
        }
        payload = {
            "alerts": [alert],
            "rows": [{"symbol": "AAAUSDT", "market_type": "spot"}],
            "meta": {"signal_probability_horizon_days": 20},
        }
        refresh_barrier = Barrier(2)
        emit_barrier = Barrier(2)
        emitted = []

        def fake_refresh(_output_dir):
            refresh_barrier.wait()
            return payload

        def emit(digest):
            emitted.append(digest)
            try:
                emit_barrier.wait(timeout=1)
            except Exception:
                pass

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(
                    executor.map(
                        lambda _index: run_daily(output_dir, refresh_fn=fake_refresh, emit=emit),
                        range(2),
                    )
                )

        self.assertEqual(len(emitted), 1)
        self.assertEqual(sum(event_id is not None for event_id in results), 1)

    def test_emit_failure_releases_claim_for_retry_with_same_event_id(self):
        alert = {
            "id": "AAAUSDT:2026-09-08:bullish_flip_watch",
            "symbol": "AAAUSDT",
            "label": "Bullish flip watch",
            "direction": "long",
            "as_of": "2026-09-08",
            "probability": 0.64,
            "samples": 90,
        }
        payload = {
            "alerts": [alert],
            "rows": [{"symbol": "AAAUSDT", "market_type": "spot"}],
            "meta": {"signal_probability_horizon_days": 20},
        }

        def fail_emit(_digest):
            raise RuntimeError("stdout unavailable")

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "stdout unavailable"):
                run_daily(output_dir, refresh_fn=lambda _path: payload, emit=fail_emit)

            retried_digests = []
            retry_event_id = run_daily(
                output_dir,
                refresh_fn=lambda _path: payload,
                emit=retried_digests.append,
            )

        expected_event_id = DeliveryLedger._event_id([alert["id"]])
        self.assertEqual(retry_event_id, expected_event_id)
        self.assertIn(f"Delivery event ID: {expected_event_id}", retried_digests[0])

    def test_delivery_ledger_persistently_deduplicates_alert_ids(self):
        alerts = [
            {"id": "AAAUSDT:2026-09-08:bullish_flip_watch"},
            {"id": "BBBUSDT:2026-09-08:bearish_flip_confirmed"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "advisory-deliveries.db"
            ledger = DeliveryLedger(path)

            event_id = ledger.mark_delivered([alerts[0]])

            self.assertTrue(event_id.startswith("daily-advisory:"))
            self.assertNotEqual(event_id, alerts[0]["id"])
            reopened = DeliveryLedger(path)
            self.assertEqual(reopened.pending(alerts), [alerts[1]])

    def test_delivery_ledger_deduplicates_repeated_ids_within_one_batch(self):
        alert = {"id": "AAAUSDT:2026-09-08:bullish_flip_watch"}
        with tempfile.TemporaryDirectory() as directory:
            ledger = DeliveryLedger(Path(directory) / "advisory-deliveries.db")

            self.assertEqual(ledger.pending([alert, dict(alert)]), [alert])

    def test_daily_run_refreshes_then_emits_each_alert_only_once(self):
        calls = []
        alert = {
            "id": "AAAUSDT:2026-09-08:bullish_flip_watch",
            "symbol": "AAAUSDT",
            "label": "Bullish flip watch",
            "direction": "long",
            "as_of": "2026-09-08",
            "probability": 0.64,
            "samples": 90,
        }

        def fake_refresh(output_dir):
            calls.append(output_dir)
            print("scanner progress")
            return {
                "alerts": [alert],
                "rows": [{"symbol": "AAAUSDT", "market_type": "spot"}],
                "meta": {"signal_probability_horizon_days": 20},
            }

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            first_stdout = io.StringIO()
            first_stderr = io.StringIO()
            with redirect_stdout(first_stdout), redirect_stderr(first_stderr):
                first_event = run_daily(output_dir, refresh_fn=fake_refresh)

            second_stdout = io.StringIO()
            with redirect_stdout(second_stdout), redirect_stderr(io.StringIO()):
                second_event = run_daily(output_dir, refresh_fn=fake_refresh)

        self.assertTrue(first_event.startswith("daily-advisory:"))
        self.assertIn("AAAUSDT", first_stdout.getvalue())
        self.assertNotIn("scanner progress", first_stdout.getvalue())
        self.assertIn("scanner progress", first_stderr.getvalue())
        self.assertIsNone(second_event)
        self.assertEqual(second_stdout.getvalue(), "")
        self.assertEqual(calls, [output_dir, output_dir])

    def test_cli_accepts_an_explicit_output_directory(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)

            exit_code = main(["--output-dir", str(output_dir)], run_fn=calls.append)

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [output_dir])


if __name__ == "__main__":
    unittest.main()
