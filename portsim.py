#!/usr/bin/env python3
"""
Motor de cartera MULTI-ACTIVO (F0/F1 base).
Simula un portafolio de varios activos a la vez con reinversion total,
comisiones por mercado y rebalanceo periodico. Compara frente al benchmark
"comprar y mantener con peso igual".

Lo honesto de verdad: los resultados FUERA de muestra (2024->hoy) son los que
valen. Los de entrenamiento aparecen elegidos por la busqueda y suelen lucir
mejor de lo que luego hacen.
"""
import csv, math, os, statistics
from datetime import datetime, timezone

DATA = "/root/trading-sim/data"
FEE_DEFAULT = {"crypto": 0.0015, "stock": 0.0010, "commodity": 0.0010, "fx": 0.0008}

def load_any(sym):
    """Carga un CSV de la carpeta data/ (nombres: BTC_1d, GCF_1d, EURUSDX_1d, ...)."""
    name = sym.upper().replace("=", "")
    path = f"{DATA}/{name}_1d.csv"
    rows = []
    with open(path) as f:
        for x in csv.DictReader(f):
            rows.append({"t": datetime.fromtimestamp(int(x["open_time"]) / 1000, tz=timezone.utc),
                         "c": float(x["close"])})
    return rows

def market_of(sym):
    if sym in ("BTC", "ETH"):
        return "crypto"
    s = sym.upper()
    if "GC" in s or "CL" in s or "SI" in s:
        return "commodity"
    if "USD" in s and not s.startswith("USD"):
        return "fx"
    return "stock"

def align(universe):
    """Devuelve dates[] y P[sym][i] alineados por fecha (interseccion de dias)."""
    loads = []
    for sym in universe:
        rows = load_any(sym)
        loads.append((sym, {d.strftime("%Y-%m-%d"): c for d, c in [(r["t"], r["c"]) for r in rows]}))
    common = None
    for _sym, m in loads:
        ks = set(m.keys())
        common = ks if common is None else (common & ks)
    common = sorted(common)
    dates = [datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc) for d in common]
    P = {}
    for sym, m in loads:
        P[sym] = [m[d] for d in common]
    return dates, P

def portfolio_sim(dates, P, weights_fn, fees, start_cash=100.0, rebalance="monthly", split=None):
    """
    Simula cartera con rebalanceo a objetivo weights_fn(day_index) -> {sym: weight (fraccion relativa)}.
    Se rebalancea al final de cada periodo (mes). Entre periodos las posiciones
    se mueven con el precio (sin operar). Reinverte todo.
    Devuelve equity[] (uno por dia desde t>=1), y series. Los fees se aplican
    sobre el valor negociado en cada rebalanceo.
    """
    syms = list(P.keys())
    n = len(dates)
    # mapear fecha -> indice de rebalanceo (primer dia de cada mes)
    rb = set()
    for i, d in enumerate(dates):
        rb.add((d.year, d.month))
    rebalance_idx = {i: i for i in range(n) if (dates[i].year, dates[i].month) in rb and (i == 0 or (dates[i-1].year, dates[i-1].month) != (dates[i].year, dates[i].month))}
    rebalance_days = sorted(rb)
    rmap = {}
    for i in range(n):
        key = (dates[i].year, dates[i].month)
        rmap[i] = rebalance_days.index(key) if key in rebalance_days else None
    # inicio con efectivo
    cash = start_cash
    holdings = {s: 0.0 for s in syms}
    equity = []
    last_done_rebalance = -1
    for i in range(1, n):
        # si cambia el mes, rebalancear a primero de mes (i primo de mes)
        if rmap[i] is not None and rmap[i] != last_done_rebalance:
            target = weights_fn(i, dates, P)
            tot = math.fsum(holdings[s] * P[s][i] for s in syms) + cash
            # vender/cambiar hacia objetivo + cash residual
            cash = tot
            for s in syms:
                holdings[s] = 0.0
            for s, w in target.items():
                if w <= 0:
                    continue
                invest = tot * w
                fee = fees.get(s, 0.0015)
                holdings[s] = invest * (1 - fee) / P[s][i]
                cash -= invest
            last_done_rebalance = rmap[i]
        equity.append(math.fsum(holdings[s] * P[s][i] for s in syms) + cash)
    return equity

def metrics(equity, start_cash=100.0):
    if not equity:
        return None
    final = equity[-1]
    days = len(equity)
    years = days / 365.0
    cagr = (final / start_cash) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")
    er = [equity[i] / equity[i-1] - 1 for i in range(1, len(equity)) if equity[i-1] > 0]
    mean_r = statistics.mean(er) if er else 0.0
    sd = statistics.pstdev(er) if er else 0.0
    sharpe = mean_r / sd * math.sqrt(365) if sd > 0 else 0.0
    peak, maxdd = equity[0], 0.0
    for v in equity:
        peak = max(peak, v)
        maxdd = max(maxdd, (peak - v) / peak)
    bw = 1.0
    for i in range(7, len(equity)):
        bw = max(bw, equity[i] / equity[i-7])
    return {"final": round(final, 2), "multiple": round(final / start_cash, 3),
            "cagr": round(cagr, 4), "sharpe": round(sharpe, 2), "maxdd": round(maxdd, 3),
            "best7": round(bw, 3)}

def report(name, eq, start):
    m = metrics(eq, start)
    if not m:
        return
    col = "UP" if m["multiple"] >= 1 else "DOWN"
    print(f"  {name:34s} {start}$ -> {m['final']:>10,.2f}$ ({m['multiple']:+.3f}x)  Sharpe {m['sharpe']:>5}  DD {m['maxdd']*100:>5.1f}%  [{col}]")

if __name__ == "__main__":
    universe = ["BTC", "ETH", "NVDA", "SPY", "AAPL", "GC=F", "EURUSD=X"]
    fees = {s: FEE_DEFAULT[market_of(s)] for s in universe}
    dates, P = align(universe)
    print(f"Universe: {universe} ({len(dates)} dias alineados: {dates[0].date()} -> {dates[-1].date()})")
    print(f"Fees por mercado: {fees}")

    def eq_weight(_i, _d, _P):
        return {s: 1.0 / len(universe) for s in universe}

    def aggressive(_i, _d, _P):
        return {"BTC": 0.30, "ETH": 0.20, "NVDA": 0.20, "SPY": 0.15, "AAPL": 0.05, "GC=F": 0.10, "EURUSD=X": 0.0}

    def defensive(_i, _d, _P):
        return {"GC=F": 0.40, "SPY": 0.25, "AAPL": 0.05, "BTC": 0.10, "ETH": 0.05, "EURUSD=X": 0.10, "NVDA": 0.05}

    # split fuera de muestra
    split = next(i for i, d in enumerate(dates) if d.year >= 2024)

    print("\n== FUERA DE MUESTRA (2024 -> hoy, lo que importa) ==")
    print("   (rebasado a 100 € al entrar en 2024 — mide SOLO ese tramo, no lo acumulado desde 2019)")
    for name, wf in [("Peso igual (benchmark)", eq_weight),
                      ("Agresiva (cripto+tech)", aggressive),
                      ("Defensiva (oro+cobertura)", defensive)]:
        eq0 = portfolio_sim(dates, P, wf, fees, 100.0, split=split)
        eq_test = eq0[split - 1:]
        base = eq_test[0] if eq_test else 100.0
        eq_test_re = [v / base * 100.0 for v in eq_test] if eq_test else eq_test
        report(name + "  [test]", eq_test_re, 100.0)

    print("\n== ENTRENAMIENTO (2019-23) ==")
    for name, wf in [("Peso igual (benchmark)", eq_weight), ("Agresiva", aggressive), ("Defensiva", defensive)]:
        eq_train = portfolio_sim(dates, P, wf, fees, 100.0)[:split - 1]
        report(name + "  [train]", eq_train, 100.0)

    print("\n== RESUMEN honesto ==")
    print("  Con 100 € y 7 mercados a la vez, con costes y rebalanceo mensual, se compara ")
    print("  cada perfil (benchmark / agresiva / defensiva) en el tramo que importa (2024->hoy).")
    print("  Ninguna garantiza nada, pero aqui ves que dice la historia real con costes.")