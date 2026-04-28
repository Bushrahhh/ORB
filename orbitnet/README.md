# OrbitNet — LEO constellation as a Content-Centric Network (CCN)

OrbitNet is an interactive simulation and demo for a **Walker-style LEO constellation** (12 satellites, 3 orbital planes) operating as a **delay-tolerant, graph-routed network** with **autonomous collision-avoidance agents**. It is built for coursework and live presentation: a 60fps pygame view, live metrics, packet animation, and optional **chaos mode** stress testing.

## What the simulation models

- **Orbital layer:** Circular LEO orbits (~550 km altitude), multiple planes with RAAN spacing, analytic position/velocity, optional debris and **intercept debris** in chaos mode.
- **Network layer:** Satellites and ground stations form a **time-varying graph**: ISL edges appear when in range; **Dijkstra routing** minimizes **propagation delay** (distance / *c*). Packets queue with per-link **load** and decay, producing **congestion** on hot links.
- **Agent layer:** Each satellite runs a **finite-state machine** (nominal → warning → maneuvering → safe) with **decentralized** threat sensing, **telemetry**, and **collision-alert** traffic toward the ground segment.

## CCN concepts demonstrated

| Concept | Where it shows up |
|--------|-------------------|
| **Graph topology** | ISL edges rebuilt from geometry; mini topology panel and main view. |
| **Dynamic routing** | Shortest-delay paths when topology changes; animated packets along paths. |
| **Packet switching** | Typed packets (telemetry, alerts); hops, latency, delivery stats. |
| **Propagation delay** | Edge weights from physical range; latency metrics. |
| **Congestion** | `current_load` on links; link color and “congested” counts. |
| **ISL links** | Range-limited satellite–satellite edges; utilization logged for analysis heatmaps. |

## ABM (agent-based modeling) concepts

| Concept | Where it shows up |
|--------|-------------------|
| **Autonomous agents** | One agent per satellite + non-cooperative debris. |
| **State machines** | `NOMINAL` / `WARNING` / `MANEUVERING` / `SAFE` with explicit transitions. |
| **Emergent avoidance** | Local sensing + burns; global pattern from many local decisions. |
| **Decentralized coordination** | No central orchestrator; alerts and telemetry share state via the network. |

## How to run

```bash
cd orbitnet
pip install -r requirements.txt
python main.py
```

Optional non-graphical checks:

```bash
python main.py --verify
```

### Controls

| Key / action | Effect |
|--------------|--------|
| **SPACE** | Pause / resume |
| **+** / **-** | Increase / decrease simulation speed |
| **C** | Toggle **chaos mode** (periodic intercept debris bursts + dashboard indicator) |
| **G** | Export `results.csv`, run `analysis.py`, open `results_analysis.png` |
| **Click** satellite (left view) | Popup: id, state, position (km), velocity (km/s), messages, near misses, ISL neighbors, in-flight queue depth |
| **R** | Reset simulation |
| **Q** or **ESC** | Quit (metrics are written to `results.csv` on exit) |

## Analysis output

After running, `results.csv` holds time series of link activity, latency, near misses, maneuvers, per-satellite ISL utilization snapshots, and delivery rate. Press **G** or run:

```bash
python analysis.py
```

This writes **`results_analysis.png`**: a 2×2 dark-theme figure (near misses & maneuvers, average latency, ISL utilization heatmap, delivery rate).

## Project layout

- `main.py` — Main loop, chaos injection, input, metrics export.
- `physics.py` — Orbital mechanics.
- `agents.py` — Satellites, debris, chaos intercept debris.
- `network.py` — Graph, ISLs, uplinks, packets in flight.
- `routing.py` — Dijkstra / ground-station paths.
- `packets.py` — Packet types.
- `metrics.py` — CSV history.
- `analysis.py` — Matplotlib figures.
- `ui/renderer.py` — Starfield, orbit view, packets, selection popup, collision flash.
- `ui/dashboard.py` — Side panel metrics and topology.

## Requirements

Python 3.10+ recommended; `pygame-ce`, `networkx`, `numpy`, `pandas`, `matplotlib` (see `requirements.txt`).
