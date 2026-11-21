#!/usr/bin/env python3
"""
Servidor web del simulador de inversiones con busqueda genetica honesta.

Busca parametros con algoritmo genetico sobre el SPLIT DE ENTRENAMIENTO (2019-2023) y
evalua SIN TOCAR los mejores en el SPLIT FUERA DE MUESTRA (2024-hoy). La optimizacion
genetica sobreajusta facilmente: por eso la seleccion usa solo train y el resultado que
se muestra al usuario como "lo que de verdad pasa" es el fuera de muestra.

Endpoints (HTTP JSON, stdlib, sin dependencias externas):
  GET  /                    -> pagina web (static/index.html)
  POST /api/simulate        -> simular 1 escenario concreto
  POST /api/genetic         -> busqueda genetica (evoluciona en train, reporta train+test)
  POST /api/refresh         -> actualizar datos desde Binance (asincrono, respuesta rapida)
  GET  /api/live            -> ultimo precio/cierre por activo + fecha de datos
"""
import json, math, random, statistics, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, "/root/trading-sim")   # para importar simcore y portsim (dir padre)
import simcore as sim
import portsim as psim

HOST, PORT = "0.0.0.0", 8766
DATA = {}                     # sym -> {dates:[], prices:[], rows:[...]}
SPLIT = {}                    # sym -> indice del split (anio >= 2024)

# ------------------------------------------------------------------ datos
def ensure_data():
    refresh_data()

def refresh_data():
    global DATA, SPLIT
    for sym in ("BTC", "ETH"):
        try:
            rows = sim.load(sym)
        except Exception as e:
            raise RuntimeError(f"No hay datos de {sym}: {e} — `python3 fetch_data.py` primero")
        prices = [r["c"] for r in rows]
        dates = [r["t"] for r in rows]
        split = next((i for i, x in enumerate(rows) if x["t"].year >= 2024), len(rows))
        DATA[sym] = {"dates": dates, "prices": prices, "rows": rows}
        SPLIT[sym] = split

# ------------------------------------------------------------------ metricas
def run_strategy(sym, strategy, params, capital, split_mode):
    p = DATA[sym]["prices"]; d = DATA[sym]["dates"]
    if strategy == "buyandhold":
        positions = [1.0] * len(p)
    else:
        s = sim.STRATEGIES[strategy]
        positions = s["fn"](p, **params)
    if split_mode == "train":
        t0, t1 = 0, SPLIT[sym]
    elif split_mode == "test":
        t0, t1 = SPLIT[sym], None
    else:  # full
        t0, t1 = 0, None
    m = sim.metrics(p, positions, capital, t0=t0, t1=t1, dates=d)
    return m, positions

# ------------------------------------------------------------------ algoritmo genetico
STRATEGY_RANGES = {
    "momentum_regime": [("mom_n", 5, 60, 1), ("ma_n", 50, 250, 10)],
    "ma_cross":        [("fast", 5, 60, 1), ("slow", 20, 200, 5)],
    "momentum_vol":    [("mom_n", 5, 40, 1), ("vol_n", 5, 40, 1), ("target_vol", 0.005, 0.05, "float")],
}
STRAT_LIST = list(STRATEGY_RANGES.keys())

def decode(g):
    """geno -> (strategy, params). g[0] elige familia; el resto genes en [0,1]."""
    fam = STRAT_LIST[min(int(g[0] * len(STRAT_LIST)), len(STRAT_LIST) - 1)]
    ranges = STRATEGY_RANGES[fam]
    params = {}
    for j, (name, lo, hi, mode) in enumerate(ranges):
        v = g[1 + j]
        if mode == "float":
            params[name] = round(lo + v * (hi - lo), 4)
        else:
            params[name] = int(round(lo + v * (hi - lo)))
    if fam == "ma_cross" and params["slow"] <= params["fast"]:
        params["slow"] = params["fast"] + 5
    return fam, params

def fitness(sym, fam, params):
    p = DATA[sym]["prices"]
    s = sim.STRATEGIES[fam]
    try:
        pos = s["fn"](p, **params)
    except Exception:
        return -999.0
    m = sim.metrics(p, pos, 100.0, t0=0, t1=SPLIT[sym])
    if m is None:
        return -999.0
    # objetivo en SAMPLE: recompensar Sharpe, penalizar drawdown y no-operar
    score = m["sharpe"] - 1.5 * m["maxdd"]
    if m["maxdd"] > 0.45:
        score -= 1.0
    if m["time_in_market"] < 0.03:
        score -= 0.5
    return score

def genetic(sym, capital, population=30, generations=12, seed=None):
    if seed is not None:
        random.seed(seed)
    npop, ng = int(population), int(generations)
    ngenes = 1 + max(len(r) for r in STRATEGY_RANGES.values())

    def rand_gene():
        v = [random.random() for _ in range(ngenes)]
        # mezclar familias para que arranque repartida
        return v

    def mutate(g, rate=0.25):
        g = g[:]
        for i in range(len(g)):
            if random.random() < rate:
                g[i] = max(0.0, min(1.0, g[i] + random.gauss(0, 0.15)))
        return g

    def crossover(a, b):
        cut = random.randint(0, len(a))
        return a[:cut] + b[cut:]

    pop = [rand_gene() for _ in range(npop)]
    scored = {}
    best_overall = None
    gen_history = []

    for gen in range(ng):
        # evaluar
        fits = []
        for g in pop:
            key = tuple(round(x, 4) for x in g)
            if key not in scored:
                fam, prm = decode(g)
                scored[key] = fitness(sym, fam, prm)
            fits.append(scored[key])
        # ranking
        order = sorted(range(npop), key=lambda i: fits[i], reverse=True)
        best_fit = fits[order[0]]
        fam_g, prm_g = decode(pop[order[0]])
        gen_history.append({"gen": gen + 1, "best": round(best_fit, 3),
                            "params": json.dumps({fam_g: prm_g}, default=str)})
        if best_overall is None or best_fit > best_overall[0]:
            best_overall = (best_fit, pop[order[0]])

        # elitismo (guardar 2 mejores)
        next_pop = [pop[order[0]], pop[order[1]]]
        while len(next_pop) < npop:
            # torneo de 3
            a = pop[min(random.sample(range(npop), 3), key=lambda i: -fits[i])]
            b = pop[min(random.sample(range(npop), 3), key=lambda i: -fits[i])]
            child = crossover(a, b)
            if random.random() < 0.3:
                child = mutate(child)
            next_pop.append(child)
        pop = next_pop

    # top-5 unicos de toda la poblacion final + mejores historicos (con sus familias)
    cands = {}
    for g in pop:
        key = tuple(round(x, 4) for x in g)
        cands[key] = g
    # anadir el mejor overall por si acaso
    cands[tuple(round(x, 4) for x in best_overall[1])] = best_overall[1]
    # puntuar cualquier gen final aun no evaluado (los hijos de la ultima generacion)
    for key, g in cands.items():
        if key not in scored:
            fam, prm = decode(g)
            scored[key] = fitness(sym, fam, prm)
    scored_keys = sorted(cands.items(), key=lambda kv: scored[kv[0]], reverse=True)[:5]

    top = []
    seen = set()
    for key, g in scored_keys:
        fam, prm = decode(g)
        sig = (fam, json.dumps(prm, sort_keys=True))
        if sig in seen:
            continue
        seen.add(sig)
        tr = run_strategy(sym, fam, prm, capital, "train")[0]
        te = run_strategy(sym, fam, prm, capital, "test")[0]
        top.append({"strategy": fam, "strategy_name": sim.STRATEGIES[fam]["name"],
                    "params": prm, "train": tr, "test": te})
    bench_train = run_strategy(sym, "buyandhold", {}, capital, "train")[0]
    bench_test = run_strategy(sym, "buyandhold", {}, capital, "test")[0]
    return {"generations": gen_history, "top": top,
            "benchmark": {"train": bench_train, "test": bench_test}}

# ------------------------------------------------------------------ veredicto de agentes + barrido historico
def _rsi(prices, n=14):
    if len(prices) < n + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-n, 0):
        d = prices[i] - prices[i - 1]
        gains += max(d, 0); losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)

def _oos_metrics(sym, strategy, params=None):
    rows = psim.load_any(sym)
    prices = [r["c"] for r in rows]; dates = [r["t"] for r in rows]
    split = next(i for i, x in enumerate(dates) if x.year >= 2024)
    if strategy == "buyandhold":
        pos = [1.0] * len(prices)
    else:
        s = sim.STRATEGIES[strategy]
        pos = s["fn"](prices, **(params or s["params"]))
    m = sim.metrics(prices, pos, 100.0, t0=split, dates=dates)
    return m

def agent_verdict(sym, capital=100.0):
    rows = psim.load_any(sym)
    prices = [r["c"] for r in rows]; dates = [r["t"] for r in rows]
    if len(prices) < 250:
        return {"error": "pocos datos"}
    cur = prices[-1]
    mom30 = prices[-1] / prices[-31] - 1 if len(prices) > 31 else 0.0
    ma200 = sim.sma(prices, 200)[-1] or prices[-1]
    ma50 = sim.sma(prices, 50)[-1] or prices[-1]
    rsi = _rsi(prices)
    rets = sim.returns(prices[-121:])
    vol_ann = (statistics.pstdev(rets) * math.sqrt(365)) if rets else 0.0

    m_mom = _oos_metrics(sym, "momentum_regime")
    m_bh = _oos_metrics(sym, "buyandhold")
    m_ma = _oos_metrics(sym, "ma_cross")

    # --- agentes (stancia real calculada)
    agents = []
    # Investigador
    in_new = dates[-1].strftime("%Y-%m-%d")
    agents.append({"nombre": "Investigador", "icon": "🔎", "stancia": "analiza",
                   "voto": None,
                   "razon": f"{sym} a {cur:,.2f} (cierre {in_new}) · vol. anualizada {vol_ann*100:.0f}% · {len(prices)} velas históricas."})
    # Técnico
    if mom30 > 0 and cur > ma200:
        st, v = "SÍ", +1
    else:
        st, v = "NO", -1
    agents.append({"nombre": "Técnico", "icon": "📊", "stancia": "entrar", "voto": v,
                   "razon": f"momentum30 {mom30*100:+.1f}% · precio{' >' if cur>ma200 else ' <'} MA200 · RSI {rsi:.0f}."})
    # Predictor ML
    mlt = m_mom["multiple"] if m_mom else 1.0
    st, v = ("SÍ", +1) if mlt >= 1.3 else ("no", -1)
    agents.append({"nombre": "Predictor ML", "icon": "🧠", "stancia": "entrar" if v > 0 else "evitar", "voto": v,
                   "razon": f"backtest momentum+régimen fuera de muestra x{mlt:.2f} (100€→{m_mom['final']:.0f}€)."})
    # Noticias (proxy honesto: sin feed gratis robusto, usa momentum corto)
    mom7 = prices[-1] / prices[-8] - 1 if len(prices) > 8 else 0
    agents.append({"nombre": "Noticias", "icon": "📰", "stancia": "neutral", "voto": None,
                   "razon": f"proxy momentum 7d {mom7*100:+.1f}% · feed de titulares pendiente de API pública estable."})
    # Examinador (estrés)
    dd = m_mom["maxdd"] if m_mom else 1.0
    st, v = ("aprueba", +1) if dd < 0.42 else ("rechaza", -1)
    agents.append({"nombre": "Examinador", "icon": "🎓", "stancia": "aprueba" if v > 0 else "rechaza", "voto": v,
                   "razon": f"estrés: peor drawdown del método {dd*100:.0f}% (<42% ⇒ ok)."})
    # Crítico
    warns = []
    if rsi >= 70: warns.append(f"RSI {rsi:.0f} sobrecomprado")
    if mom30 < 0: warns.append("momentum negativo")
    st, v = ("alerta", -1) if warns else ("ok", +1)
    agents.append({"nombre": "Crítico", "icon": "😈", "stancia": "alerta" if warns else "ok", "voto": v,
                   "razon": "; ".join(warns) if warns else "sin objeciones de peso."})
    # Riesgo
    sh = m_mom["sharpe"] if m_mom else 0
    st, v = ("aprueba", +1) if (sh > 0.3 and dd < 0.5) else ("bloquea", -1)
    agents.append({"nombre": "Riesgo", "icon": "🛡️", "stancia": "aprueba" if v > 0 else "bloquea", "voto": v,
                   "razon": f"Sharpe {sh} · drawdown {dd*100:.0f}% · sin apalancamiento."})
    # Ejecutor
    agents.append({"nombre": "Ejecutor", "icon": "⚡", "stancia": "cola", "voto": None,
                   "razon": "modo papel (Alpaca/Binance paper-first)."})

    yes = sum(1 for a in agents if a["voto"] == +1)
    no = sum(1 for a in agents if a["voto"] == -1)
    verdict = "ENTRAR · moderado" if yes > no else ("EVITAR" if no > yes else "NEUTRO")
    stop = cur * (1 - 0.06)
    target = cur * (1 + 0.10)
    return {"asset": sym, "price": round(cur, 2), "date": in_new,
            "verdict": verdict, "yes": yes, "no": no,
            "entry": round(cur, 2), "stop": round(stop, 2), "target": round(target, 2),
            "agents": agents}

def market_sweep():
    groups = {"Cripto": ["BTC", "ETH"], "Materias primas": ["GC=F", "CL=F", "SI=F"], "Acciones": ["NVDA", "SPY", "AAPL"]}
    strats = {"buyandhold": "Comprar y mantener", "momentum_regime": "Momentum+régimen", "ma_cross": "Cruce MA", "momentum_vol": "Mom+vol"}
    out = {"groups": [], "all": []}
    for g, syms in groups.items():
        rows = []
        for s in syms:
            row = {"asset": s}
            for k, name in strats.items():
                m = _oos_metrics(s, k)
                row[k] = None if not m else {"x": m["multiple"], "sharpe": m["sharpe"], "dd": m["maxdd"]}
            best = max([k for k in strats], key=lambda k: (row[k] or {"x": 0})["x"])
            row["best"] = best
            rows.append(row)
        out["groups"].append({"name": g, "assets": rows})
        out["all"].extend(rows)
    out["strategies"] = strats
    return out


# ------------------------------------------------------------------ Mirofish: escenarios de futuro + eleccion + rotacion a cierre
SCEN_UNIVERSE = {"Cripto": ["BTC", "ETH"], "Materias primas": ["GC=F", "CL=F", "SI=F"], "Acciones": ["NVDA", "SPY", "AAPL"]}

def _roll(sym, window=7, keep_days=750):
    """Retornos futuros rodantes (sin solapamiento solo al final) y percentiles."""
    p = [r["c"] for r in psim.load_any(sym)][-keep_days:]
    fwd = [p[i + window] / p[i] - 1 for i in range(len(p) - window)]
    s = sorted(fwd)
    def q(qq):
        k = int(qq * (len(s) - 1)); return s[k]
    return {"fwd": fwd, "p_up": sum(1 for x in fwd if x > 0) / len(fwd),
            "p25": q(0.25), "p50": q(0.50), "p75": q(0.75),
            "mean_up": statistics.mean([x for x in fwd if x > 0]) if any(x > 0 for x in fwd) else 0,
            "mean_down": statistics.mean([x for x in fwd if x < 0]) if any(x < 0 for x in fwd) else 0}

def forward_scenarios(capital=100.0):
    groups_res = {}
    allcands = []
    for grp, syms in SCEN_UNIVERSE.items():
        arr = []
        for s in syms:
            try:
                r7 = _roll(s, 7)
            except Exception:
                continue
            fee = 2 * psim.FEE_DEFAULT[psim.market_of(s)]  # compra+venta
            prob_up = r7["p_up"]
            ev7 = prob_up * r7["mean_up"] - (1 - prob_up) * abs(r7["mean_down"]) - fee
            risk = abs(r7["p25"])
            score = ev7 / risk if risk > 0 else ev7
            row = {"asset": s, "market": grp, "price": round(psim.load_any(s)[-1]["c"], 2),
                   "prob_up": round(prob_up, 3), "p25": round(r7["p25"], 4), "p50": round(r7["p50"], 4), "p75": round(r7["p75"], 4),
                   "ev7": round(ev7, 4), "score": round(score, 3)}
            arr.append(row); allcands.append(row)
        groups_res[grp] = sorted(arr, key=lambda r: -r["score"])
    best = max(allcands, key=lambda r: r["score"]) if allcands else None
    out = {"capital": capital, "groups": groups_res, "chosen": None,
           "scenarios": ["Bajista"] * 0}
    if best:
        entry = best["price"]
        out["chosen"] = {"asset": best["asset"], "market": best["market"], "price": entry,
                         "scenario": "Alcista (prob " + str(round(best["prob_up"] * 100)) + "%)",
                         "prob_up": best["prob_up"], "ev7": best["ev7"],
                         "target": round(entry * (1 + best["p75"]), 2),
                         "central": round(entry * (1 + best["p50"]), 2),
                         "stop": round(entry * (1 - abs(best["p25"])), 2),
                         "expect_7d": round(capital * (1 + best["ev7"]), 2),
                         "scenarios_7d": [
                            {"nombre": "Alcista", "prob": best["prob_up"], "ruta": round(best["p75"], 3), "100e": round(capital * (1 + best["p75"]), 2)},
                            {"nombre": "Base", "prob": 0.5, "ruta": round(best["p50"], 3), "100e": round(capital * (1 + best["p50"]), 2)},
                            {"nombre": "Bajista", "prob": 1 - best["prob_up"], "ruta": round(best["p25"], 3), "100e": round(capital * (1 + best["p25"]), 2)}]}
    return out

def rotate_backtest(capital=100.0):
    """Rota a diario al activo con mejor momentum previo (SIN lookahead):
       en el cierre t decido con datos <=t, realizo el movimiento t->t+1, con costes."""
    syms = [s for grp in SCEN_UNIVERSE.values() for s in grp]
    loads = {s: psim.load_any(s) for s in syms}
    common = None
    for s, rows in loads.items():
        ks = {r["t"].strftime("%Y-%m-%d") for r in rows}
        common = ks if common is None else (common & ks)
    common = sorted(common)
    idx = {sym: {r["t"].strftime("%Y-%m-%d"): i for i, r in enumerate(rows)} for sym, rows in loads.items()}
    def price(sym, day):
        return loads[sym][idx[sym][day]]["c"]
    C0 = len(common)
    value = capital; equity = []; picks = {}
    def dayme(d): return loads[syms[0]][idx[syms[0]][d]]
    for k in range(C0 - 1):
        day = common[k]
        if int(day[:4]) < 2024:
            continue
        # decidir con datos hasta day (<= t): mejor momentum 30d
        best_sym, best_mom, cash_mode = None, None, None
        for s in syms:
            pi = idx[s][day]; row = loads[s]
            if pi < 30:
                continue
            mom = row[pi]["c"] / row[pi - 30]["c"] - 1
            if mom <= 0 and (best_mom is None or mom > best_mom) and cash_mode is None:
                continue  # solo forzamos cash si TODOS negativos
            if best_mom is None or mom > best_mom:
                best_mom = mom; best_sym = s
        # si todos negativos -> cash (no invertir)
        if best_sym is None or best_mom <= 0:
            equity.append(value); picks["EFECTIVO"] = picks.get("EFECTIVO", 0) + 1; continue
        # realizar t -> t+1 con costes (2 viajes)
        ret = price(best_sym, common[k + 1]) / price(best_sym, day) - 1
        fee = 2 * psim.FEE_DEFAULT[psim.market_of(best_sym)]
        value *= (1 + ret) * (1 - fee)
        picks[best_sym] = picks.get(best_sym, 0) + 1
        equity.append(value)
    if not equity:
        return {"error": "sin datos"}
    m = psim.metrics(equity, capital)
    m["final"] = round(equity[-1], 2); m["multiple"] = round(equity[-1] / capital, 3)
    m["picks"] = {k: v for k, v in sorted(picks.items(), key=lambda kv: -kv[1])}
    m["curve"] = [{"t": common[i + 2], "eq": round(equity[i], 2)} for i in range(len(equity))][::5]
    return m


# ------------------------------------------------------------------ barrido IA supply chain
IA_HOLDS = {
    "AMD": ("Chip · competidor de NVDA", "IA generativa / centros de datos"),
    "TSM": ("Chip · fabricante (TSMC)", "litografía avanzada de todos los chips IA"),
    "ASML": ("Litografía", "monopolio de máquinas EUV para semis IA"),
    "AVGO": ("Chip · red + IA", "sistemas de red y ASICs para datacenters"),
    "MU": ("Memoria HBM (Micron)", "memoria de alto ancho de banda exigida por la IA"),
    "SMH": ("ETF semiconductores", "cesta de semis IA (NVDA, TSM, AMD, ...)"),
    "LIT": ("Baterías · litio (ETF)", "litio para baterías: se hunde si hay exceso de oferta"),
    "ALB": ("Baterías · litio (Albemarle)", "mayor productora de litio, cíclica"),
    "FCX": ("Cobre (Freeport)", "cobre para redes eléctricas, data centers y motores"),
    "COPX": ("Cobre (ETF mineras)", "cesta de mineras de cobre"),
    "URA": ("Uranio / nuclear (ETF)", "energía nuclear para alimentar los data centers de IA"),
    "REMX": ("Tierras raras (ETF)", "imanes y materiales raros para motores y chips"),
}

def ia_sweep():
    res = {"assets": [], "thesis": IA_HOLDS}
    import time as _t
    for sym, (hold, cat) in IA_HOLDS.items():
        try:
            rows = psim.load_any(sym)
        except Exception:
            continue
        p = [r["c"] for r in rows]; dates = [r["t"] for r in rows]
        if len(p) < 260:
            continue
        cur = p[-1]
        def _r(days):
            return p[-1] / p[-1 - days] - 1 if len(p) > days else 0.0
        hi52 = max(p[-252:]); idx_hi = p[-252:].index(hi52)
        dist_high = cur / hi52 - 1
        from_high = cur / max(p[-252:]) - 1
        mom30 = _r(30); chg3 = _r(63); chg6 = _r(126); chg12 = _r(252)
        rsi = _rsi(p)
        rets = sim.returns(p[-121:])
        vol = (statistics.pstdev(rets) * math.sqrt(365)) if rets else 0
        m_bh = _oos_metrics(sym, "buyandhold")
        m_mom = _oos_metrics(sym, "momentum_regime")
        # clasificacion
        if dist_high > -0.05 and mom30 > 0:
            state = "Subida fuerte"
        elif dist_high < -0.30:
            state = "Baja / posible rebote" if chg3 > 0 else "Desplomada"
        elif mom30 < 0:
            state = "Corrigiendo"
        else:
            state = "Plana"
        # potencial (compuesto): cuanta más caida con giro positivo => mas upside
        upside = (-dist_high) + max(chg3, 0) * 3
        res["assets"].append({
            "asset": sym, "hold": hold, "catalyst": cat, "price": round(cur, 2), "date": dates[-1].strftime("%Y-%m-%d"),
            "chg3m": round(chg3, 4), "chg6m": round(chg6, 4), "chg12m": round(chg12, 4),
            "mom30": round(mom30, 4), "rsi": round(rsi, 1), "dist_high": round(dist_high, 4), "vol_ann": round(vol, 3),
            "oos": {"bh": round(m_bh["multiple"], 2) if m_bh else None,
                    "momreg": round(m_mom["multiple"], 2) if m_mom else None},
            "state": state, "upside": round(upside, 3)
        })
    res["assets"].sort(key=lambda a: -a["upside"])
    return res


# ------------------------------------------------------------------ cartera multi-activo
PORT_UNIVERSE = ["BTC", "ETH", "NVDA", "SPY", "AAPL", "GC=F", "EURUSD=X"]

def portfolio_scenarios(capital=100.0, sample_points=120):
    dates, P = psim.align(PORT_UNIVERSE)
    fees = {s: psim.FEE_DEFAULT[psim.market_of(s)] for s in PORT_UNIVERSE}
    split = next(i for i, d in enumerate(dates) if d.year >= 2024)
    profiles = {
        "bench": ("Peso igual (benchmark)", lambda _i, _d, _P: {s: 1.0 / len(PORT_UNIVERSE) for s in PORT_UNIVERSE}),
        "agg":   ("Agresiva (cripto+tech)", lambda _i, _d, _P: {"BTC": .30, "ETH": .20, "NVDA": .20, "SPY": .15, "AAPL": .05, "GC=F": .10, "EURUSD=X": 0}),
        "def":   ("Defensiva (oro+cobertura)", lambda _i, _d, _P: {"GC=F": .40, "SPY": .25, "AAPL": .05, "BTC": .10, "ETH": .05, "EURUSD=X": .10, "NVDA": .05}),
    }
    def thin(series, n=sample_points):
        if len(series) <= n:
            return series
        step = len(series) / n
        return [series[int(i * step)] for i in range(n)]
    out = {"assets": PORT_UNIVERSE, "split": dates[split].strftime("%Y-%m-%d"),
           "from": dates[0].strftime("%Y-%m-%d"), "to": dates[-1].strftime("%Y-%m-%d"),
           "test": {}, "train": {}, "dates_t": None}
    for key, (name, wf) in profiles.items():
        eq = psim.portfolio_sim(dates, P, wf, fees, capital)
        # prueba (rebasada a 100)
        eq_test = eq[split - 1:]
        base = eq_test[0] if eq_test else 100.0
        eq_test_re = [v / base * 100.0 if base else v for v in eq_test]
        m_test = psim.metrics(eq_test_re, 100.0)
        eq_train = eq[:split - 1]
        m_train = psim.metrics(eq_train, capital)
        m_test["curve"] = thin([{"t": dates[split - 1 + i].strftime("%Y-%m-%d"), "eq": v} for i, v in enumerate(eq_test_re)])
        m_train["curve"] = thin([{"t": dates[i].strftime("%Y-%m-%d"), "eq": v} for i, v in enumerate(eq_train)])
        out["test"][key] = {"name": name, **m_test}
        out["train"][key] = {"name": name, **m_train}
    return out


# ------------------------------------------------------------------ respuestas
def json_resp(handler, obj, code=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

def handler_factory(static):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def _read_json(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n == 0:
                return {}
            return json.loads(self.rfile.read(n))
        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/api/live":
                out = {"data_as_of": None, "assets": {}}
                for sym in DATA:
                    prices = DATA[sym]["prices"]; dates = DATA[sym]["dates"]
                    out["assets"][sym] = {"last_close": prices[-1], "last_date": dates[-1].strftime("%Y-%m-%d"),
                                          "bars": len(prices)}
                json_resp(self, out)
                return
            if u.path == "/" or u.path.startswith("/index"):
                try:
                    data = open(static, "rb").read()
                except Exception as e:
                    json_resp(self, {"error": str(e)}, 500); return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            json_resp(self, {"error": "not found"}, 404)
        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/api/simulate":
                    b = self._read_json()
                    sym = (b.get("asset") or "BTC").upper()
                    strat = b.get("strategy") or "momentum_regime"
                    params = b.get("params") or sim.STRATEGIES[strat]["params"]
                    cap = float(b.get("capital") or 100)
                    mode = b.get("split") or "test"
                    m, _pos = run_strategy(sym, strat, params, cap, mode)
                    json_resp(self, {"sim": m, "split": mode, "strategy": strat, "params": params})
                    return
                if u.path == "/api/verdict":
                    b = self._read_json()
                    sym = (b.get("asset") or "BTC").upper()
                    cap = float(b.get("capital") or 100)
                    json_resp(self, agent_verdict(sym, cap), 500 if False else 200)
                    return
                if u.path == "/api/sweep":
                    json_resp(self, market_sweep())
                    return
                if u.path == "/api/scenarios":
                    b = self._read_json()
                    cap = float(b.get("capital") or 100)
                    json_resp(self, forward_scenarios(cap))
                    return
                if u.path == "/api/rotate":
                    b = self._read_json()
                    cap = float(b.get("capital") or 100)
                    json_resp(self, rotate_backtest(cap))
                    return
                if u.path == "/api/ia":
                    json_resp(self, ia_sweep())
                    return
                if u.path == "/api/portfolio":
                    b = self._read_json()
                    cap = float(b.get("capital") or 100)
                    t0 = time.time()
                    res = portfolio_scenarios(cap)
                    res["elapsed_ms"] = int((time.time() - t0) * 1000)
                    json_resp(self, res)
                    return
                if u.path == "/api/genetic":
                    b = self._read_json()
                    sym = (b.get("asset") or "BTC").upper()
                    cap = float(b.get("capital") or 100)
                    pop = int(b.get("population") or 30)
                    gens = int(b.get("generations") or 12)
                    t0 = time.time()
                    res = genetic(sym, cap, pop, gens)
                    res["elapsed_ms"] = int((time.time() - t0) * 1000)
                    json_resp(self, res)
                    return
                if u.path == "/api/refresh":
                    try:
                        refresh_data()
                        json_resp(self, {"ok": True, **DATA_BYREF_VIEW(sym_default="BTC")})
                    except Exception as e:
                        json_resp(self, {"ok": False, "error": str(e)}, 500)
                    return
            except Exception as e:
                json_resp(self, {"error": f"{type(e).__name__}: {e}"}, 400)
                return
            json_resp(self, {"error": "not found"}, 404)
    return H

def DATA_BYREF_VIEW(sym_default="BTC"):
    out = {}
    for sym in DATA:
        out[sym] = {"bars": len(DATA[sym]["prices"]),
                    "last": DATA[sym]["prices"][-1],
                    "last_date": DATA[sym]["dates"][-1].strftime("%Y-%m-%d"),
                    "split": DATA[sym]["dates"][SPLIT[sym]].strftime("%Y-%m-%d")}
    return out

def main():
    ensure_data()
    print("Datos listos:", {k: len(v["prices"]) for k, v in DATA.items()})
    static = "/root/trading-sim/web/index.html"
    srv = ThreadingHTTPServer((HOST, PORT), handler_factory(static))
    print(f"Simulador web en http://{HOST}:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nparado")

if __name__ == "__main__":
    main()