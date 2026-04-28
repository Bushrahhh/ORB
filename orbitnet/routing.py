import math
import heapq


class RoutingEngine:
    """Shortest-path and utility routing over the ISL networkx graph."""

    # ------------------------------------------------------------------
    # Core Dijkstra
    # ------------------------------------------------------------------

    @staticmethod
    def dijkstra_path(graph, source, dest) -> list:
        """
        Returns ordered list of node IDs from source to dest,
        using propagation_delay_ms as edge weight.
        Returns [] if no path exists.
        """
        if source not in graph or dest not in graph:
            return []
        if source == dest:
            return [source]

        dist = {source: 0.0}
        prev = {}
        heap = [(0.0, source)]

        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, math.inf):
                continue
            if u == dest:
                break
            for v in graph.neighbors(u):
                w = graph[u][v].get("propagation_delay_ms", 1.0)
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, v))

        if dest not in prev and dest != source:
            return []

        path = []
        cur = dest
        while cur in prev:
            path.append(cur)
            cur = prev[cur]
        path.append(source)
        path.reverse()
        return path

    # ------------------------------------------------------------------
    # Ground-station routing
    # ------------------------------------------------------------------

    @staticmethod
    def find_ground_station_path(sat_id: int, graph) -> list:
        """
        Returns the shortest-delay path from sat_id to any ground station
        node (string IDs starting with 'GS').
        """
        gs_nodes = [n for n in graph.nodes if isinstance(n, str) and n.startswith("GS")]
        if not gs_nodes:
            return []

        best_path: list = []
        best_delay = math.inf

        for gs in gs_nodes:
            path = RoutingEngine.dijkstra_path(graph, sat_id, gs)
            if not path:
                continue
            delay = sum(
                graph[path[i]][path[i + 1]].get("propagation_delay_ms", 0.0)
                for i in range(len(path) - 1)
            )
            if delay < best_delay:
                best_delay = delay
                best_path = path

        return best_path

    # ------------------------------------------------------------------
    # Failure reroute
    # ------------------------------------------------------------------

    @staticmethod
    def reroute_on_failure(packet, failed_link: tuple, graph) -> list:
        """
        Finds alternate path for packet avoiding failed_link (u, v).
        Temporarily removes the edge, runs Dijkstra, then restores it.
        Returns new path or [] if unreachable.
        """
        u, v = failed_link
        edge_data = None

        if graph.has_edge(u, v):
            edge_data = dict(graph[u][v])
            graph.remove_edge(u, v)

        # Restart from the last undelivered hop
        src = packet.path[-1] if packet.path else packet.source
        path = RoutingEngine.dijkstra_path(graph, src, packet.destination)

        if edge_data is not None:
            graph.add_edge(u, v, **edge_data)

        return path
