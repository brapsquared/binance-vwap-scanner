from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path


class AlertStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with closing(self._connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    trend_score INTEGER,
                    probability REAL,
                    samples INTEGER NOT NULL DEFAULT 0,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
            """)
            connection.execute("CREATE INDEX IF NOT EXISTS alerts_symbol_date ON alerts(symbol, as_of DESC)")
            connection.execute("CREATE INDEX IF NOT EXISTS alerts_type_date ON alerts(type, as_of DESC)")

    def record(self, alerts: list[dict], cooldown_days: int = 10) -> list[dict]:
        accepted = []
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for alert in alerts:
                existing = connection.execute("SELECT id FROM alerts WHERE id = ?", (alert["id"],)).fetchone()
                if existing:
                    connection.execute("UPDATE alerts SET last_seen = ? WHERE id = ?", (now, alert["id"]))
                    accepted.append(alert)
                    continue
                prior = connection.execute(
                    "SELECT as_of FROM alerts WHERE symbol = ? AND type = ? ORDER BY as_of DESC LIMIT 1",
                    (alert["symbol"], alert["type"]),
                ).fetchone()
                if prior:
                    current_date = date.fromisoformat(alert["as_of"])
                    prior_date = date.fromisoformat(prior["as_of"])
                    if 0 <= (current_date - prior_date).days < cooldown_days:
                        continue
                connection.execute(
                    """INSERT INTO alerts
                    (id, symbol, as_of, type, label, direction, trend_score, probability, samples, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        alert["id"], alert["symbol"], alert["as_of"], alert["type"], alert["label"],
                        alert["direction"], alert.get("trend_score"), alert.get("probability"),
                        alert.get("samples", 0), now, now,
                    ),
                )
                accepted.append(alert)
        return accepted

    def list(self, symbol: str | None = None, alert_type: str | None = None, limit: int | None = None) -> list[dict]:
        clauses, parameters = [], []
        if symbol:
            clauses.append("symbol = ?")
            parameters.append(symbol.upper())
        if alert_type:
            clauses.append("type = ?")
            parameters.append(alert_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_sql = " LIMIT ?" if limit else ""
        if limit:
            parameters.append(limit)
        query = f"SELECT * FROM alerts {where} ORDER BY as_of DESC, probability DESC, symbol ASC{limit_sql}"
        with closing(self._connect()) as connection, connection:
            return [dict(row) for row in connection.execute(query, parameters).fetchall()]

    def count(self) -> int:
        with closing(self._connect()) as connection, connection:
            return int(connection.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
