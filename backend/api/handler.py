"""
API Lambda — GET /movers
────────────────────────
Returns the last 7 days of "top mover" records from DynamoDB.
Invoked via API Gateway HTTP API (payload format 2.0).
"""

import hashlib
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
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Cache-Control": "public, max-age=300, must-revalidate",
    "X-Content-Type-Options": "nosniff",
}


class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _response(status: int, body: dict) -> dict:
    body_str = json.dumps(body, cls=_DecimalEncoder)
    etag = f'W/"{hashlib.sha256(body_str.encode("utf-8")).hexdigest()[:16]}"'
    
    headers = CORS_HEADERS.copy()
    headers["ETag"] = etag
    
    return {
        "statusCode": status,
        "headers": headers,
        "body": body_str,
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
        # Check query string parameters for pagination / limit override
        query_params = event.get("queryStringParameters") or {}
        limit = RESULT_LIMIT
        if query_params and "limit" in query_params:
            try:
                limit = int(query_params["limit"])
                limit = max(1, min(limit, LOOKBACK_DAYS))
            except ValueError:
                pass

        today = datetime.now(timezone.utc).date()
        # Look back far enough to cover weekends and market holidays, then cap
        # the response to the latest stored winners.
        date_keys = [
            {"date": (today - timedelta(days=i)).strftime("%Y-%m-%d")}
            for i in range(LOOKBACK_DAYS)
        ]

        records = _batch_get_all(date_keys)
        records.sort(key=lambda r: r["date"], reverse=True)
        records = records[:limit]

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

        # Conditional GET (ETag / If-None-Match validation)
        body = {"status": "success", "count": len(movers), "data": movers}
        body_str = json.dumps(body, cls=_DecimalEncoder)
        etag = f'W/"{hashlib.sha256(body_str.encode("utf-8")).hexdigest()[:16]}"'

        request_headers = event.get("headers", {}) or {}
        req_headers_lower = {k.lower(): v for k, v in request_headers.items()}
        if_none_match = req_headers_lower.get("if-none-match")

        if if_none_match and if_none_match == etag:
            logger.info("ETag match: %s. Returning 304 Not Modified", etag)
            headers = CORS_HEADERS.copy()
            headers["ETag"] = etag
            return {
                "statusCode": 304,
                "headers": headers,
                "body": "",
            }

        logger.info("Returning %d records", len(movers))
        headers = CORS_HEADERS.copy()
        headers["ETag"] = etag
        return {
            "statusCode": 200,
            "headers": headers,
            "body": body_str,
        }

    except Exception as exc:
        logger.error("Unhandled error: %s", exc, exc_info=True)
        return _response(500, {"status": "error", "message": "Internal server error"})
