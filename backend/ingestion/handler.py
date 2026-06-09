# Ingestion Lambda function. Runs on a cron, fetches previous day OHLC data 
# for tickers, finds the daily top mover, and writes it to DynamoDB.

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

# Config options
WATCHLIST: list[str] = os.environ.get(
    "WATCHLIST", "AAPL,MSFT,GOOGL,AMZN,TSLA,NVDA"
).split(",")

TABLE_NAME: str = os.environ["DYNAMODB_TABLE_NAME"]
SECRET_NAME: str = os.environ["MASSIVE_SECRET_NAME"]
TTL_DAYS: int = int(os.environ.get("TTL_DAYS", "30"))
REQUEST_DELAY_SECONDS: float = float(os.environ.get("MASSIVE_REQUEST_DELAY_SECONDS", "13"))
MASSIVE_API_BASE = "https://api.massive.com"

# AWS clients
_dynamodb = boto3.resource("dynamodb")
_secrets = boto3.client("secretsmanager")

# Helper functions


def _get_api_key() -> str:
    """Retrieve the Massive API key from AWS Secrets Manager."""
    resp = _secrets.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])["api_key"]


def _rate_limit_wait(exc: urllib.error.HTTPError) -> int:
    retry_after = exc.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return int(retry_after)
    return 65


def _fetch_from_yahoo_finance(ticker: str) -> dict | None:
    """
    Fallback method to fetch the latest completed day's bar from Yahoo Finance.
    Returns a dict with 'o' (open), 'c' (close), and 't' (timestamp in milliseconds).
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        logger.info("Calling Yahoo Finance fallback for %s...", ticker)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        res = data.get("chart", {}).get("result", [])
        if not res:
            return None
        res = res[0]
        timestamps = res.get("timestamp", [])
        quote = res.get("indicators", {}).get("quote", [{}])[0]
        opens = quote.get("open", [])
        closes = quote.get("close", [])
        
        # Search backwards for a valid completed bar
        for i in range(len(timestamps) - 1, -1, -1):
            if i < len(opens) and i < len(closes) and opens[i] is not None and closes[i] is not None:
                ts_ms = int(timestamps[i] * 1000)
                logger.info(
                    "Yahoo Finance | %s | o=%.2f c=%.2f t=%d",
                    ticker, opens[i], closes[i], ts_ms
                )
                return {
                    "o": float(opens[i]),
                    "c": float(closes[i]),
                    "t": ts_ms
                }
    except Exception as exc:
        logger.error("Failed to fetch from Yahoo Finance for %s: %s", ticker, exc)
    return None


def _fetch_previous_day_bar(ticker: str, api_key: str | None, max_retries: int = 3) -> dict | None:
    """
    Call GET /v2/aggs/ticker/{ticker}/prev and return the first result dict,
    or None if the request fails after all retries.

    Retries with exponential back-off on 429 (rate limit) and transient errors.
    Raises immediately on 401/403 (bad credentials).
    """
    if not api_key or api_key == "YOUR_MASSIVE_API_KEY_HERE":
        logger.warning("No valid Massive API key. Falling back directly to Yahoo Finance for %s.", ticker)
        return _fetch_from_yahoo_finance(ticker)

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

        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                logger.error("Auth failure (%s) for %s — check API key", exc.code, ticker)
                break
            elif exc.code == 429:
                wait = _rate_limit_wait(exc)
                logger.warning("Rate-limited on %s (attempt %d), retrying in %ds", ticker, attempt + 1, wait)
                time.sleep(wait)
            else:
                logger.error("HTTP %s fetching %s: %s", exc.code, ticker, exc.reason)

        except urllib.error.URLError as exc:
            logger.error("Network error fetching %s: %s", ticker, exc.reason)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error fetching %s: %s", ticker, exc)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    logger.warning("Massive.com fetch failed for %s. Attempting Yahoo Finance fallback...", ticker)
    return _fetch_from_yahoo_finance(ticker)


# Lambda entrypoint
def lambda_handler(event, context):  # noqa: ARG001
    logger.info("Ingestion started | watchlist=%s", WATCHLIST)

    try:
        api_key = _get_api_key()
    except Exception as exc:
        logger.warning("Failed to retrieve Massive API key from Secrets Manager: %s. Proceeding with Yahoo Finance fallback.", exc)
        api_key = None

    candidates: list[dict] = []
    failed_tickers: list[str] = []
    for index, ticker in enumerate(WATCHLIST):
        bar = _fetch_previous_day_bar(ticker, api_key)
        if not bar:
            failed_tickers.append(ticker)
            if index < len(WATCHLIST) - 1:
                time.sleep(REQUEST_DELAY_SECONDS)
            continue

        open_price = float(bar.get("o", 0))
        close_price = float(bar.get("c", 0))

        if open_price == 0:
            logger.warning("%s: open price is zero, skipping", ticker)
            failed_tickers.append(ticker)
            if index < len(WATCHLIST) - 1:
                time.sleep(REQUEST_DELAY_SECONDS)
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

        if index < len(WATCHLIST) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)

    if failed_tickers:
        msg = f"Incomplete stock data for watchlist; failed tickers: {', '.join(failed_tickers)}"
        logger.error(msg)
        raise RuntimeError(msg)

    if not candidates:
        msg = "No valid stock data — market may be closed or API unavailable"
        logger.error(msg)
        raise RuntimeError(msg)

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
