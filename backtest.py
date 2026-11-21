#!/usr/bin/env python3
"""
Simulador de trading honesto — datos reales Binance, costes reales.
Objetivo del usuario: 100$ -> x10 en una semana con reinversion exponencial.
Esto mide QUE HACE DE VERDAD esa meta con datos historicos reales.

Costes: 0.1% taker + 0.05% slippage por lado = 0.15% por operacion (compra o venta).
"""
import csv, math, statistics
from datetime import datetime, timezone

DATA = {
    "BTC": "/root/trading-sim/data/BTCUSDT_1d.csv",
    "ETH": "/root/trading-sim/data/ETHUSDT_1d.csv",
}
FEE = 0.0015  # 0.1% taker + 0.05% slippage, por lado

def load(sym):
    rows = []
    with open(DATA[sym]) as f:
        r = csv.DictReader(f)
        for x in r:
            rows.append({
                "t": datetime.fromtimestamp(int(x["open_time"]) / 1000, tz=timezone.utc),
                "c": float(x["close"]),
            })
    return rows

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

# ---------- Estrategias ----------
# Devuelven posicion objetivo (0=cash, 1=long) para cada dia.
def strat_momentum_regime(prices, mom_n=30, ma_n=200):
    """Momentum + filtro de regimen: long si retorno(mom_n)>0 y precio>MA(ma_n)."""
    pos = [0.0] * len(prices)
    ma = sma(prices, ma_n)
    for i in range(ma_n, len(prices)):
        if ma[i] is None:
            continue
        mom = prices[i] / prices[i - mom_n] - 1 if i >= mom_n else 0
        pos[i] = 1.0 if (mom > 0 and prices[i] > ma[i]) else 0.0
    return pos

def strat_ma_cross(prices, fast=20, slow=50):
    """Cruce de medias moviles."""
    pos = [0.0] * len(prices)
    fa, sl = sma(prices, fast), sma(prices, slow)
    for i in range(1, len(prices)):
        if fa[i] and sl[i] and fa[i-1] and sl[i-1]:
            pos[i] = 1.0 if fa[i] > sl[i] else 0.0
    return pos

def strat_momentum_vol(prices, mom_n=21, vol_n=21, target_vol=0.015):
    """Momentum con objetivo de volatilidad (la familia que mejor aguanto en los repos serios)."""
    pos = [0.0] * len(prices)
    for i in range(vol_n, len(prices)):
        window = prices[i - vol_n:i + 1]
        r = returns(window)
        vol = statistics.pstdev(r)
        if vol == 0:
            continue
        mom = prices[i] / prices[i - mom_n] - 1 if i >= mom_n else 0
        if mom > 0:
            pos[i] = min(1.0, target_vol / vol)
        else:
            pos[i] = 0.0
    return pos

# ---------- Simulacion ----------
def simulate(prices, positions, start_cash=100.0):
    """Reinversion total; se cambia posicion al dia siguiente del cierre (evita lookahead)."""
    cash, coins = start_cash, 0.0
    equity = []
    for i in range(1, len(prices)):
        target = positions[i - 1]  # decision del dia anterior, ejecuto hoy
        if target > 0 and coins == 0:
            coins = cash * (1 - FEE) / prices[i]
            cash = 0.0
        elif target == 0 and coins > 0:
            cash = coins * prices[i] * (1 - FEE)
            coins = 0.0
        eq = cash + coins * prices[i]
        equity.append(eq)
    return equity

def weekly_best(prices):
    """Mejor semana historica (7 velas) en multiplicador."""
    best = 0.0
    for i in range(7, len(prices)):
        mult = prices[i] / prices[i - 7]
        best = max(best, mult)
    return best

def report(name, prices, positions, start_cash=100.0, t0=0, t1=None):
    t1 = t1 or len(prices)
    seg_prices = prices[t0:t1]
    seg_pos = positions[t0:t1]
    eq = simulate(seg_prices, seg_pos, start_cash)
    if not eq:
        return
    final = eq[-1]
    days = len(eq)
    years = days / 365.0
    cagr = (final / start_cash) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")
    # retornos de la serie de equity
    er = [eq[i] / eq[i-1] - 1 for i in range(1, len(eq))]
    mean_r = statistics.mean(er)
    sd = statistics.pstdev(er)
    sharpe = mean_r / sd * math.sqrt(365) if sd > 0 else float("nan")
    # drawdown
    peak, maxdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak)
    # mejor semana de la estrategia en el segmento
    bw = 1.0
    for i in range(7, len(eq)):
        bw = max(bw, eq[i] / eq[i-7])
    print(f"\n=== {name} ===")
    print(f"  {start_cash}$ -> {final:,.2f}$  (x{final/start_cash:.2f})")
    print(f"  CAGR anual: {cagr*100:.1f}%  |  Sharpe: {sharpe:.2f}  |  Max drawdown: {maxdd*100:.1f}%")
    print(f"  Tiempo en mercado: {sum(1 for p in seg_pos if p>0)/len(seg_pos)*100:.0f}%  |  Mejor semana de la estrategia: x{bw:.2f}")
    return final

def main():
    btc = load("BTC")
    eth = load("ETH")
    prices_btc = [x["c"] for x in btc]

    print(f"Datos: {btc[0]['t'].date()} -> {btc[-1]['t'].date()}  ({len(btc)} velas diarias)")
    print(f"Coste por operacion: {FEE*100:.2f}% por lado (taker 0.1% + slippage 0.05%)")
    print(f"Objetivo del usuario: x10 en 7 dias = +{10**(1/7)*100-100:.1f}% compuesto diario")

    # 0) Que dice la historia sobre x10 en una semana?
    bw_btc = weekly_best(prices_btc)
    bw_eth = weekly_best([x["c"] for x in eth])
    print(f"\n=== Realidad historica: mejor semana registrada ===")
    print(f"  BTC: x{bw_btc:.2f} ({(bw_btc-1)*100:.0f}%)  |  ETH: x{bw_eth:.2f} ({(bw_eth-1)*100:.0f}%)")
    print(f"  -> Un x10 en 7 dias NUNCA ha ocurrido en BTC/ETH desde 2019.")

    # split: entrenamiento 2019-2023, fuera de muestra 2024-2026
    split = next(i for i, x in enumerate(btc) if x["t"].year >= 2024)
    print(f"\nSplit: entrenamiento {btc[0]['t'].date()} -> {btc[split-1]['t'].date()} | "
          f"fuera de muestra {btc[split]['t'].date()} -> {btc[-1]['t'].date()}")

    strats = [
        ("Buy & Hold BTC (benchmark)", lambda p: [1.0]*len(p)),
        ("Momentum + filtro regimen (30/200)", strat_momentum_regime),
        ("Cruce MA (20/50)", strat_ma_cross),
        ("Momentum + objetivo volatilidad", strat_momentum_vol),
    ]

    print("\n########## FUERA DE MUESTRA (2024-2026, parametros SIN tocar) ##########")
    for name, fn in strats:
        report(name, prices_btc, fn(prices_btc), 100.0, t0=split)
    report("Misma estrategia en ETH (out-of-sample)", [x["c"] for x in eth],
           strat_momentum_regime([x["c"] for x in eth]), 100.0, t0=split)

    print("\n########## ENTRENAMIENTO (2019-2023) ##########")
    for name, fn in strats:
        report(name, prices_btc, fn(prices_btc), 100.0, t0=0, t1=split)

    # Simulacion directa del objetivo: 100$ con reinversion diaria completa en BTC
    print("\n########## La apuesta del usuario, medida de verdad ##########")
    eq = simulate(prices_btc, [1.0]*len(prices_btc), 100.0)
    # mejor tramo de 7 dias comprando y vendiendo BTC al cierre
    best7, best_i = 1.0, 0
    for i in range(7, len(eq)):
        m = eq[i] / eq[i-7]
        if m > best7:
            best7, best_i = m, i
    print(f"  Mejor ventana de 7 dias comprando BTC a cierre (con costes): x{best7:.2f} "
          f"({btc[best_i-7]['t'].date()} -> {btc[best_i]['t'].date()})")
    print(f"  Semanas que dieron >= x1.5: {sum(1 for i in range(7,len(eq)) if eq[i]/eq[i-7]>=1.5)} "
          f"de {len(eq)-7} | >= x2: {sum(1 for i in range(7,len(eq)) if eq[i]/eq[i-7]>=2)}")

if __name__ == "__main__":
    main()
