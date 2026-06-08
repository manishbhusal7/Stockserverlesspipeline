"""
Stock Ingestion Lambda
─────────────────────
Triggered by EventBridge on a daily schedule (default 10 PM UTC).
Fetches the previous trading day's OHLC data for each ticker in the watchlist
via the Massive.com (Polygon.io) API, determines the highest absolute % change,
and persists one record to DynamoDB.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Configuration ────────────────────────────────────────────────────────────

WATCHLIST: list[str] = os.environ.get(
    "WATCHLIST", "AAPL,MSFT,GOOGL,AMZN,TSLA,NVDA"
).split(",")

TABLE_NAME: str = os.environ["DYNAMODB_TABLE_NAME"]
SECRET_NAME: str = os.environ["MASSIVE_SECRET_NAME"]
TTL_DAYS: int = int(os.environ.get("TTL_DAYS", "30"))
MASSIVE_API_BASE = "https://api.massive.com"

# ── AWS clients (reused across warm invocations) ────────────────────────────

_dynamodb = boto3.resource("dynamodb")
_secrets = boto3.client("secretsmanager")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Retrieve the Massive API key from AWS Secrets Manager."""
    resp = _secrets.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])["api_key"]


def _fetch_previous_day_bar(ticker: str, api_key: str, max_retries: int = 3) -> dict | None:
    """
    Call GET /v2/aggs/ticker/{ticker}/prev and return the first result dict,
    or None if the request fails after all retries.

    Retries with exponential back-off on 429 (rate limit) and transient errors.
    Raises immediately on 401/403 (bad credentials).
    """
    url = f"{MASSIVE_API_BASE}/v2/aggs/ticker/{ticker}/prev"

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {api_key}"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode())

            status = payload.get("status")
            results = payload.get("results") or []

            if status == "OK" and results:
                bar = results[0]
                logger.info(
                    "%s | o=%.2f  c=%.2f  t=%s",
                    ticker,
                    bar.get("o", 0),
                    bar.get("c", 0),
                    bar.get("t"),
                )
                return bar

            logger.warning(
                "%s: status=%s resultsCount=%d — market likely closed",
                ticker, status, payload.get("resultsCount", 0),
            )
            return None

        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                logger.error("Auth failure (%s) for %s — check API key", exc.code, ticker)
                raise
            if exc.code == 429:
                wait = 2 ** attempt
                logger.warning("Rate-limited on %s (attempt %d), retrying in %ds", ticker, attempt + 1, wait)
                time.sleep(wait)
            else:
                logger.error("HTTP %s fetching %s: %s", exc.code, ticker, exc.reason)
                return None

        except urllib.error.URLError as exc:
            logger.error("Network error fetching %s: %s", ticker, exc.reason)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error fetching %s: %s", ticker, exc)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    logger.error("All %d attempts failed for %s", max_retries, ticker)
    return None


# ── Lambda handler ───────────────────────────────────────────────────────────

def lambda_handler(event, context):  # noqa: ARG001
    logger.info("Ingestion started | watchlist=%s", WATCHLIST)

    api_key = _get_api_key()

    candidates: list[dict] = []
    for ticker in WATCHLIST:
        bar = _fetch_previous_day_bar(ticker, api_key)
        if not bar:
            continue

        open_price = float(bar.get("o", 0))
        close_price = float(bar.get("c", 0))

        if open_price == 0:
            logger.warning("%s: open price is zero, skipping", ticker)
            continue

        pct_change = ((close_price - open_price) / open_price) * 100

        # Convert Unix ms timestamp → YYYY-MM-DD
        ts_ms = bar.get("t", 0)
        date_str = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        candidates.append(
            {
                "ticker": ticker,
                "date": date_str,
                "open_price": open_price,
                "close_price": close_price,
                "pct_change": pct_change,
            }
        )

    if not candidates:
        msg = "No valid stock data — market may be closed or API unavailable"
        logger.warning(msg)
        # Return 200 so EventBridge doesn't retry; alarm will fire if this persists
        return {"statusCode": 200, "body": msg}

    winner = max(candidates, key=lambda x: abs(x["pct_change"]))
    logger.info(
        "Winner: %s | %+.2f%% | open=%.2f close=%.2f | date=%s",
        winner["ticker"], winner["pct_change"],
        winner["open_price"], winner["close_price"],
        winner["date"],
    )

    table = _dynamodb.Table(TABLE_NAME)
    now_utc = datetime.now(timezone.utc)

    item = {
        "date":         winner["date"],
        "ticker":       winner["ticker"],
        "pct_change":   Decimal(str(round(winner["pct_change"], 4))),
        "close_price":  Decimal(str(round(winner["close_price"], 4))),
        "open_price":   Decimal(str(round(winner["open_price"], 4))),
        "expires_at":   int(now_utc.timestamp()) + (TTL_DAYS * 86_400),
        "ingested_at":  now_utc.isoformat(),
    }

    table.put_item(Item=item)
    logger.info("Stored → %s : %s (%+.2f%%)", item["date"], item["ticker"], winner["pct_change"])

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "date":         winner["date"],
                "ticker":       winner["ticker"],
                "pct_change":   round(winner["pct_change"], 4),
                "close_price":  round(winner["close_price"], 4),
            }
        ),
    }
