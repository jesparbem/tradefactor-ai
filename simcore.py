#!/usr/bin/env python3
"""
Motor de simulacion de inversiones (reusable) — datos reales Binance, costes reales.
Refactor de backtest.py para uso como libreria (devuelve dicts, no imprime).
Costes: 0.1% taker + 0.05% slippage por lado = 0.15% por operacion.
"""
import csv, math, statistics
from datetime import datetime, timezone

DATA_DIR = "/root/trading-sim/data"
FEE = 0.0015

# ------------------------------------------------------------------ datos
def load(sym, data_dir=DATA_DIR):
    path = f"{data_dir}/{sym.upper()}USDT_1d.csv"
    rows = []
    with open(path) as f:
        for x in csv.DictReader(f):
            rows.append({
                "t": datetime.fromtimestamp(int(x["open_time"]) / 1000, tz=timezone.utc),
                "c": float(x["close"]),
            })
    return rows

# ------------------------------------------------------------------ tecnicos
def returns(prices):
    return [prices[i] / prices[i-1] - 1 for i in range(1, len(prices))]

def sma(values, n):
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out

# ------------------------------------------------------------------ estrategias
# Devuelven posicion objetivo (0=cash, 1..=exposicion long) por dia.
def strat_momentum_regime(prices, mom_n=30, ma_n=200):
    pos = [0.0] * len(prices)
    ma = sma(prices, ma_n)
    for i in range(ma_n, len(prices)):
        if ma[i] is None:
            continue
        mom = prices[i] / prices[i - mom_n] - 1 if i >= mom_n else 0
        pos[i] = 1.0 if (mom > 0 and prices[i] > ma[i]) else 0.0
    return pos

def strat_ma_cross(prices, fast=20, slow=50):
    pos = [0.0] * len(prices)
    fa, sl = sma(prices, fast), sma(prices, slow)
    for i in range(1, len(prices)):
        if fa[i] and sl[i] and fa[i-1] and sl[i-1]:
            pos[i] = 1.0 if fa[i] > sl[i] else 0.0
    return pos

def strat_momentum_vol(prices, mom_n=21, vol_n=21, target_vol=0.015):
    pos = [0.0] * len(prices)
    for i in range(vol_n, len(prices)):
        window = prices[i - vol_n:i + 1]
        r = returns(window)
        vol = statistics.pstdev(r)
        if vol == 0:
            continue
        mom = prices[i] / prices[i - mom_n] - 1 if i >= mom_n else 0
        pos[i] = min(1.0, target_vol / vol) if mom > 0 else 0.0
    return pos

STRATEGIES = {
    "momentum_regime": {"fn": strat_momentum_regime, "params": {"mom_n": 30, "ma_n": 200}, "name": "Momentum + filtro de regimen"},
    "ma_cross":        {"fn": strat_ma_cross,        "params": {"fast": 20, "slow": 50},  "name": "Cruce de medias (MA)"},
    "momentum_vol":    {"fn": strat_momentum_vol,    "params": {"mom_n": 21, "vol_n": 21, "target_vol": 0.015}, "name": "Momentum + objetivo volatilidad"},
}

# ------------------------------------------------------------------ simulacion
def simulate(prices, positions, start_cash=100.0):
    """Reinversion total; se ejecuta al dia siguiente del cierre (evita lookahead)."""
    cash, coins = start_cash, 0.0
    equity = []
    for i in range(1, len(prices)):
        target = positions[i - 1]
        if target > 0 and coins == 0:
            coins = cash * (1 - FEE) / prices[i]
            cash = 0.0
        elif target == 0 and coins > 0:
            cash = coins * prices[i] * (1 - FEE)
            coins = 0.0
        equity.append(cash + coins * prices[i])
    return equity

def metrics(prices, positions, start_cash=100.0, t0=0, t1=None, dates=None):
    """Metricas de la estrategia en el segmento [t0,t1). Devuelve dict."""
    t1 = t1 or len(prices)
    seg_prices = prices[t0:t1]
    seg_pos = positions[t0:t1]
    eq = simulate(seg_prices, seg_pos, start_cash)
    if not eq:
        return None
    final = eq[-1]
    days = len(eq)
    years = days / 365.0
    cagr = (final / start_cash) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")
    er = [eq[i] / eq[i-1] - 1 for i in range(1, len(eq))]
    mean_r = statistics.mean(er)
    sd = statistics.pstdev(er)
    sharpe = mean_r / sd * math.sqrt(365) if sd > 0 else 0.0
    peak, maxdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak)
    bw = 1.0
    for i in range(7, len(eq)):
        bw = max(bw, eq[i] / eq[i-7])
    in_mkt = sum(1 for p in seg_pos if p > 0) / len(seg_pos) if seg_pos else 0.0
    # curva de equity (fechas y valor)
    curve_dates = [dates[i].strftime("%Y-%m-%d") for i in range(t0 + 1, t1)] if dates else None
    return {
        "start_cash": start_cash,
        "final": round(final, 2),
        "multiple": round(final / start_cash, 3),
        "cagr": round(cagr, 4),
        "sharpe": round(sharpe, 2),
        "maxdd": round(maxdd, 3),
        "best7": round(bw, 3),
        "time_in_market": round(in_mkt, 3),
        "curve": [{"t": curve_dates[i] if curve_dates else str(i), "eq": round(eq[i], 2)} for i in range(len(eq))],
    }

def calibrate(prices):
    """Debuelve parametros sin calibrar (por defecto) de cada estrategia."""
    return {k: dict(v["params"]) for k, v in STRATEGIES.items()}

if __name__ == "__main__":
    for sym in ("BTC", "ETH"):
        rows = load(sym)
        prices = [x["c"] for x in rows]
        split = next(i for i, x in enumerate(rows) if x["t"].year >= 2024)
        print(f"== {sym}: {len(prices)} velas | split en {rows[split]['t'].date()}")
        for name, st in STRATEGIES.items():
            ps = st["fn"](prices)
            m = metrics(prices, ps, 100.0, t0=split, dates=[x["t"] for x in rows])
            m2 = metrics(prices, ps, 100.0, t0=0, t1=split, dates=[x["t"] for x in rows])
            print(f"  {name}: OOS x{m['multiple']} (Sharpe {m['sharpe']}, DD {m['maxdd']}) | train x{m2['multiple']}")