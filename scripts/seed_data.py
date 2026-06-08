#!/usr/bin/env python3
"""
seed_data.py — Populate DynamoDB with synthetic top-mover records.

Usage:
  python3 scripts/seed_data.py <table-name>
  make seed-data          (preferred — auto-resolves table name from Terraform)

Useful for testing the frontend before the daily cron job has run.
Records are tagged with expires_at = now + 7 days so they auto-expire.
"""

import json
import random
import sys
import time
from datetime import date, timedelta
from decimal import Decimal

import boto3

WATCHLIST = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]

# Realistic price ranges per ticker
PRICE_RANGES = {
    "AAPL":  (190.0, 215.0),
    "MSFT":  (410.0, 450.0),
    "GOOGL": (165.0, 195.0),
    "AMZN":  (185.0, 215.0),
    "TSLA":  (165.0, 250.0),
    "NVDA":  (850.0, 1050.0),
}

TTL_SECONDS = 7 * 86_400


def make_record(trading_date: date) -> dict:
    ticker = random.choice(WATCHLIST)
    lo, hi = PRICE_RANGES[ticker]
    open_price  = round(random.uniform(lo, hi), 2)
    # Daily move: ±0.5% to ±6%
    pct_change  = round(random.uniform(-6.0, 6.0), 4)
    close_price = round(open_price * (1 + pct_change / 100), 2)

    return {
        "date":        trading_date.strftime("%Y-%m-%d"),
        "ticker":      ticker,
        "pct_change":  Decimal(str(pct_change)),
        "close_price": Decimal(str(close_price)),
        "open_price":  Decimal(str(open_price)),
        "expires_at":  int(time.time()) + TTL_SECONDS,
        "ingested_at": f"{trading_date.isoformat()}T22:00:00+00:00",
    }


def seed(table_name: str):
    dynamodb = boto3.resource("dynamodb")
    table    = dynamodb.Table(table_name)

    today = date.today()
    records = []

    for i in range(7):
        d = today - timedelta(days=i)
        # Skip weekends
        if d.weekday() >= 5:
            continue
        records.append(make_record(d))

    with table.batch_writer() as batch:
        for rec in records:
            batch.put_item(Item=rec)
            print(f"  ✅ {rec['date']} → {rec['ticker']} ({float(rec['pct_change']):+.2f}%)")

    print(f"\nSeeded {len(records)} records into '{table_name}'.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <table-name>")
        sys.exit(1)
    seed(sys.argv[1])
