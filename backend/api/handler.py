"""
API Lambda — GET /movers
────────────────────────
Returns the last 7 days of "top mover" records from DynamoDB.
Invoked via API Gateway HTTP API (payload format 2.0).
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME: str = os.environ["DYNAMODB_TABLE_NAME"]
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "21"))
RESULT_LIMIT = int(os.environ.get("RESULT_LIMIT", "7"))

_dynamodb = boto3.resource("dynamodb")

# ── Response helpers ─────────────────────────────────────────────────────────

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Cache-Control": "public, max-age=3600",
    "X-Content-Type-Options": "nosniff",
}


class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, cls=_DecimalEncoder),
    }


def _batch_get_all(date_keys: list[dict], max_retries: int = 5) -> list[dict]:
    """Batch-read requested date keys, retrying any DynamoDB unprocessed keys."""
    request_items = {
        TABLE_NAME: {
            "Keys": date_keys,
            "ProjectionExpression": "#dt, ticker, pct_change, close_price, open_price",
            "ExpressionAttributeNames": {"#dt": "date"},
        }
    }

    records = []
    for attempt in range(max_retries + 1):
        db_resp = _dynamodb.batch_get_item(RequestItems=request_items)
        records.extend(db_resp.get("Responses", {}).get(TABLE_NAME, []))
        request_items = db_resp.get("UnprocessedKeys", {})
        if not request_items:
            return records

        wait = min(2 ** attempt, 8)
        logger.warning("DynamoDB returned unprocessed keys; retrying in %ss", wait)
        time.sleep(wait)

    raise RuntimeError("DynamoDB batch_get_item left unprocessed keys after retries")


# ── Lambda handler ───────────────────────────────────────────────────────────

def lambda_handler(event, context):  # noqa: ARG001
    # HTTP API v2 payload format
    method = (
        event.get("requestContext", {}).get("http", {}).get("method", "")
        or event.get("httpMethod", "GET")
    )

    if method == "OPTIONS":
        return _response(200, {})

    logger.info("GET /movers requested")

    try:
        today = datetime.now(timezone.utc).date()
        # Look back far enough to cover weekends and market holidays, then cap
        # the response to the latest seven stored winners.
        date_keys = [
            {"date": (today - timedelta(days=i)).strftime("%Y-%m-%d")}
            for i in range(LOOKBACK_DAYS)
        ]

        records = _batch_get_all(date_keys)
        records.sort(key=lambda r: r["date"], reverse=True)
        records = records[:RESULT_LIMIT]

        movers = [
            {
                "date":        rec["date"],
                "ticker":      rec["ticker"],
                "pct_change":  float(rec["pct_change"]),
                "close_price": float(rec["close_price"]),
                "open_price":  float(rec.get("open_price", 0)),
                "direction":   "gain" if float(rec["pct_change"]) >= 0 else "loss",
            }
            for rec in records
        ]

        logger.info("Returning %d records", len(movers))
        return _response(200, {"status": "success", "count": len(movers), "data": movers})

    except Exception as exc:
        logger.error("Unhandled error: %s", exc, exc_info=True)
        return _response(500, {"status": "error", "message": "Internal server error"})
