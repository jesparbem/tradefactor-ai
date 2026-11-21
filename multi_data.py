#!/usr/bin/env python3
"""
Cargador de datos multi-mercado (F0) -> /root/trading-sim/data/
  - Cripto        : Binance (BTC, ETH)            [tiempo real, gratuito]
  - Acciones/ETF  : Yahoo via yfinance (AAPL, MSFT, NVDA, TSLA, AMZN, SPY)
  - Materias      : Yahoo via yfinance (GC=F oro, CL=F WTI, SI=F plata)
  - Divisas       : Yahoo via yfinance (EURUSD=X, GBPUSD=X, USDJPY=X)
  - Retraso bolsa/materias/divisas ~15 min en el plan gratuito (honesto).
Guarda CSVs con el mismo esquema que Binance (open_time, close, ...) para que
simcore.load() los lea igual.
"""
import csv, os, sys, time
from datetime import datetime, timezone

sys.path.insert(0, "/root/trading-sim")
DATA = "/root/trading-sim/data"
START = "2019-01-01"
os.makedirs(DATA, exist_ok=True)

CRYPTO = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}
YAHOO = {
    "AAPL": "Accion", "MSFT": "Accion", "NVDA": "Accion", "TSLA": "Accion",
    "AMZN": "Accion", "SPY": "ETF SP500", "QQQ": "ETF Nasdaq",
    "GC=F": "Oro", "CL=F": "Petroleo WTI", "SI=F": "Plata",
    "EURUSD=X": "Divisa EUR/USD", "GBPUSD=X": "Divisa GBP/USD", "USDJPY=X": "Divisa USD/JPY",
}
FEE_BY_MARKET = {"crypto": 0.0015, "stock": 0.0010, "commodity": 0.0010, "fx": 0.0008}

def market_of(sym):
    if sym in CRYPTO:
        return "crypto"
    s = YAHOO.get(sym, "")
    if "Oro" in s or "Petroleo" in s or "Plata" in s:
        return "commodity"
    if "Divisa" in s:
        return "fx"
    return "stock"

def save_csv(sym, rows):
    path = f"{DATA}/{sym.replace('=', '')}_1d.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time", "open", "high", "low", "close", "volume", "close_time"])
        for r in rows:
            w.writerow(r)
    return path

def fetch_binance(sym_usdt):
    rows, cursor = [], int(datetime(2019, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    import urllib.request, json
    while True:
        url = f"https://api.binance.com/api/v3/klines?symbol={sym_usdt}&interval=1d&startTime={cursor}&limit=1000"
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

def fetch_yahoo(symbols):
    import yfinance as yf
    out = {}
    df = yf.download(symbols, start=START, interval="1d", progress=False, auto_adjust=True, group_by="ticker", threads=False)
    if len(symbols) == 1:
        df = df.loc[:, [(c, symbols[0]) for c in ["Open", "High", "Low", "Close", "Volume"]]]
        df.columns = df.columns.droplevel(1)
    for sym in symbols:
        d = df[sym].dropna(subset=["Close"]) if len(symbols) > 1 else df.dropna(subset=["Close"])
        rows = []
        for ts, row in d.iterrows():
            t_ms = int(ts.timestamp() * 1000)
            rows.append([t_ms, row["Open"], row["High"], row["Low"], row["Close"], row["Volume"], t_ms])
        out[sym] = rows
    return out

def main():
    print("== Cripto (Binance) ==")
    for short, usdt in CRYPTO.items():
        rows = fetch_binance(usdt)
        p = save_csv(short, rows)
        print(f"  {short}: {len(rows)} velas -> {p}")
    print("== Acciones / materias / divisas (Yahoo) ==")
    syms = list(YAHOO.keys())
    for i in range(0, len(syms), 5):
        chunk = syms[i:i+5]
        try:
            got = fetch_yahoo(chunk)
            for sym, rows in got.items():
                p = save_csv(sym, rows)
                first = datetime.fromtimestamp(rows[0][0] / 1000, tz=timezone.utc).date() if rows else "-"
                last = datetime.fromtimestamp(rows[-1][0] / 1000, tz=timezone.utc).date() if rows else "-"
                print(f"  {sym:9s} [{YAHOO[sym]:14s}] {len(rows):4d} velas | {first} -> {last} | {p}")
        except Exception as e:
            print(f"  ERROR en {chunk}: {str(e)[:100]}")
        time.sleep(2)
    # indice de mercados con comisiones
    with open(f"{DATA}/markets.json", "w") as f:
        import json
        json.dump({s: {"market": market_of(s), "fee_per_side": FEE_BY_MARKET[market_of(s)]} for s in list(CRYPTO) + syms}, f, indent=1)
    print("markets.json escrito (comisiones por mercado incluidas)")

if __name__ == "__main__":
    main()