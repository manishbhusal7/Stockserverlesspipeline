#!/usr/bin/env python3
"""
Local development server — no AWS required.

Serves the frontend at http://localhost:8000
Provides GET /movers backed by the real Massive API.

Usage:
  MASSIVE_API_KEY=your-key-here python3 scripts/local_server.py
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# ── Config ────────────────────────────────────────────────────────────────

PORT       = 8000
WATCHLIST  = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]
API_KEY    = os.environ.get("MASSIVE_API_KEY", "")
REQUEST_DELAY_SECONDS = float(os.environ.get("MASSIVE_REQUEST_DELAY_SECONDS", "13"))

FRONTEND   = Path(__file__).parent.parent / "frontend"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".ico":  "image/x-icon",
}

# ── Mock Data Generator ───────────────────────────────────────────────────

def _mock_movers() -> list[dict]:
    import random
    from datetime import date, timedelta
    
    price_ranges = {
        "AAPL":  (190.0, 215.0),
        "MSFT":  (410.0, 450.0),
        "GOOGL": (165.0, 195.0),
        "AMZN":  (185.0, 215.0),
        "TSLA":  (165.0, 250.0),
        "NVDA":  (850.0, 1050.0),
    }
    
    results = []
    today = date.today()
    
    # Generate last 7 trading days
    day_offset = 0
    while len(results) < 7:
        d = today - timedelta(days=day_offset)
        day_offset += 1
        # Skip weekends
        if d.weekday() >= 5:
            continue
            
        ticker = random.choice(WATCHLIST)
        lo, hi = price_ranges[ticker]
        open_price = round(random.uniform(lo, hi), 2)
        pct = round(random.uniform(-6.0, 6.0), 4)
        close_price = round(open_price * (1 + pct / 100), 2)
        
        results.append({
            "date": d.strftime("%Y-%m-%d"),
            "ticker": ticker,
            "pct_change": pct,
            "close_price": close_price,
            "open_price": open_price,
            "direction": "gain" if pct >= 0 else "loss",
        })
        
    return results


# ── Real Yahoo Finance API ────────────────────────────────────────────────

def _yahoo_movers() -> list[dict]:
    import datetime
    from datetime import timezone
    
    daily_data = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    
    print("\nFetching real historical data from Yahoo Finance...")
    for ticker in WATCHLIST:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=15d&interval=1d"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            res = data.get("chart", {}).get("result", [])
            if not res:
                continue
            res = res[0]
            timestamps = res.get("timestamp", [])
            quote = res.get("indicators", {}).get("quote", [{}])[0]
            opens = quote.get("open", [])
            closes = quote.get("close", [])
            
            for i in range(len(timestamps)):
                if i < len(opens) and i < len(closes):
                    o = opens[i]
                    c = closes[i]
                    if o is not None and c is not None and o != 0:
                        ts = timestamps[i]
                        dt = datetime.datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                        pct = round(((c - o) / o) * 100, 4)
                        
                        if dt not in daily_data:
                            daily_data[dt] = []
                        daily_data[dt].append({
                            "ticker": ticker,
                            "open_price": round(float(o), 2),
                            "close_price": round(float(c), 2),
                            "pct_change": pct
                        })
            print(f"  {ticker}: loaded successfully")
        except Exception as exc:
            print(f"  {ticker}: error fetching Yahoo Finance data — {exc}")
            
    winners = []
    for dt, candidates in daily_data.items():
        if not candidates:
            continue
        winner = max(candidates, key=lambda x: abs(x["pct_change"]))
        winners.append({
            "date": dt,
            "ticker": winner["ticker"],
            "pct_change": winner["pct_change"],
            "close_price": winner["close_price"],
            "open_price": winner["open_price"],
            "direction": "gain" if winner["pct_change"] >= 0 else "loss",
        })
        
    winners.sort(key=lambda x: x["date"], reverse=True)
    return winners[:7]


# ── Real Massive API ──────────────────────────────────────────────────────

def _rate_limit_wait(exc: urllib.error.HTTPError) -> int:
    retry_after = exc.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return int(retry_after)
    return 65


def _fetch_previous_day_bar(ticker: str, max_retries: int = 2) -> dict:
    url = f"https://api.massive.com/v2/aggs/ticker/{ticker}/prev"

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            if data.get("status") == "OK" and data.get("results"):
                return data["results"][0]
            raise RuntimeError(f"{ticker}: Massive returned no results")
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < max_retries:
                wait = _rate_limit_wait(exc)
                print(f"  {ticker}: rate-limited, retrying in {wait}s")
                time.sleep(wait)
                continue
            raise

    raise RuntimeError(f"{ticker}: failed after retries")


def _real_movers() -> list[dict]:
    results = []
    errors = []

    for index, ticker in enumerate(WATCHLIST):
        try:
            b = _fetch_previous_day_bar(ticker)
            o, c = float(b["o"]), float(b["c"])
            if o == 0:
                raise RuntimeError(f"{ticker}: open price is zero")

            pct = round(((c - o) / o) * 100, 4)
            from datetime import datetime, timezone
            ts  = b.get("t", 0)
            dt  = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            results.append({
                "date": dt, "ticker": ticker,
                "pct_change": pct, "close_price": round(c, 4),
                "open_price": round(o, 4),
                "direction": "gain" if pct >= 0 else "loss",
            })
            print(f"  {ticker}: open={o:.2f}  close={c:.2f}  {pct:+.2f}%")
        except Exception as exc:
            print(f"  {ticker}: error — {exc}")
            errors.append(f"{ticker}: {exc}")

        if index < len(WATCHLIST) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)

    if errors:
        raise RuntimeError("Massive API did not return data for the full watchlist: " + "; ".join(errors))

    if not results:
        return []

    winner = max(results, key=lambda x: abs(x["pct_change"]))
    return [winner]


# ── Request handler ───────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: str, ctype: str = "application/json"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        # Parse query string parameters
        parsed_url = urlparse(self.path)
        
        # ── /movers API ───────────────────────────────────────────────────
        if parsed_url.path == "/movers":
            # Extract limit parameter
            query_params = parse_qs(parsed_url.query)
            limit = 7
            if "limit" in query_params:
                try:
                    limit = int(query_params["limit"][0])
                except ValueError:
                    pass

            if not API_KEY:
                try:
                    movers = _yahoo_movers()
                    source = "yahoo"
                except Exception as exc:
                    print(f"\nFailed to fetch from Yahoo Finance ({exc}), falling back to synthetic mock data…")
                    movers = _mock_movers()
                    source = "mock"
                
                # Apply pagination limit
                movers = movers[:limit]
                
                payload = json.dumps(
                    {"status": "success", "count": len(movers), "data": movers, "source": source},
                    indent=2,
                )
            else:
                print("\nFetching live data from Massive API…")
                try:
                    movers = _real_movers()
                    # Apply pagination limit
                    movers = movers[:limit]
                except Exception as exc:
                    payload = json.dumps(
                        {
                            "status": "error",
                            "message": str(exc),
                            "source": "live",
                        },
                        indent=2,
                    )
                    self._send(502, payload)
                    return

                if not movers:
                    payload = json.dumps(
                        {
                            "status": "error",
                            "message": "Massive API returned no usable stock data",
                            "source": "live",
                        },
                        indent=2,
                    )
                    self._send(502, payload)
                    return

                payload = json.dumps(
                    {"status": "success", "count": len(movers), "data": movers, "source": "live"},
                    indent=2,
                )

            # ETag verification
            etag = f'W/"{hashlib.sha256(payload.encode()).hexdigest()[:16]}"'
            if_none_match = self.headers.get("If-None-Match")
            if if_none_match == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return

            # Otherwise send full response
            data = payload.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "public, max-age=300, must-revalidate")
            self.end_headers()
            self.wfile.write(data)
            return

        # ── Static files ──────────────────────────────────────────────────
        path = parsed_url.path
        if path == "/":
            path = "/index.html"

        # Inject real API URL into config.js
        if path == "/config.js":
            api_url = f"http://localhost:{PORT}/movers"
            js = f'window.APP_CONFIG = {{ apiUrl: "{api_url}" }};\n'
            self._send(200, js, "application/javascript; charset=utf-8")
            return

        file_path = FRONTEND / path.lstrip("/")
        if file_path.is_file():
            ext   = file_path.suffix.lower()
            ctype = CONTENT_TYPES.get(ext, "text/plain")
            self._send(200, file_path.read_text(encoding="utf-8"), ctype)
        else:
            self._send(404, '{"error":"not found"}')


# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not API_KEY:
        print("💡 MASSIVE_API_KEY not found in environment.")
        print("   Running in Live Free Mode using Yahoo Finance (real data).")
        mode_label = "Yahoo Finance (Real Data)"
    else:
        mode_label = f"LIVE Massive API (key: ...{API_KEY[-6:]})"


    print(f"""
  ╔════════════════════════════════════════════════╗
  ║   TRE Stock Pipeline — Local Dev Server        ║
  ╠════════════════════════════════════════════════╣
  ║  URL    : http://localhost:{PORT}                  ║
  ║  API    : http://localhost:{PORT}/movers            ║
  ║  Mode   : {mode_label:<36} ║
  ╚════════════════════════════════════════════════╝
  """)
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\nServer stopped.")
