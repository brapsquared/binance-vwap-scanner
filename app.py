from __future__ import annotations

import argparse
import json
import math
import mimetypes
import re
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from alert_store import AlertStore
from lifecycle import build_action_queue
from scanner import refresh

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
SYMBOL = re.compile(r"^[A-Z0-9]+USDT$")
REFRESH_LOCK = threading.Lock()
REFRESH_STATE = {"running": False, "started_at": None, "finished_at": None, "error": None}


def parse_action_queue_filters(query: dict[str, list[str]]) -> dict:
    allowed = {"min_probability", "min_samples", "market_type", "new_only"}
    if set(query) - allowed or any(len(values) != 1 for values in query.values()):
        raise ValueError("Unknown or repeated Action Queue filter")
    probability = float(query.get("min_probability", ["0"])[0])
    samples = int(query.get("min_samples", ["0"])[0])
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("min_probability must be between 0 and 1")
    if samples < 0:
        raise ValueError("min_samples must be a non-negative integer")
    market_aliases = {"all": "all", "spot": "spot", "perp": "perp", "perp-only": "perp"}
    raw_market_type = query.get("market_type", ["all"])[0].lower()
    if raw_market_type not in market_aliases:
        raise ValueError("market_type must be all, spot, or perp-only")
    raw_new_only = query.get("new_only", ["false"])[0].lower()
    boolean_values = {"true": True, "1": True, "false": False, "0": False}
    if raw_new_only not in boolean_values:
        raise ValueError("new_only must be true or false")
    return {
        "min_probability": probability,
        "min_samples": samples,
        "market_type": market_aliases[raw_market_type],
        "new_only": boolean_values[raw_new_only],
    }


def run_refresh():
    try:
        refresh(DATA)
        REFRESH_STATE.update({"finished_at": datetime.now(timezone.utc).isoformat(), "error": None})
    except Exception as exc:
        REFRESH_STATE.update({"finished_at": datetime.now(timezone.utc).isoformat(), "error": str(exc)})
    finally:
        REFRESH_STATE["running"] = False
        REFRESH_LOCK.release()


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/scanner":
            return self.send_file(DATA / "scanner.json", "application/json")
        if path == "/api/refresh-status":
            return self.send_json(REFRESH_STATE)
        if path == "/api/alerts-history":
            query = parse_qs(parsed.query)
            symbol = query.get("symbol", [None])[0]
            alert_type = query.get("type", [None])[0]
            store = AlertStore(DATA / "alerts.db")
            alerts = store.list(symbol=symbol, alert_type=alert_type)
            return self.send_json({"count": len(alerts), "total": store.count(), "alerts": alerts})
        if path == "/api/action-queue":
            try:
                filters = parse_action_queue_filters(parse_qs(parsed.query, keep_blank_values=True))
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, status=400)
            scanner_path = DATA / "scanner.json"
            if not scanner_path.exists():
                return self.send_error(503, "Data not ready. Run: python app.py --refresh")
            scanner = json.loads(scanner_path.read_text(encoding="utf-8"))
            rows = scanner.get("rows", [])
            dates = [row.get("as_of") for row in rows if row.get("as_of")]
            as_of = max(dates) if dates else None
            events = (
                AlertStore(DATA / "alerts.db").list_recent(
                    as_of=as_of,
                    symbols=[row["symbol"] for row in rows],
                )
                if as_of
                else []
            )
            items = build_action_queue(rows, events, as_of=as_of, **filters)
            return self.send_json({"as_of": as_of, "count": len(items), "filters": filters, "items": items})
        if path.startswith("/api/chart/"):
            symbol = path.rsplit("/", 1)[-1].upper()
            if not SYMBOL.fullmatch(symbol):
                return self.send_error(400, "Invalid symbol")
            return self.send_file(DATA / "history" / f"{symbol}.json", "application/json")
        if path == "/" or path == "/index.html":
            return self.send_file(STATIC / "index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            target = (STATIC / path.removeprefix("/static/")).resolve()
            if STATIC.resolve() not in target.parents:
                return self.send_error(403)
            return self.send_file(target, mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        return self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/refresh":
            return self.send_error(404)
        if not REFRESH_LOCK.acquire(blocking=False):
            return self.send_json({"accepted": False, **REFRESH_STATE}, status=409)
        REFRESH_STATE.update({"running": True, "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None, "error": None})
        threading.Thread(target=run_refresh, daemon=True).start()
        return self.send_json({"accepted": True, **REFRESH_STATE}, status=202)

    def send_json(self, payload, status=200):
        content = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def send_file(self, path: Path, content_type: str):
        if not path.exists():
            return self.send_error(503, "Data not ready. Run: python app.py --refresh")
        content = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


def main():
    parser = argparse.ArgumentParser(description="Binance 365D rolling VWAP scanner")
    parser.add_argument("--refresh", action="store_true", help="Download fresh Velo history before serving")
    parser.add_argument("--refresh-only", action="store_true", help="Download data and exit")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    if args.refresh or args.refresh_only:
        result = refresh(DATA)
        counts = {}
        for row in result["rows"]:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        print(json.dumps({"symbols": len(result["rows"]), "counts": counts, "errors": len(result["meta"]["errors"])}, indent=2))
    if args.refresh_only:
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Scanner ready at http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
