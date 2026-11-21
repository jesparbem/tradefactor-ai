# Mockups — TradeFactor AI (diseño UI)

Maquetas de alta fidelidad de la interfaz, **100 % autocontenidas** (un solo HTML, sin dependencias ni red). Servir con cualquier servidor estático:

```bash
cd mockups
python3 -m http.server 8090        # abre http://localhost:8090/index.html
```

## Pantallas

| Archivo | Contenido |
|---|---|
| `index.html` | **App navegable** — pestañas + switch claro/oscuro (la principal) |
| `screen1-portafolio.html` | Portafolio: valor, curva, distribución, tickers multi-mercado |
| `screen2-agentes.html` | War-room de los 8 agentes con su "qué estoy haciendo" |
| `screen3-simulaciones.html` | Escenarios de 100 € comparados |
| `screen4-mercado.html` | Activo con rupturas y consenso de la red |
| `screen5-alpha.html` | **Alpha en vivo**: lattice de probabilidad, grafo Mirofish, pulso |

> Estas maquetas usan datos ilustrativos. Las cifras reales salen del motor (`web/server.py`).