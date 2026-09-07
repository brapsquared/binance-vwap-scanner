from __future__ import annotations

import argparse
import json
import mimetypes
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from scanner import refresh

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
SYMBOL = re.compile(r"^[A-Z0-9]+USDT$")


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/scanner":
            return self.send_file(DATA / "scanner.json", "application/json")
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
