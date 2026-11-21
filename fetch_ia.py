#!/usr/bin/env python3
"""Descarga datos de la CADENA DE SUMINISTRO DE IA (materiales + chips) via Yahoo -> CSVs."""
import csv, os, sys, time
sys.path.insert(0, "/root/trading-sim")
from multi_data import save_csv, fetch_yahoo, market_of, FEE_BY_MARKET

DATA = "/root/trading-sim/data"
HOLDS = {
    # IA / chips / memoria
    "AMD": "Chip (AMD)", "TSM": "Chip (TSMC)", "ASML": "Litografia", "AVGO": "Chip (Broadcom)",
    "MU": "Memoria HBM (Micron)", "SMH": "ETF semis",
    # Materiales para IA / baterias / nucleo
    "LIT": "ETF litio", "ALB": "Litio (Albemarle)", "FCX": "Cobre (Freeport)",
    "COPX": "ETF cobre", "URA": "ETF uranio", "REMX": "ETF tierras raras",
}
if __name__ == "__main__":
    print("Bajando datos de IA supply chain...")
    syms = list(HOLDS)
    for i in range(0, len(syms), 5):
        chunk = syms[i:i+5]
        try:
            got = fetch_yahoo(chunk)
            for sym, rows in got.items():
                p = save_csv(sym, rows)
                last = len(rows) and rows[-1][0]
                import datetime
                fecha = datetime.datetime.fromtimestamp(last/1000, tz=datetime.timezone.utc).date() if last else "-"
                print(f"  {sym:7s} [{HOLDS.get(sym,'?'):14s}] {len(rows):4d} velas -> {p} ({fecha})")
        except Exception as e:
            print(f"  ERROR {chunk}: {str(e)[:90]}")
        time.sleep(2)
    with open(f"{DATA}/ia_markets.json", "w") as f:
        import json
        json.dump({s: {"hold": HOLDS[s], "market": market_of(s), "fee": FEE_BY_MARKET[market_of(s)]} for s in syms}, f)
    print("ia_markets.json escrito")