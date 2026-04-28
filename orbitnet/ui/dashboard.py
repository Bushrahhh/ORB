import math
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pygame
from config import COLORS, ORBITAL_RADIUS_KM, NUM_ORBITAL_PLANES
from agents import State

# ── Layout ──────────────────────────────────────────────────────────────────
PANEL_X  = 900
PANEL_W  = 500
PANEL_H  = 900
PAD      = 14

# Section y-offsets (relative to PANEL_X, y=0)
_SEC = {
    "title":       (0,   50),
    "constellation": (50, 175),
    "network":     (175, 325),
    "collision":   (325, 445),
    "eventlog":    (445, 635),
    "minigraph":   (635, 815),
    "siminfo":     (815, 900),
}

# Mini-graph geometry
_MG_CX = PANEL_X + PANEL_W // 2   # 1150
_MG_CY = (_SEC["minigraph"][0] + _SEC["minigraph"][1]) // 2   # 725
_MG_SCALE = 68.0 / ORBITAL_RADIUS_KM   # orbital radius → 68 px in mini-graph
_MG_EARTH_R = int(6371 * _MG_SCALE * 0.92)   # visual Earth radius in mini-graph

# ── Projection (same angles as renderer, different scale/center) ─────────────
_AZ  = math.radians(20.0)
_EL  = math.radians(25.0)
_COS_AZ, _SIN_AZ = math.cos(_AZ), math.sin(_AZ)
_COS_EL, _SIN_EL = math.cos(_EL), math.sin(_EL)


def _proj_mini(pos_3d):
    x, y, z = pos_3d
    x1 = x * _COS_AZ - y * _SIN_AZ
    y1 = x * _SIN_AZ + y * _COS_AZ
    x2 = x1
    y2 = y1 * _COS_EL - z * _SIN_EL
    return (_MG_CX + int(x2 * _MG_SCALE), _MG_CY - int(y2 * _MG_SCALE))


# ── Color aliases ────────────────────────────────────────────────────────────
_C         = COLORS
BG_PANEL   = _C["PANEL_BG"]
BORDER_C   = _C["PANEL_BORDER"]
TXT_PRI    = _C["TEXT_PRIMARY"]
TXT_SEC    = _C["TEXT_SECONDARY"]
SAT_NOM    = _C["SAT_NOMINAL"]
SAT_WARN   = _C["SAT_WARNING"]
SAT_MAN    = _C["SAT_MANEUVERING"]
SAT_SAFE   = _C["SAT_SAFE"]
GS_C       = _C["GROUND_STATION"]
ISL_LO     = _C["ISL_ACTIVE"]
ISL_HI     = _C["ISL_CONGESTED"]
GOOD       = _C["METRIC_GOOD"]
WARN_C     = _C["METRIC_WARN"]
DANGER_C   = _C["METRIC_DANGER"]
BG_MAIN    = _C["BACKGROUND"]

_STATE_COLOR = {
    State.NOMINAL:     SAT_NOM,
    State.WARNING:     SAT_WARN,
    State.MANEUVERING: SAT_MAN,
    State.SAFE:        SAT_SAFE,
}

_EVT_COLOR = {
    "ALERT":    _C["ALERT_PACKET"],
    "MANEUVER": SAT_MAN,
    "INFO":     TXT_PRI,
    "TELEMETRY": TXT_SEC,
}


# ════════════════════════════════════════════════════════════════════════════
class MetricsDashboard:
    def __init__(self):
        self._f_title  = None
        self._f_head   = None
        self._f_body   = None
        self._f_small  = None
        self._f_mono   = None
        self._overlay  = None

    def init_fonts(self):
        self._f_title = pygame.font.SysFont("monospace", 14, bold=True)
        self._f_head  = pygame.font.SysFont("monospace", 11, bold=True)
        self._f_body  = pygame.font.SysFont("monospace", 11)
        self._f_small = pygame.font.SysFont("monospace", 9)
        self._f_mono  = pygame.font.SysFont("monospace", 10)
        self._overlay = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)

    # ── Master draw ──────────────────────────────────────────────────────────
    def draw(self, surface: pygame.Surface, satellites: list, debris_list: list,
             network, metrics, event_log: list,
             sim_time: float, sim_speed: int) -> None:
        self._draw_panel_bg(surface)
        self._draw_title(surface)
        self._draw_constellation(surface, satellites)
        self._draw_network_metrics(surface, network)
        self._draw_collision_stats(surface, satellites, debris_list, metrics)
        self._draw_event_log(surface, event_log)
        self._draw_mini_graph(surface, satellites, network)
        self._draw_sim_info(surface, sim_time, sim_speed)

    # ── Panel background ─────────────────────────────────────────────────────
    def _draw_panel_bg(self, surface):
        pygame.draw.rect(surface, BG_PANEL, (PANEL_X, 0, PANEL_W, PANEL_H))
        pygame.draw.line(surface, BORDER_C, (PANEL_X, 0), (PANEL_X, PANEL_H), 2)

    # ── Section divider helper ────────────────────────────────────────────────
    def _section_header(self, surface, y_top, label):
        y = y_top + 6
        pygame.draw.line(surface, BORDER_C, (PANEL_X + PAD, y + 8),
                         (PANEL_X + PANEL_W - PAD, y + 8), 1)
        lbl = self._f_head.render(label, True, TXT_SEC)
        surface.blit(lbl, (PANEL_X + PAD, y))

    def _row(self, surface, y, label, value, v_color=None):
        lbl = self._f_body.render(label, True, TXT_SEC)
        val = self._f_body.render(str(value), True, v_color or TXT_PRI)
        surface.blit(lbl, (PANEL_X + PAD, y))
        surface.blit(val, (PANEL_X + PANEL_W - PAD - val.get_width(), y))

    # ── Title ────────────────────────────────────────────────────────────────
    def _draw_title(self, surface):
        y0, y1 = _SEC["title"]
        pygame.draw.rect(surface, (18, 0, 36), (PANEL_X, y0, PANEL_W, y1 - y0))
        t1 = self._f_title.render("ORB — LEO CCN SIMULATION", True, BORDER_C)
        t2 = self._f_small.render("CE313 · CCN Assignment · Phase 2", True, TXT_SEC)
        surface.blit(t1, (PANEL_X + PAD, y0 + 10))
        surface.blit(t2, (PANEL_X + PAD, y0 + 32))

    # ── Constellation status grid ────────────────────────────────────────────
    def _draw_constellation(self, surface, satellites):
        y0, y1 = _SEC["constellation"]
        self._section_header(surface, y0, "CONSTELLATION STATUS")
        # 4 × 3 grid (4 per plane, 3 planes)
        sq   = 18
        gap  = 6
        x0   = PANEL_X + PAD
        y_s  = y0 + 24
        for sat in sorted(satellites, key=lambda s: s.sat_id):
            col = _STATE_COLOR[sat.state]
            gx  = x0 + (sat.sat_id % 4) * (sq + gap)
            gy  = y_s + (sat.sat_id // 4) * (sq + gap + 4)
            pygame.draw.rect(surface, col, (gx, gy, sq, sq))
            pygame.draw.rect(surface, BORDER_C, (gx, gy, sq, sq), 1)
            lbl = self._f_small.render(f"S{sat.sat_id}", True,
                                        BG_MAIN if sat.state != State.NOMINAL else TXT_SEC)
            surface.blit(lbl, (gx + 2, gy + 4))

        # Legend
        legend_y = y0 + 24 + 3 * (sq + gap + 4) + 4
        for i, (name, col) in enumerate([("NOM", SAT_NOM), ("WARN", SAT_WARN),
                                          ("MAN", SAT_MAN), ("SAFE", SAT_SAFE)]):
            lx = PANEL_X + PAD + i * 110
            pygame.draw.rect(surface, col, (lx, legend_y, 10, 10))
            lbl = self._f_small.render(name, True, TXT_SEC)
            surface.blit(lbl, (lx + 13, legend_y))

    # ── Network metrics ───────────────────────────────────────────────────────
    def _draw_network_metrics(self, surface, network):
        y0, y1 = _SEC["network"]
        self._section_header(surface, y0, "NETWORK METRICS")
        stats = network.get_network_stats()
        util  = network.get_link_utilization()
        active = sum(1 for v in util.values() if v > 0.0)
        congested = stats["congested_links"]
        delivered = stats["delivered"]
        sent      = stats["total_packets_sent"]
        rate      = delivered / sent * 100 if sent else 0.0

        rows = [
            ("Active ISLs",       f"{active} / {stats['total_links']}",     None),
            ("Packets in transit", str(stats["in_flight"]),                  None),
            ("Avg latency",        f"{stats['avg_latency_ms']:.2f} ms",
             GOOD if stats["avg_latency_ms"] < 50 else WARN_C),
            ("Max latency",        f"{stats['max_latency_ms']:.2f} ms",      None),
            ("Congested links",    str(congested),
             DANGER_C if congested > 0 else GOOD),
            ("Packets delivered",  f"{delivered} / {sent}",                  None),
            ("Delivery rate",      f"{rate:.1f}%",
             GOOD if rate > 90 else (WARN_C if rate > 50 else DANGER_C)),
        ]
        for i, (label, value, col) in enumerate(rows):
            self._row(surface, y0 + 24 + i * 17, label, value, col)

    # ── Collision stats ───────────────────────────────────────────────────────
    def _draw_collision_stats(self, surface, satellites, debris_list, metrics):
        y0, y1 = _SEC["collision"]
        self._section_header(surface, y0, "COLLISION STATS")
        nm  = metrics.total_near_misses if metrics else 0
        man = metrics.total_maneuvers if metrics else 0
        min_sep = metrics.min_separation_km if metrics else float("inf")
        min_str = f"{min_sep:.1f} km" if min_sep < 1e6 else "—"

        rows = [
            ("Near misses",       str(nm),           DANGER_C if nm > 0 else GOOD),
            ("Maneuvers exec.",   str(man),           WARN_C   if man > 0 else None),
            ("Min separation",    min_str,
             DANGER_C if min_sep < 10 else (WARN_C if min_sep < 50 else GOOD)),
            ("Debris tracked",    str(len(debris_list)),  TXT_SEC),
        ]
        for i, (label, value, col) in enumerate(rows):
            self._row(surface, y0 + 24 + i * 22, label, value, col)

    # ── Event log ─────────────────────────────────────────────────────────────
    def _draw_event_log(self, surface, event_log):
        y0, y1 = _SEC["eventlog"]
        self._section_header(surface, y0, "LIVE EVENT LOG")
        line_h = 13
        for i, evt in enumerate(list(event_log)[:12]):
            y = y0 + 24 + i * line_h
            if y + line_h > y1:
                break
            col   = _EVT_COLOR.get(getattr(evt, "category", "INFO"), TXT_PRI)
            ts    = f"[{evt.sim_time:>7.1f}s]"
            ts_s  = self._f_small.render(ts, True, TXT_SEC)
            msg_s = self._f_small.render(evt.message[:42], True, col)
            surface.blit(ts_s,  (PANEL_X + PAD,                y))
            surface.blit(msg_s, (PANEL_X + PAD + ts_s.get_width() + 4, y))

    # ── Mini ISL network graph ─────────────────────────────────────────────────
    def _draw_mini_graph(self, surface, satellites, network):
        y0, y1 = _SEC["minigraph"]
        self._section_header(surface, y0, "NETWORK TOPOLOGY")

        # Clip region — only draw inside this section
        clip = pygame.Rect(PANEL_X + 2, y0 + 18, PANEL_W - 4, y1 - y0 - 20)
        surface.set_clip(clip)

        # Earth circle in mini graph
        pygame.draw.circle(surface, (20, 0, 40), (_MG_CX, _MG_CY), _MG_EARTH_R)
        pygame.draw.circle(surface, BORDER_C, (_MG_CX, _MG_CY), _MG_EARTH_R, 1)

        # Ground stations
        gs_mini = {}
        for n, data in network.graph.nodes(data=True):
            if isinstance(n, str) and n.startswith("GS"):
                raw = _proj_mini(data["pos"])
                # Clamp to Earth border in mini graph
                dx, dy = raw[0] - _MG_CX, raw[1] - _MG_CY
                dist   = math.hypot(dx, dy) or 1.0
                gx = _MG_CX + int(dx / dist * _MG_EARTH_R)
                gy = _MG_CY + int(dy / dist * _MG_EARTH_R)
                gs_mini[n] = (gx, gy)

        # Satellite mini positions
        sat_mini = {s.sat_id: _proj_mini(s.position) for s in satellites}
        all_mini = {**sat_mini, **gs_mini}

        # Edges
        for u, v, data in network.graph.edges(data=True):
            kind = data.get("kind", "")
            p1   = all_mini.get(u)
            p2   = all_mini.get(v)
            if p1 is None or p2 is None:
                continue
            if kind == "isl":
                load = data.get("current_load", 0.0)
                col  = ISL_HI if load > 0.7 else ISL_LO
                pygame.draw.line(surface, col, p1, p2, 1)
            elif kind == "uplink":
                pygame.draw.line(surface, (*GS_C, 140), p1, p2, 1)

        # Satellite nodes
        for sat in satellites:
            p = sat_mini.get(sat.sat_id)
            if p:
                pygame.draw.circle(surface, _STATE_COLOR[sat.state], p, 3)

        # Ground station triangles
        for n, p in gs_mini.items():
            pygame.draw.polygon(surface, GS_C,
                                [(p[0], p[1] - 5), (p[0] - 4, p[1] + 3),
                                 (p[0] + 4, p[1] + 3)])
            lbl = self._f_small.render(n, True, GS_C)
            surface.blit(lbl, (p[0] - lbl.get_width() // 2, p[1] + 5))

        surface.set_clip(None)

    # ── Simulation info bar ───────────────────────────────────────────────────
    def _draw_sim_info(self, surface, sim_time, sim_speed):
        y0, y1 = _SEC["siminfo"]
        pygame.draw.rect(surface, (10, 0, 28), (PANEL_X, y0, PANEL_W, y1 - y0))
        pygame.draw.line(surface, BORDER_C, (PANEL_X, y0), (PANEL_X + PANEL_W, y0), 1)

        h = sim_time // 3600
        m = (sim_time % 3600) // 60
        s = sim_time % 60
        t_str = f"SIM TIME  {int(h):02d}:{int(m):02d}:{s:05.2f}"
        sp_str = f"SPEED  {sim_speed}×"
        ctrl = "SPC pause  ± speed  R reset  ESC quit"

        t_lbl  = self._f_mono.render(t_str,  True, TXT_PRI)
        sp_lbl = self._f_mono.render(sp_str, True, WARN_C)
        ct_lbl = self._f_small.render(ctrl,  True, TXT_SEC)

        surface.blit(t_lbl,  (PANEL_X + PAD, y0 + 8))
        surface.blit(sp_lbl, (PANEL_X + PAD, y0 + 26))
        surface.blit(ct_lbl, (PANEL_X + PAD, y0 + 44))
        # ORB watermark bottom-right
        wm = self._f_title.render("ORB", True, (*BORDER_C, 60))
        surface.blit(wm, (PANEL_X + PANEL_W - wm.get_width() - PAD, y0 + 56))
