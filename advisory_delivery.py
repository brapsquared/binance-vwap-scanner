from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


class DeliveryLedger:
    """Durable record of alert IDs already emitted by the advisory runner."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_events (
                    id TEXT PRIMARY KEY,
                    delivered_at TEXT,
                    status TEXT NOT NULL,
                    lease_until REAL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_alerts (
                    delivery_id TEXT NOT NULL,
                    alert_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY (delivery_id) REFERENCES delivery_events(id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _event_id(alert_ids: list[str]) -> str:
        digest = hashlib.sha256("\n".join(alert_ids).encode("utf-8")).hexdigest()[:20]
        return f"daily-advisory:{digest}"

    def claim(self, alerts: list[dict], lease_seconds: float = 300) -> tuple[str | None, list[dict]]:
        """Atomically reserve currently deliverable alerts for one runner."""
        now = time.time()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            expired = connection.execute(
                "SELECT id FROM delivery_events WHERE status = 'claimed' AND lease_until <= ?",
                (now,),
            ).fetchall()
            if expired:
                event_ids = [row[0] for row in expired]
                connection.executemany(
                    "DELETE FROM delivery_alerts WHERE delivery_id = ?",
                    ((event_id,) for event_id in event_ids),
                )
                connection.executemany(
                    "DELETE FROM delivery_events WHERE id = ?",
                    ((event_id,) for event_id in event_ids),
                )

            unavailable = {
                row[0] for row in connection.execute("SELECT alert_id FROM delivery_alerts")
            }
            claimed = []
            seen = set(unavailable)
            for alert in alerts:
                if alert["id"] not in seen:
                    claimed.append(alert)
                    seen.add(alert["id"])
            if not claimed:
                return None, []

            alert_ids = sorted(alert["id"] for alert in claimed)
            event_id = self._event_id(alert_ids)
            connection.execute(
                "INSERT INTO delivery_events (id, status, lease_until) VALUES (?, 'claimed', ?)",
                (event_id, now + lease_seconds),
            )
            connection.executemany(
                "INSERT INTO delivery_alerts (delivery_id, alert_id) VALUES (?, ?)",
                ((event_id, alert_id) for alert_id in alert_ids),
            )
        return event_id, claimed

    def pending(self, alerts: list[dict]) -> list[dict]:
        with closing(self._connect()) as connection:
            delivered = {row[0] for row in connection.execute("SELECT alert_id FROM delivery_alerts")}
        pending = []
        seen = set(delivered)
        for alert in alerts:
            if alert["id"] not in seen:
                pending.append(alert)
                seen.add(alert["id"])
        return pending

    def acknowledge(self, event_id: str) -> None:
        delivered_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE delivery_events
                SET status = 'delivered', delivered_at = ?, lease_until = NULL
                WHERE id = ? AND status = 'claimed'
                """,
                (delivered_at, event_id),
            )

    def release(self, event_id: str) -> None:
        """Release an un-emitted claim so a later run can retry it immediately."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            claimed = connection.execute(
                "SELECT 1 FROM delivery_events WHERE id = ? AND status = 'claimed'",
                (event_id,),
            ).fetchone()
            if claimed:
                connection.execute("DELETE FROM delivery_alerts WHERE delivery_id = ?", (event_id,))
                connection.execute("DELETE FROM delivery_events WHERE id = ?", (event_id,))

    def mark_delivered(self, alerts: list[dict]) -> str:
        alert_ids = sorted({alert["id"] for alert in alerts})
        event_id = self._event_id(alert_ids)
        delivered_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO delivery_events (id, delivered_at, status) VALUES (?, ?, 'delivered')",
                (event_id, delivered_at),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO delivery_alerts (delivery_id, alert_id) VALUES (?, ?)",
                ((event_id, alert_id) for alert_id in alert_ids),
            )
        return event_id
