# TradeFactor AI

**A honest, multi-market AI investment simulator with a visible agent swarm, Mirofish future-scenario engine, and an Apple-clean dashboard. Research & paper-trading — built for the truth, not for hype.**

TradeFactor AI simulates what really happens to your money — with real historical data (crypto + stocks + commodities + FX), **real costs per market**, out-of-sample discipline against overfitting, and a team of **8 visible AI agents** (Researcher, Technician, ML Predictor, News, Examiner, Critic, Risk, Executor) that debate before any decision.

## What it does

- **Multi-market data** — Binance (crypto, real-time) + Yahoo Finance (stocks, commodities, FX). 2019→today, daily.
- **Honest backtest engine** — costs (0.08–0.15%/side), no look-ahead, train/test split. A strategy only counts if it beats buy & hold **out-of-sample**.
- **Agent swarm** — each agent publishes what it is doing (momentum, RSI/overbought, out-of-sample backtest, stress test, risk gate). Nothing executes without passing Critic + Risk.
- **Mirofish scenario engine** — forward-return distributions per asset, picks the scenario with the highest probability of success, and tells you entry / target / stop.
- **Historical sweep** — every asset × every strategy, out-of-sample, so you see what actually worked.
- **Apple-clean web UI** — light/dark theme, multi-market tickers, portfolio curves, and the "Alpha live" screen where you watch the agents think (probability lattice, relation graph, price pulse).
- **Paper-first execution** — designed around Alpaca (stocks) and Binance (crypto) via MCP. No real money until you decide.

## Quickstart

```bash
cd trading-sim
python3 -m venv .venv && .venv/bin/pip install pandas numpy yfinance

# 1) fetch data
.venv/bin/python multi_data.py          # crypto (Binance) + stocks/commodities/FX (Yahoo)
.venv/bin/python fetch_ia.py            # AI supply chain (chips + materials)

# 2) run the honest backtest + multi-asset portfolio
.venv/bin/python simcore.py
.venv/bin/python portsim.py

# 3) serve the web app (API: /api/simulate, /api/genetic, /api/portfolio, /api/scenarios, /api/rotate, /api/ia)
python3 web/server.py                   # http://localhost:8766
```

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/simulate` | simulate one strategy on one asset |
| `POST /api/genetic` | genetic search (train) + honest out-of-sample report |
| `POST /api/portfolio` | multi-asset portfolio (7 markets, 3 profiles) |
| `POST /api/scenarios` | Mirofish future scenarios + highest-probability pick |
| `POST /api/rotate` | daily-close rotation backtest (no look-ahead) |
| `GET /api/ia` | AI supply-chain sweep (chips + materials) |

## Honest disclaimer

TradeFactor AI is **not financial advice**. It reports what history says with costs included. In our data, **$100 → x10 in a week has never happened** in BTC/ETH since 2019, and a naive "maximize every close" daily-rotation **loses** (churn + costs). A platform that tells you the truth is worth more than one that sells you a dream.

## License

Apache-2.0