#!/usr/bin/env python3
"""Descarga velas diarias de Binance (API publica) y las guarda en CSV."""
import json, time, urllib.request, csv, os
from datetime import datetime, timezone

BASE = "https://api.binance.com/api/v3/klines"
OUT = "/root/trading-sim/data"
os.makedirs(OUT, exist_ok=True)

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
START_MS = int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)

def fetch(symbol, start_ms):
    rows = []
    cursor = start_ms
    while True:
        url = f"{BASE}?symbol={symbol}&interval=1d&startTime={cursor}&limit=1000"
        with urllib.request.urlopen(url, timeout=30) as r:
            batch = json.loads(r.read())
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + 1
        if len(batch) < 1000:
            break
        time.sleep(0.3)
    return rows

for sym in SYMBOLS:
    rows = fetch(sym, START_MS)
    path = f"{OUT}/{sym}_1d.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6]])
    first = datetime.fromtimestamp(rows[0][0] / 1000, tz=timezone.utc).date()
    last = datetime.fromtimestamp(rows[-1][0] / 1000, tz=timezone.utc).date()
    print(f"{sym}: {len(rows)} velas | {first} -> {last} | {path}")
