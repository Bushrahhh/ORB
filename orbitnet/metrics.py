import csv
import math
from dataclasses import dataclass, asdict

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


class MetricsCollector:
    def __init__(self):
        self.history: list[FrameMetrics] = []
        self.total_maneuvers: int = 0
        self.total_near_misses: int = 0
        self.min_separation_km: float = math.inf
        self._last_near_miss_counts: dict[int, int] = {}

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

        self.history.append(FrameMetrics(
            sim_time=round(sim_time, 2),
            active_links=active,
            total_links=network.graph.number_of_edges(),
            packets_sent=stats["total_packets_sent"],
            packets_delivered=stats["delivered"],
            in_flight=stats["in_flight"],
            avg_latency_ms=stats["avg_latency_ms"],
            near_misses=self.total_near_misses,
            maneuvers=self.total_maneuvers,
            min_separation_km=round(
                self.min_separation_km if self.min_separation_km < math.inf else 0.0, 2
            ),
        ))

    def export_csv(self, path: str) -> None:
        if not self.history:
            return
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(asdict(self.history[0]).keys()))
            writer.writeheader()
            for frame in self.history:
                writer.writerow(asdict(frame))
        print(f"  Metrics exported → {path}")
