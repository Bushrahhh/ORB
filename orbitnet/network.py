import math
import networkx as nx

from config import ISL_MAX_RANGE_KM, EARTH_RADIUS_KM
from physics import OrbitalMechanics
from routing import RoutingEngine

# Speed of light in km/ms
_C_KM_MS = 299_792.458 / 1_000.0

# Ground stations: (label, lat_deg, lon_deg) — equator, 180° apart
_GROUND_STATIONS = [
    ("GS0",  0.0,   0.0),
    ("GS1",  0.0, 180.0),
]

# Bandwidth and load constants
_BANDWIDTH_MBPS = 100.0
_CONGESTION_THRESHOLD = 0.7


def _gs_ecef(lat_deg: float, lon_deg: float) -> tuple[float, float, float]:
    """Ground station position on Earth's surface (ECEF, km)."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    r = EARTH_RADIUS_KM
    return (r * math.cos(lat) * math.cos(lon),
            r * math.cos(lat) * math.sin(lon),
            r * math.sin(lat))


class ConstellationNetwork:
    def __init__(self):
        self.graph = nx.Graph()
        self._packet_queue: list = []
        self._in_flight: list = []      # (packet, remaining_delay_ms)

        # Stats
        self.total_packets_sent = 0
        self.total_delivered = 0
        self._latencies: list[float] = []

        # Add ground station nodes (fixed)
        for label, lat, lon in _GROUND_STATIONS:
            self.graph.add_node(label, pos=_gs_ecef(lat, lon), kind="ground")

    # ------------------------------------------------------------------
    # Topology management
    # ------------------------------------------------------------------

    def update_topology(self, positions: dict) -> None:
        """
        Rebuild ISL edges each tick from current satellite positions.
        positions: {sat_id: (x, y, z)}  (includes all sats + debris)
        Only satellite integers ≥ 0 participate in ISLs.
        """
        sat_ids = [k for k in positions if isinstance(k, int) and k >= 0]

        # Ensure sat nodes exist
        for sid in sat_ids:
            if not self.graph.has_node(sid):
                self.graph.add_node(sid, kind="satellite")
            self.graph.nodes[sid]["pos"] = positions[sid]

        # Remove stale satellite nodes
        stale = [n for n in self.graph.nodes
                 if isinstance(n, int) and n not in sat_ids]
        self.graph.remove_nodes_from(stale)

        # Remove all ISL edges; rebuild from scratch
        isl_edges = [(u, v) for u, v, d in self.graph.edges(data=True)
                     if d.get("kind") == "isl"]
        self.graph.remove_edges_from(isl_edges)

        # Add edges for satellite pairs within range
        for i, a in enumerate(sat_ids):
            for b in sat_ids[i + 1:]:
                dist = OrbitalMechanics.distance_3d(positions[a], positions[b])
                if dist <= ISL_MAX_RANGE_KM:
                    delay = dist / _C_KM_MS
                    self.graph.add_edge(
                        a, b,
                        kind="isl",
                        distance_km=dist,
                        propagation_delay_ms=delay,
                        bandwidth_mbps=_BANDWIDTH_MBPS,
                        current_load=0.0,
                    )

        # Ground station ↔ nearest 2 satellites
        for label, _, _ in _GROUND_STATIONS:
            gs_pos = self.graph.nodes[label]["pos"]
            # Remove old GS edges
            old_gs = list(self.graph.edges(label))
            self.graph.remove_edges_from(old_gs)

            ranked = sorted(
                sat_ids,
                key=lambda s: OrbitalMechanics.distance_3d(gs_pos, positions[s])
            )
            for sid in ranked[:2]:
                dist = OrbitalMechanics.distance_3d(gs_pos, positions[sid])
                delay = dist / _C_KM_MS
                self.graph.add_edge(
                    label, sid,
                    kind="uplink",
                    distance_km=dist,
                    propagation_delay_ms=delay,
                    bandwidth_mbps=_BANDWIDTH_MBPS,
                    current_load=0.0,
                )

    # ------------------------------------------------------------------
    # Packet handling
    # ------------------------------------------------------------------

    def send_packet(self, packet) -> bool:
        """Route packet via Dijkstra and enqueue for delivery."""
        path = RoutingEngine.dijkstra_path(
            self.graph, packet.source, packet.destination
        )
        if not path:
            return False

        packet.path = path[:]
        self.total_packets_sent += 1
        # Compute total path delay
        total_delay = sum(
            self.graph[path[i]][path[i + 1]].get("propagation_delay_ms", 0.0)
            for i in range(len(path) - 1)
        )
        self._in_flight.append([packet, total_delay, total_delay])  # [pkt, remaining_ms, total_ms]

        # Increment load on each edge
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if self.graph.has_edge(u, v):
                bw = self.graph[u][v].get("bandwidth_mbps", _BANDWIDTH_MBPS)
                load_delta = (packet.size_bytes * 8 / 1e6) / bw
                self.graph[u][v]["current_load"] = min(
                    1.0,
                    self.graph[u][v]["current_load"] + load_delta
                )
        return True

    def tick(self, dt: float) -> None:
        """
        Advance in-flight packets by dt simulation-seconds.
        Deliver packets whose accumulated delay has elapsed.
        """
        dt_ms = dt * 1000.0
        still_flying = []
        for entry in self._in_flight:
            pkt, remaining, total = entry
            remaining -= dt_ms
            if remaining <= 0.0:
                pkt.delivered_at = pkt.created_at + (
                    sum(
                        self.graph[pkt.path[i]][pkt.path[i + 1]].get(
                            "propagation_delay_ms", 0.0
                        )
                        for i in range(len(pkt.path) - 1)
                        if self.graph.has_edge(pkt.path[i], pkt.path[i + 1])
                    ) / 1000.0
                )
                pkt.hops = len(pkt.path) - 1
                self.total_delivered += 1
                if pkt.latency_ms is not None:
                    self._latencies.append(pkt.latency_ms)
            else:
                entry[1] = remaining
                still_flying.append(entry)

        self._in_flight = still_flying

        # Decay link load each tick
        for u, v in self.graph.edges():
            if self.graph[u][v].get("current_load", 0.0) > 0:
                self.graph[u][v]["current_load"] = max(
                    0.0, self.graph[u][v]["current_load"] - 0.05 * dt
                )

    # ------------------------------------------------------------------
    # Stats / queries
    # ------------------------------------------------------------------

    @property
    def in_flight_packets(self) -> list:
        """List of (packet, progress_0_to_1) for animation."""
        out = []
        for pkt, remaining, total in self._in_flight:
            progress = 1.0 - remaining / total if total > 0 else 0.0
            out.append((pkt, max(0.0, min(1.0, progress))))
        return out

    def get_link_utilization(self) -> dict:
        return {
            (u, v): self.graph[u][v].get("current_load", 0.0)
            for u, v in self.graph.edges()
        }

    def get_network_stats(self) -> dict:
        util = self.get_link_utilization()
        active = len([e for e in util if util[e] > 0.0])
        congested = len([e for e in util if util[e] > _CONGESTION_THRESHOLD])
        avg_lat = (sum(self._latencies) / len(self._latencies)
                   if self._latencies else 0.0)
        max_lat = max(self._latencies) if self._latencies else 0.0
        return {
            "total_packets_sent": self.total_packets_sent,
            "delivered": self.total_delivered,
            "in_flight": len(self._in_flight),
            "avg_latency_ms": round(avg_lat, 3),
            "max_latency_ms": round(max_lat, 3),
            "active_links": active,
            "congested_links": congested,
            "total_links": self.graph.number_of_edges(),
        }
