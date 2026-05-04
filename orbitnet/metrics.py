import csv
import math
from collections import deque
from dataclasses import dataclass, asdict

from config import NUM_SATELLITES
from physics import OrbitalMechanics


@dataclass
class FrameMetrics:
    sim_time: float
    active_links: int
    total_links: int
    packets_sent: int
    packets_delivered: int
    in_flight: int
    avg_latency_ms: float
    near_misses: int
    maneuvers: int
    min_separation_km: float
    delivery_rate_pct: float
    isl_util: tuple[float, ...]  # length NUM_SATELLITES, mean load on incident ISLs


def _per_satellite_isl_utilization(network) -> tuple[float, ...]:
    """Mean `current_load` on ISL edges incident to each satellite id 0..N-1."""
    loads: dict[int, list[float]] = {i: [] for i in range(NUM_SATELLITES)}
    for u, v, d in network.graph.edges(data=True):
        if d.get("kind") != "isl":
            continue
        load = float(d.get("current_load", 0.0))
        if isinstance(u, int) and 0 <= u < NUM_SATELLITES:
            loads[u].append(load)
        if isinstance(v, int) and 0 <= v < NUM_SATELLITES:
            loads[v].append(load)
    out: list[float] = []
    for i in range(NUM_SATELLITES):
        lst = loads[i]
        out.append(sum(lst) / len(lst) if lst else 0.0)
    return tuple(out)


class MetricsCollector:
    def __init__(self):
        self.history: list[FrameMetrics] = []
        self.total_maneuvers: int = 0
        self.total_near_misses: int = 0
        self.min_separation_km: float = math.inf
        self._last_near_miss_counts: dict[int, int] = {}
        self.chart_latency_ms: deque[float] = deque(maxlen=120)
        self.chart_near_misses: deque[int] = deque(maxlen=120)

    def update(self, sim_time: float, satellites: list, network) -> None:
        """Record one frame of metrics."""
        # Detect new near-misses
        for sat in satellites:
            prev = self._last_near_miss_counts.get(sat.sat_id, 0)
            if sat.near_miss_count > prev:
                self.total_near_misses += sat.near_miss_count - prev
                self._last_near_miss_counts[sat.sat_id] = sat.near_miss_count

        # Track minimum pairwise satellite separation
        for i, a in enumerate(satellites):
            for b in satellites[i + 1:]:
                d = OrbitalMechanics.distance_3d(a.position, b.position)
                if d < self.min_separation_km:
                    self.min_separation_km = d

        stats = network.get_network_stats()
        util = network.get_link_utilization()
        active = sum(1 for v in util.values() if v > 0.0)
        sent = stats["total_packets_sent"]
        delivered = stats["delivered"]
        rate = (delivered / sent * 100.0) if sent else 0.0
        isl_by_sat = _per_satellite_isl_utilization(network)

        self.history.append(FrameMetrics(
            sim_time=round(sim_time, 2),
            active_links=active,
            total_links=network.graph.number_of_edges(),
            packets_sent=sent,
            packets_delivered=delivered,
            in_flight=stats["in_flight"],
            avg_latency_ms=stats["avg_latency_ms"],
            near_misses=self.total_near_misses,
            maneuvers=self.total_maneuvers,
            min_separation_km=round(
                self.min_separation_km if self.min_separation_km < math.inf else 0.0, 2
            ),
            delivery_rate_pct=round(rate, 3),
            isl_util=isl_by_sat,
        ))

    def export_csv(self, path: str) -> None:
        if not self.history:
            return
        base_keys = [
            "sim_time", "active_links", "total_links", "packets_sent",
            "packets_delivered", "in_flight", "avg_latency_ms", "near_misses",
            "maneuvers", "min_separation_km", "delivery_rate_pct",
        ]
        isl_keys = [f"isl_u{i}" for i in range(NUM_SATELLITES)]
        fieldnames = base_keys + isl_keys
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for frame in self.history:
                row = {k: asdict(frame)[k] for k in base_keys}
                for i, v in enumerate(frame.isl_util):
                    row[f"isl_u{i}"] = round(v, 5)
                writer.writerow(row)
        print(f"  Metrics exported -> {path}")
