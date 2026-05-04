import math
import sys
import os
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pygame
from config import ORBITAL_RADIUS_KM, NUM_SATELLITES
from agents import State

PANEL_X = 900
PANEL_W = 500
PANEL_H = 900
PAD = 8
GAP = 12
SEP = 1
SIMINFO_H = 40
SEC_TITLE_H = 22

BG_PANEL = (0x0A, 0x00, 0x18)
BORDER_LEFT = (0x7F, 0x77, 0xDD)
HEADER_BAR = (0x15, 0x00, 0x30)
TXT_HEADER = (0xAF, 0xA9, 0xEC)
TXT_ACCENT = (0x7F, 0x77, 0xDD)
TXT_PRI = (0xCE, 0xCB, 0xF6)
TXT_PINK = (0xED, 0x93, 0xB1)
TXT_LABEL = (0xAF, 0xA9, 0xEC)
SAT_NOM = (0x7F, 0x77, 0xDD)
SAT_WARN = (0xD4, 0x53, 0x7E)
SAT_MAN = (0xED, 0x93, 0xB1)
SAT_SAFE = (0xAF, 0xA9, 0xEC)
GS_C = (0xED, 0x93, 0xB1)
GOOD = (0x5D, 0xCA, 0xA5)
WARN_C = (0xEF, 0x9F, 0x27)
DANGER_C = (0xF0, 0x95, 0x95)
ROW_EVEN = (0x08, 0x00, 0x14)
ROW_ODD = (0x0A, 0x00, 0x18)
CHART_INNER_BG = (0x08, 0x00, 0x14)
CHART_GRID = (0x1A, 0x0A, 0x3A)
CHART_BD = (0x2A, 0x1A, 0x4A)
BAR_BG = (0x1A, 0x0A, 0x3A)

_STATE_COLOR = {
    State.NOMINAL: SAT_NOM,
    State.WARNING: SAT_WARN,
    State.MANEUVERING: SAT_MAN,
    State.SAFE: SAT_SAFE,
}

_STATE_ABBREV = {
    State.NOMINAL: "NOM",
    State.WARNING: "WARN",
    State.MANEUVERING: "MAN",
    State.SAFE: "SAFE",
}

_EVT_STYLE = {
    "ALERT":    {"bar": (0xD4, 0x53, 0x7E), "txt": (0xF4, 0xC0, 0xD1)},
    "MANEUVER": {"bar": (0xED, 0x93, 0xB1), "txt": (0xCE, 0xCB, 0xF6)},
    "TELEMETRY": {"bar": (0x7F, 0x77, 0xDD), "txt": (0xAF, 0xA9, 0xEC)},
    "DEBRIS":   {"bar": (0xEF, 0x9F, 0x27), "txt": (0xFA, 0xC7, 0x75)},
    "DELIVERY": {"bar": (0x5D, 0xCA, 0xA5), "txt": (0xCE, 0xCB, 0xF6)},
    "INFO":     {"bar": (0x53, 0x4A, 0xB7), "txt": (0xCE, 0xCB, 0xF6)},
}


def _isl_rgb(load: float):
    if load < 0.40:
        return (0x2A, 0x1A, 0x5E)
    if load < 0.70:
        t = (load - 0.40) / 0.30
        a, b = (0x2A, 0x1A, 0x5E), (0x53, 0x4A, 0xB7)
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    t = min(1.0, (load - 0.70) / 0.30)
    a, b = (0x53, 0x4A, 0xB7), (0xD4, 0x53, 0x7E)
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _compute_dashboard_layout():
    """Non-overlapping Y regions; topology gets remainder >= min height."""
    main_top = 8
    main_h = 52
    y = main_top + main_h + SEP + GAP

    const_h = SEC_TITLE_H + 168
    net_h = SEC_TITLE_H + 106
    chart_inner_h = 70
    chart_gap = 16
    chart_h = SEC_TITLE_H + chart_inner_h * 2 + chart_gap

    event_rows = 8
    event_body = event_rows * 28 + 12
    event_h = SEC_TITLE_H + event_body

    cur = main_top + main_h + SEP + GAP
    y_const = cur
    cur += const_h + SEP + GAP
    y_net = cur
    cur += net_h + SEP + GAP
    y_charts = cur
    cur += chart_h + SEP + GAP
    y_events = cur
    cur += event_h + SEP + GAP
    y_topo = cur

    reserved_bottom = SIMINFO_H + GAP
    topo_h = PANEL_H - y_topo - reserved_bottom

    if topo_h < 200:
        event_rows = 6
        event_body = event_rows * 28 + 12
        event_h = SEC_TITLE_H + event_body
        cur = y_charts + chart_h + SEP + GAP
        y_events = cur
        cur += event_h + SEP + GAP
        y_topo = cur
        topo_h = PANEL_H - y_topo - reserved_bottom

    if topo_h < 200:
        chart_inner_h = 60
        chart_h = SEC_TITLE_H + chart_inner_h * 2 + chart_gap
        cur = y_net + net_h + SEP + GAP
        y_charts = cur
        cur += chart_h + SEP + GAP
        y_events = cur
        cur += event_h + SEP + GAP
        y_topo = cur
        topo_h = PANEL_H - y_topo - reserved_bottom

    topo_h = max(120, topo_h)
    y_siminfo = PANEL_H - SIMINFO_H

    return {
        "main_top": main_top,
        "main_h": main_h,
        "y_const": y_const,
        "const_h": const_h,
        "y_net": y_net,
        "net_h": net_h,
        "y_charts": y_charts,
        "chart_h": chart_h,
        "chart_inner_h": chart_inner_h,
        "chart_gap": chart_gap,
        "y_events": y_events,
        "event_h": event_h,
        "event_rows": event_rows,
        "y_topo": y_topo,
        "topo_h": topo_h,
        "y_siminfo": y_siminfo,
    }


class MetricsDashboard:
    def __init__(self):
        self._f_orb = None
        self._f_sub = None
        self._f_sec = None
        self._f_tiny = None
        self._f_mono = None
        self._f_med_bold = None
        self._f_cell_id = None
        self._f_cell_abbr = None
        self._evt_seen_len = 0
        self._evt_flash_until = 0.0

    def init_fonts(self):
        self._f_orb = pygame.font.SysFont("arial", 28, bold=True)
        self._f_sub = pygame.font.SysFont("arial", 11)
        self._f_sec = pygame.font.SysFont("arial", 11, bold=True)
        self._f_tiny = pygame.font.SysFont("consolas", 9)
        self._f_mono = pygame.font.SysFont("consolas", 10)
        self._f_med_bold = pygame.font.SysFont("consolas", 12, bold=True)
        self._f_cell_id = pygame.font.SysFont("arial", 11, bold=True)
        self._f_cell_abbr = pygame.font.SysFont("arial", 9)
        self._f_msg = pygame.font.SysFont("arial", 11)
        self._f_ts = pygame.font.SysFont("consolas", 10)
        self._f_chart_lbl = pygame.font.SysFont("arial", 9)

    def draw(
        self,
        surface: pygame.Surface,
        satellites: list,
        debris_list: list,
        network,
        metrics,
        event_log: list,
        sim_time: float,
        sim_speed: int,
        display_positions: dict | None = None,
        chaos_mode: bool = False,
        anim_t: float = 0.0,
        selected_sat_id: int | None = None,
    ) -> None:
        if display_positions is None:
            display_positions = {s.sat_id: s.position for s in satellites}
        lay = _compute_dashboard_layout()
        self._draw_panel_bg(surface)
        self._draw_header(surface, lay, sim_time, sim_speed, chaos_mode, anim_t)
        self._draw_section_title(surface, lay["y_const"], "CONSTELLATION")
        self._draw_constellation(surface, satellites, selected_sat_id, lay, anim_t)
        self._draw_section_title(surface, lay["y_net"], "NETWORK METRICS")
        self._draw_network_metrics(surface, network, lay)
        self._draw_section_title(surface, lay["y_charts"], "LIVE TRENDS")
        self._draw_live_charts(surface, metrics, lay)
        self._draw_section_title(surface, lay["y_events"], "EVENT LOG")
        self._draw_event_log(surface, event_log, lay, anim_t)
        self._draw_section_title(surface, lay["y_topo"], "TOPOLOGY")
        self._draw_topology(surface, satellites, network, display_positions, lay)
        self._draw_sim_info(surface, lay)

    def _draw_panel_bg(self, surface):
        pygame.draw.rect(surface, BG_PANEL, (PANEL_X, 0, PANEL_W, PANEL_H))
        pygame.draw.line(surface, BORDER_LEFT, (PANEL_X, 0), (PANEL_X, PANEL_H), 2)

    def _draw_section_title(self, surface, y_top: int, title: str):
        bar = pygame.Surface((PANEL_W, SEC_TITLE_H), pygame.SRCALPHA)
        bar.fill(HEADER_BAR)
        surface.blit(bar, (PANEL_X, y_top))
        txt = self._f_sec.render(title.upper(), True, TXT_HEADER)
        surface.blit(txt, (PANEL_X + PAD, y_top + 4))
        pygame.draw.line(surface, CHART_BD, (PANEL_X + PAD, y_top + SEC_TITLE_H),
                         (PANEL_X + PANEL_W - PAD, y_top + SEC_TITLE_H), 1)

    def _draw_header(self, surface, lay, sim_time, sim_speed, chaos_mode, anim_t):
        y0 = lay["main_top"]
        h = lay["main_h"]
        pygame.draw.rect(surface, BG_PANEL, (PANEL_X, y0, PANEL_W, h))
        pygame.draw.line(surface, CHART_BD, (PANEL_X + PAD, y0 + h),
                         (PANEL_X + PANEL_W - PAD, y0 + h), 1)
        t1 = self._f_orb.render("ORB", True, (0xCE, 0xCB, 0xF6))
        t2 = self._f_sub.render("LEO SATELLITE CCN SIMULATOR", True, TXT_ACCENT)
        surface.blit(t1, (PANEL_X + PAD, y0 + 6))
        surface.blit(t2, (PANEL_X + PAD, y0 + 34))

        htime = int(sim_time // 3600)
        mtime = int((sim_time % 3600) // 60)
        stm = sim_time % 60
        t_str = f"T+ {htime:02d}:{mtime:02d}:{stm:05.2f}"
        tr = self._f_mono.render(t_str, True, TXT_PINK)
        surface.blit(tr, (PANEL_X + PANEL_W - PAD - tr.get_width(), y0 + 10))

        badge = self._f_mono.render(f"\u00d7{sim_speed}", True, TXT_PRI)
        bw, bh = badge.get_width() + 14, badge.get_height() + 6
        bx = PANEL_X + PANEL_W - PAD - bw
        pygame.draw.rect(surface, (0x26, 0x21, 0x5C), (bx, y0 + 30, bw, bh), border_radius=6)
        surface.blit(badge, (bx + 7, y0 + 33))

        if chaos_mode:
            pulse = 0.5 + 0.5 * math.sin(anim_t * 6.0)
            c = (int(220 + 35 * pulse), int(60 + 40 * pulse), int(120 + 60 * pulse))
            cs = self._f_sec.render("CHAOS MODE", True, c)
            surface.blit(cs, (PANEL_X + PANEL_W // 2 - cs.get_width() // 2, y0 + 4))

    def _draw_constellation(self, surface, satellites, selected_sat_id, lay, anim_t):
        body_top = lay["y_const"] + SEC_TITLE_H + 8
        cell, gap = 44, 6
        grid_w = 4 * cell + 3 * gap
        x0 = PANEL_X + (PANEL_W - grid_w) // 2
        warn_pulse = 0.5 + 0.5 * math.sin(anim_t * (2 * math.pi / 0.6))

        for sat in sorted(satellites, key=lambda s: s.sat_id):
            col = _STATE_COLOR[sat.state]
            gx = x0 + (sat.sat_id % 4) * (cell + gap)
            gy = body_top + (sat.sat_id // 4) * (cell + gap)

            surf = pygame.Surface((cell, cell), pygame.SRCALPHA)
            pygame.draw.rect(surf, (*col, 77), (0, 0, cell, cell), border_radius=6)

            brd_a = 255
            if sat.state == State.WARNING:
                brd_a = int(100 + 155 * warn_pulse)
            pygame.draw.rect(surf, (*col, brd_a), (0, 0, cell, cell), width=2, border_radius=6)

            cx, cy = cell // 2, cell // 2
            pygame.draw.circle(surf, col, (cx, cy), 6)

            if sat.state == State.MANEUVERING:
                pygame.draw.line(surf, col, (cx - 6, cy + 2), (cx + 6, cy - 3), 2)
                pygame.draw.line(surf, col, (cx + 6, cy - 3), (cx + 2, cy - 8), 2)
                pygame.draw.line(surf, col, (cx + 6, cy - 3), (cx + 5, cy + 5), 2)

            surface.blit(surf, (gx, gy))

            if selected_sat_id == sat.sat_id:
                pygame.draw.rect(surface, (255, 255, 255), (gx - 1, gy - 1, cell + 2, cell + 2), 2, border_radius=7)

            id_s = self._f_cell_id.render(str(sat.sat_id), True, (0xCE, 0xCB, 0xF6))
            ab = self._f_cell_abbr.render(_STATE_ABBREV[sat.state], True, col)
            surface.blit(id_s, (gx + 4, gy + 4))
            aw = ab.get_width()
            surface.blit(ab, (gx + (cell - aw) // 2, gy + cell - 14))

    def _metric_row(self, surface, y: int, label: str, val_str: str, frac: float, fill_rgb: tuple):
        bar_x = PANEL_X + 180
        bar_w = PANEL_W - 190
        row_h = 26
        lbl = self._f_med_bold.render(label, True, TXT_LABEL)
        surface.blit(lbl, (PANEL_X + PAD, y + 5))
        val = self._f_med_bold.render(val_str, True, (0xCE, 0xCB, 0xF6))
        vx = PANEL_X + PAD + 110 + max(0, 60 - val.get_width())
        surface.blit(val, (vx, y + 5))
        by = y + (row_h - 8) // 2
        pygame.draw.rect(surface, BAR_BG, (bar_x, by, bar_w, 8), border_radius=4)
        fw = int(bar_w * max(0.0, min(1.0, frac)))
        if fw > 0:
            pygame.draw.rect(surface, fill_rgb, (bar_x, by, fw, 8), border_radius=4)
        pygame.draw.rect(surface, CHART_BD, (bar_x, by, bar_w, 8), 1, border_radius=4)

    def _draw_network_metrics(self, surface, network, lay):
        y0 = lay["y_net"] + SEC_TITLE_H + 8
        stats = network.get_network_stats()
        isl_edges = [(u, v) for u, v, d in network.graph.edges(data=True) if d.get("kind") == "isl"]
        n_isl = len(isl_edges)
        max_isl = max(1, NUM_SATELLITES * (NUM_SATELLITES - 1) // 2)
        frac_isl = n_isl / max_isl

        lat = float(stats["avg_latency_ms"])
        frac_lat = min(1.0, lat / 100.0)
        if lat < 20:
            lc = GOOD
        elif lat <= 50:
            lc = WARN_C
        else:
            lc = DANGER_C

        sent = stats["total_packets_sent"]
        delivered = stats["delivered"]
        rate = (delivered / sent * 100.0) if sent else 0.0
        if rate > 90:
            rc = GOOD
        elif rate >= 60:
            rc = WARN_C
        else:
            rc = DANGER_C

        isl_rgb = (0x7F, 0x77, 0xDD)
        self._metric_row(surface, y0, "Active ISLs", f"{n_isl}", frac_isl, isl_rgb)
        self._metric_row(surface, y0 + 26, "Avg latency", f"{lat:.0f}", frac_lat, lc)
        self._metric_row(surface, y0 + 52, "Delivery rate", f"{rate:.0f}%", rate / 100.0, rc)

    def _chart_single(self, surface, y_top: int, inner_h: int, title: str, data, line_rgb: tuple, pad_lr: int):
        inner_w = PANEL_W - 2 * pad_lr
        x0 = PANEL_X + pad_lr
        pygame.draw.rect(surface, CHART_INNER_BG, (x0, y_top, inner_w, inner_h))
        pygame.draw.rect(surface, CHART_BD, (x0, y_top, inner_w, inner_h), 1)

        for g in (0.25, 0.5, 0.75):
            gy = int(y_top + inner_h * g)
            pygame.draw.line(surface, CHART_GRID, (x0, gy), (x0 + inner_w, gy), 1)

        surface.blit(self._f_chart_lbl.render(title, True, TXT_ACCENT), (x0 + 4, y_top + 2))

        pts = list(data)
        if len(pts) < 2:
            wait = self._f_chart_lbl.render("waiting for data...", True, TXT_ACCENT)
            surface.blit(wait, (x0 + inner_w // 2 - wait.get_width() // 2, y_top + inner_h // 2))
            return

        vmax = max(pts) * 1.05 if max(pts) > 0 else 1.0
        vmax = max(vmax, 1e-6)
        px_pts = []
        for i, v in enumerate(pts):
            tx = x0 + 4 + i * (inner_w - 8) / max(1, len(pts) - 1)
            ty = y_top + inner_h - 4 - (v / vmax) * (inner_h - 14)
            px_pts.append((int(tx), int(ty)))

        fill_pts_loc = [(p[0] - x0, p[1] - y_top) for p in px_pts]
        fill_pts_loc.append((px_pts[-1][0] - x0, inner_h - 2))
        fill_pts_loc.append((px_pts[0][0] - x0, inner_h - 2))
        fill_surf = pygame.Surface((inner_w, inner_h), pygame.SRCALPHA)
        if len(fill_pts_loc) >= 3:
            pygame.draw.polygon(fill_surf, (*line_rgb, 40), fill_pts_loc)
        surface.blit(fill_surf, (x0, y_top))

        if len(px_pts) > 1:
            pygame.draw.lines(surface, line_rgb, False, px_pts, 2)
        lx, ly = px_pts[-1]
        pygame.draw.circle(surface, line_rgb, (lx, ly), 3)

        mx_s = self._f_chart_lbl.render(f"{vmax:.2g}", True, TXT_ACCENT)
        surface.blit(mx_s, (x0 + inner_w - mx_s.get_width() - 4, y_top + 3))

    def _draw_live_charts(self, surface, metrics, lay):
        pad_lr = 16
        ich = lay["chart_inner_h"]
        cg = lay["chart_gap"]
        y0 = lay["y_charts"] + SEC_TITLE_H + 8
        lat_data = metrics.chart_latency_ms if metrics else []
        nm_data = metrics.chart_near_misses if metrics else []
        self._chart_single(surface, y0, ich, "LATENCY (ms)", lat_data, (0xD4, 0x53, 0x7E), pad_lr)
        self._chart_single(surface, y0 + ich + cg, ich, "NEAR MISSES", nm_data, (0xED, 0x93, 0xB1), pad_lr)

    def _draw_event_log(self, surface, event_log: list, lay, anim_t: float):
        evlist = list(event_log)
        n = lay["event_rows"]
        body_top = lay["y_events"] + SEC_TITLE_H + 6
        row_h = 28
        msg_w = PANEL_W - 2 * PAD - 8 - 72

        if len(evlist) > self._evt_seen_len:
            self._evt_flash_until = time.monotonic() + 0.4
        self._evt_seen_len = len(evlist)

        flash_on = time.monotonic() < self._evt_flash_until
        for i, evt in enumerate(evlist[:n]):
            y = body_top + i * row_h
            row_bg = ROW_EVEN if i % 2 == 0 else ROW_ODD
            cat = getattr(evt, "category", "INFO")
            st = _EVT_STYLE.get(cat, _EVT_STYLE["INFO"])

            base = row_bg
            if i == 0 and flash_on:
                overlay = pygame.Surface((PANEL_W - 2 * PAD, row_h), pygame.SRCALPHA)
                overlay.fill((*st["bar"], 60))
                pygame.draw.rect(surface, base, (PANEL_X + PAD, y, PANEL_W - 2 * PAD, row_h))
                surface.blit(overlay, (PANEL_X + PAD, y))
            else:
                pygame.draw.rect(surface, base, (PANEL_X + PAD, y, PANEL_W - 2 * PAD, row_h))

            pygame.draw.rect(surface, st["bar"], (PANEL_X + PAD, y, 3, row_h))
            ts = self._f_ts.render(f"{evt.sim_time:>8.1f}s", True, (0x7F, 0x77, 0xDD))
            surface.blit(ts, (PANEL_X + PAD + 8, y + 6))

            full = evt.message
            if self._f_msg.render(full, True, st["txt"]).get_width() <= msg_w:
                msg = full
            else:
                ell = "..."
                lo, hi = 0, len(full)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if self._f_msg.render(full[:mid] + ell, True, st["txt"]).get_width() <= msg_w:
                        lo = mid
                    else:
                        hi = mid - 1
                msg = full[:lo] + ell
            msg_s = self._f_msg.render(msg, True, st["txt"])
            surface.blit(msg_s, (PANEL_X + PAD + 72, y + 5))

    def _draw_topology(self, surface, satellites, network, display_positions, lay):
        box = min(lay["topo_h"] - 16, PANEL_W - 2 * PAD)
        box = max(120, box)
        bx = PANEL_X + (PANEL_W - box) // 2
        by = lay["y_topo"] + SEC_TITLE_H + 8
        pygame.draw.rect(surface, CHART_INNER_BG, (bx, by, box, box))
        pygame.draw.rect(surface, CHART_BD, (bx, by, box, box), 1)
        cx, cy = bx + box // 2, by + box // 2
        pygame.draw.circle(surface, (0x12, 0x00, 0x28), (cx, cy), min(28, box // 8))
        pygame.draw.circle(surface, CHART_BD, (cx, cy), min(28, box // 8), 1)

        n = len(satellites)
        r_node = min(78, box // 2 - 24)
        sat_ang = {satellites[i].sat_id: 2 * math.pi * i / n - math.pi / 2 for i in range(n)}
        sat_pos2 = {}
        for sat in satellites:
            ang = sat_ang[sat.sat_id]
            sx = cx + int(r_node * math.cos(ang))
            sy = cy + int(r_node * math.sin(ang))
            sat_pos2[sat.sat_id] = (sx, sy)

        gs_pos2 = {}
        for node, data in network.graph.nodes(data=True):
            if isinstance(node, str) and node.startswith("GS"):
                ang = math.pi / 2 + (0.35 if node == "GS0" else -0.35)
                gs_pos2[node] = (
                    cx + int((r_node + 22) * math.cos(ang)),
                    cy + int((r_node + 22) * math.sin(ang)),
                )

        highlight = network.get_latest_route_path()
        hl_set = set()
        if highlight and len(highlight) > 1:
            for a, b in zip(highlight[:-1], highlight[1:]):
                hl_set.add(frozenset((a, b)))

        for u, v, d in network.graph.edges(data=True):
            if d.get("kind") != "isl":
                continue
            p1, p2 = sat_pos2.get(u), sat_pos2.get(v)
            if p1 is None or p2 is None:
                continue
            load = float(d.get("current_load", 0.0))
            col = _isl_rgb(load)
            key = frozenset((u, v))
            if key in hl_set:
                col = (255, 255, 255)
            pygame.draw.line(surface, col, p1, p2, 2 if key in hl_set else 1)

        for sat in satellites:
            p = sat_pos2.get(sat.sat_id)
            if p:
                pygame.draw.circle(surface, _STATE_COLOR[sat.state], p, 6)
                lbl = self._f_tiny.render(str(sat.sat_id), True, TXT_PRI)
                surface.blit(lbl, (p[0] - 4, p[1] + 8))

        for node, p in gs_pos2.items():
            pygame.draw.rect(surface, GS_C, (p[0] - 5, p[1] - 5, 10, 10))
            lbl = self._f_tiny.render(node, True, GS_C)
            surface.blit(lbl, (p[0] - 10, p[1] - 18))

    def _draw_sim_info(self, surface, lay):
        y0 = lay["y_siminfo"]
        pygame.draw.rect(surface, (0x08, 0x00, 0x14), (PANEL_X, y0, PANEL_W, PANEL_H - y0))
        ctrl = "SPC pause  +/- speed  C chaos  T tracer  G graphs  R reset  Q quit"
        surface.blit(self._f_tiny.render(ctrl, True, TXT_ACCENT), (PANEL_X + PAD, y0 + 6))
        # Analytics panel button hint
        btn_w, btn_h = 148, 22
        btn_x = PANEL_X + PANEL_W - btn_w - PAD
        btn_y = y0 + SIMINFO_H - btn_h - 4
        pygame.draw.rect(surface, (0x53, 0x4A, 0xB7), (btn_x, btn_y, btn_w, btn_h), border_radius=4)
        pygame.draw.rect(surface, (0x7F, 0x77, 0xDD), (btn_x, btn_y, btn_w, btn_h), 1, border_radius=4)
        btn_lbl = self._f_sec.render("[ P ]  ANALYTICS PANEL", True, (0xED, 0x93, 0xB1))
        surface.blit(btn_lbl, (btn_x + btn_w // 2 - btn_lbl.get_width() // 2,
                                btn_y + btn_h // 2 - btn_lbl.get_height() // 2))
