import math
import random
import sys
import os
import time
from collections import defaultdict, deque

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pygame
from config import (
    ORBITAL_RADIUS_KM, NUM_ORBITAL_PLANES,
    WARNING_THRESHOLD_KM,
)
from physics import OrbitalMechanics
from agents import State
from packets import CollisionAlertPacket, TelemetryPacket, AvoidanceCommandPacket

VP_W = 900
VP_H = 900
THREAT_BAR_H = 28
CX_ORBIT = VP_W // 2
CY_ORBIT = THREAT_BAR_H + (VP_H - THREAT_BAR_H) // 2
HALO_PURPLE = (0x4A, 0x20, 0x80)

EARTH_R_PX = 120
ORBIT_SCALE = VP_W * 0.35 / ORBITAL_RADIUS_KM

_INC_RAD = math.radians(53.0)
_RAAN_GAP = math.radians(60.0)
_AZ = math.radians(20.0)
_EL = math.radians(25.0)
_COS_AZ, _SIN_AZ = math.cos(_AZ), math.sin(_AZ)
_COS_EL, _SIN_EL = math.cos(_EL), math.sin(_EL)

# ── Satellite visual colors (spec) ───────────────────────────────────────────
SAT_STYLE = {
    State.NOMINAL:     {"core": (0x7F, 0x77, 0xDD), "glow": (0x53, 0x4A, 0xB7)},
    State.WARNING:     {"core": (0xD4, 0x53, 0x7E), "glow": (0x99, 0x35, 0x56)},
    State.MANEUVERING: {"core": (0xED, 0x93, 0xB1), "glow": (0xD4, 0x53, 0x7E)},
    State.SAFE:        {"core": (0xAF, 0xA9, 0xEC), "glow": (0x7F, 0x77, 0xDD)},
}

ISL_COL_LOW = (0x2A, 0x1A, 0x5E)
ISL_COL_MID = (0x53, 0x4A, 0xB7)
ISL_COL_HI = (0xD4, 0x53, 0x7E)
PKT_DOT = (0xF4, 0xC0, 0xD1)
EARTH_FILL = (0x0D, 0x00, 0x30)
EARTH_TERM_LIT = (0x15, 0x00, 0x40)
EARTH_LAND = (0x1A, 0x00, 0x50)
GS_COL = (0xED, 0x93, 0xB1)
BG_DEEP = (8, 0, 26)

_TRACER_PALETTE = [
    (0xFF, 0x88, 0xCC), (0x88, 0xCC, 0xFF), (0xCC, 0xFF, 0x88),
    (0xFF, 0xCC, 0x66), (0xAA, 0x66, 0xFF),
]


def _proj(pos_3d: tuple) -> tuple[int, int]:
    x, y, z = pos_3d
    x1 = x * _COS_AZ - y * _SIN_AZ
    y1 = x * _SIN_AZ + y * _COS_AZ
    x2 = x1
    y2 = y1 * _COS_EL - z * _SIN_EL
    return (
        CX_ORBIT + int(x2 * ORBIT_SCALE),
        CY_ORBIT - int(y2 * ORBIT_SCALE),
    )


def _lerp_pt(p1, p2, t):
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def _dashed_line_alpha(
    surf: pygame.Surface,
    p1: tuple,
    p2: tuple,
    rgba: tuple,
    dash: float = 6.0,
    gap: float = 5.0,
    phase: float = 0.0,
) -> None:
    x1, y1 = float(p1[0]), float(p1[1])
    x2, y2 = float(p2[0]), float(p2[1])
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist < 0.5:
        return
    ux, uy = dx / dist, dy / dist
    cycle = dash + gap
    off = phase % cycle
    t = -off
    while t < dist:
        s = max(0.0, t)
        e = min(dist, t + dash)
        if e > s:
            pygame.draw.line(
                surf,
                rgba,
                (int(x1 + ux * s), int(y1 + uy * s)),
                (int(x1 + ux * e), int(y1 + uy * e)),
                1,
            )
        t += cycle


def _gs_border_pos(gs_3d):
    raw_x, raw_y = _proj(gs_3d)
    dx, dy = raw_x - CX_ORBIT, raw_y - CY_ORBIT
    dist = math.hypot(dx, dy) or 1.0
    return (
        int(CX_ORBIT + dx / dist * EARTH_R_PX),
        int(CY_ORBIT + dy / dist * EARTH_R_PX),
    )


def _isl_rgb(load: float) -> tuple[int, int, int]:
    if load < 0.40:
        return ISL_COL_LOW
    if load < 0.70:
        t = (load - 0.40) / 0.30
        return tuple(
            int(ISL_COL_LOW[i] + (ISL_COL_MID[i] - ISL_COL_LOW[i]) * t)
            for i in range(3)
        )
    t = min(1.0, (load - 0.70) / 0.30)
    return tuple(
        int(ISL_COL_MID[i] + (ISL_COL_HI[i] - ISL_COL_MID[i]) * t)
        for i in range(3)
    )


def _packet_pos_on_path(path: list, progress: float, node_screen: dict):
    if len(path) < 2:
        return None
    n_edges = len(path) - 1
    t = max(0.0, min(1.0, progress)) * n_edges
    ei = min(int(t), n_edges - 1)
    et = t - ei
    p1 = node_screen.get(path[ei])
    p2 = node_screen.get(path[ei + 1])
    if p1 is None or p2 is None:
        return None
    return (int(p1[0] + (p2[0] - p1[0]) * et), int(p1[1] + (p2[1] - p1[1]) * et))


# ── Background generators ───────────────────────────────────────────────────
_STARS_TINY: list[tuple] = []
_STARS_MED: list[tuple] = []
_STARS_BIG: list[tuple] = []  # x, y, phase


def _init_background_assets():
    global _NEBULA, _STARS_TINY, _STARS_MED, _STARS_BIG
    if _STARS_TINY:
        return
    rng = random.Random(4242)
    for _ in range(150):
        _STARS_TINY.append((
            rng.randint(0, VP_W - 1), rng.randint(0, VP_H - 1),
            rng.randint(200, 255), rng.randint(200, 255), rng.randint(230, 255),
        ))
    for _ in range(60):
        _STARS_MED.append((
            rng.randint(0, VP_W - 1), rng.randint(0, VP_H - 1),
            rng.randint(220, 255), rng.randint(220, 255), 255,
        ))
    for _ in range(20):
        _STARS_BIG.append((
            rng.randint(0, VP_W - 1), rng.randint(0, VP_H - 1),
            rng.uniform(0, 6.28),
        ))


class OrbitalRenderer:
    def __init__(self):
        _init_background_assets()
        self._font_sat = None
        self._font_gs = None
        self._font_popup = None
        self._font_threat = None
        self._overlay = None
        self._sat_layer = None
        self._vignette_start: float = 0.0
        self._vignette_duration = 0.5
        self._warn_r_px = max(1, int(WARNING_THRESHOLD_KM * ORBIT_SCALE))
        self._trails: dict[int, deque] = defaultdict(lambda: deque(maxlen=25))
        self._continent_polys = self._build_continents()

    def init_fonts(self):
        self._font_sat = pygame.font.SysFont("monospace", 9)
        self._font_gs = pygame.font.SysFont("arial", 10)
        self._font_threat_label = pygame.font.SysFont("arial", 11)
        self._font_threat_pct = pygame.font.SysFont("arial", 12, bold=True)
        self._font_popup = pygame.font.SysFont("monospace", 11)
        self._font_threat = pygame.font.SysFont("monospace", 10, bold=True)
        self._overlay = pygame.Surface((VP_W, VP_H), pygame.SRCALPHA)
        self._sat_layer = pygame.Surface((VP_W, VP_H), pygame.SRCALPHA)

    def trigger_collision_flash(self, duration_s: float = 0.5) -> None:
        self._vignette_start = time.monotonic()
        self._vignette_duration = duration_s

    def _build_continents(self):
        polys = []
        rng = random.Random(777)
        for _ in range(5):
            n = rng.randint(5, 8)
            pts = []
            for i in range(n):
                ang = 2 * math.pi * i / n + rng.uniform(-0.2, 0.2)
                rr = EARTH_R_PX - rng.randint(8, 25)
                pts.append((
                    CX_ORBIT + int(rr * math.cos(ang)),
                    CY_ORBIT + int(rr * math.sin(ang) * 0.88),
                ))
            polys.append(pts)
        return polys

    def draw(
        self,
        surface: pygame.Surface,
        satellites: list,
        debris_list: list,
        network,
        anim_t: float,
        display_positions: dict | None = None,
        screen_wh: tuple[int, int] | None = None,
        selected_sat=None,
        packet_tracer: bool = False,
        threat_pct: float = 0.0,
    ) -> None:
        if display_positions is None:
            display_positions = {s.sat_id: s.position for s in satellites}
            display_positions.update({d.debris_id: d.position for d in debris_list})
        _ = threat_pct

        self._draw_background(surface, anim_t)
        self._draw_earth(surface, anim_t)
        self._draw_orbital_ellipses(surface)

        sat_screen = {s.sat_id: _proj(display_positions.get(s.sat_id, s.position)) for s in satellites}
        gs_screen = {}
        for n, data in network.graph.nodes(data=True):
            if isinstance(n, str) and n.startswith("GS"):
                gs_screen[n] = _gs_border_pos(data["pos"])
        all_screen = {**sat_screen, **gs_screen}

        self._draw_isl_links(surface, network, sat_screen, gs_screen, all_screen, anim_t)
        if packet_tracer:
            self._draw_packet_tracer(surface, network, all_screen, anim_t)
        self._draw_inflight_packets(surface, network, display_positions, all_screen)

        self._draw_ground_stations(surface, network, sat_screen, gs_screen, anim_t)
        self._draw_sat_pair_warnings(surface, satellites, display_positions, anim_t)
        self._draw_danger_zones(surface, satellites, display_positions, anim_t)
        self._draw_debris(surface, debris_list, display_positions)
        self._draw_motion_trails(surface, satellites, display_positions, anim_t)
        self._draw_satellites(surface, satellites, display_positions, anim_t, selected_sat)
        self._draw_threat_bar(surface, satellites, anim_t)

        if packet_tracer and network.get_recent_packet_traces():
            self._draw_tracer_legend(surface, network)

        sw, sh = screen_wh or (VP_W, VP_H)
        self._draw_vignette(surface, sw, sh)

        if selected_sat is not None and self._font_popup:
            self._draw_inspector_bottom_left(surface, selected_sat, network, display_positions)

    # ── Background ────────────────────────────────────────────────────────────
    def _draw_background(self, surface, anim_t: float):
        pygame.draw.rect(surface, BG_DEEP, (0, 0, VP_W, VP_H))

        for x, y, r, g, b in _STARS_TINY:
            surface.set_at((x, y), (min(255, r), min(255, g), min(255, b)))

        for x, y, r, g, b in _STARS_MED:
            surface.set_at((x, y), (r, g, b))

        tw = 0.5 + 0.5 * math.sin(anim_t * 3.0)
        for x, y, ph in _STARS_BIG:
            a = int(180 + 75 * math.sin(anim_t * 2.2 + ph))
            a = max(80, min(255, a))
            c = (a, a, min(255, a + 20))
            pygame.draw.circle(surface, c, (x, y), 2)
            pygame.draw.circle(surface, (min(255, a + 40),) * 3, (x, y), 1)

    # ── Elliptical orbit rings ────────────────────────────────────────────────
    def _draw_orbital_ellipses(self, surface):
        ring = pygame.Surface((VP_W, VP_H), pygame.SRCALPHA)
        ring.fill((0, 0, 0, 0))
        a_ax = ORBITAL_RADIUS_KM * ORBIT_SCALE
        b_ax = a_ax * 0.35
        for plane in range(NUM_ORBITAL_PLANES):
            raan = _RAAN_GAP * plane
            pts = []
            for i in range(96):
                ang = 2 * math.pi * i / 96
                xe = a_ax * math.cos(ang)
                ye = b_ax * math.sin(ang)
                xr = xe * math.cos(raan) - ye * math.sin(raan)
                yr = xe * math.sin(raan) + ye * math.cos(raan)
                pts.append((CX_ORBIT + int(xr), CY_ORBIT + int(yr)))
            pygame.draw.lines(ring, (0x1A, 0x0A, 0x3A, 80), True, pts, 1)
        surface.blit(ring, (0, 0))

    # ── ISL solid + decorative link dots ─────────────────────────────────────
    def _draw_isl_links(self, surface, network, sat_screen, gs_screen, all_screen, anim_t):
        for u, v, data in network.graph.edges(data=True):
            if data.get("kind") != "isl":
                continue
            p1, p2 = all_screen.get(u), all_screen.get(v)
            if p1 is None or p2 is None:
                continue
            load = float(data.get("current_load", 0.0))
            col = _isl_rgb(load)
            pygame.draw.line(surface, col, p1, p2, 1)
            if load < 0.02:
                continue
            speed = 0.35
            for i in range(3):
                ph = (anim_t * speed + i / 3.0) % 1.0
                q1 = _lerp_pt(p1, p2, ph)
                pygame.draw.circle(surface, PKT_DOT, (int(q1[0]), int(q1[1])), 3)
                ph2 = (anim_t * speed + i / 3.0 + 0.5) % 1.0
                q2 = _lerp_pt(p2, p1, ph2)
                pygame.draw.circle(surface, PKT_DOT, (int(q2[0]), int(q2[1])), 3)

    def _draw_inflight_packets(self, surface, network, display_positions, all_screen):
        for pkt, progress in network.in_flight_packets:
            pos = _packet_pos_on_path(pkt.path, progress, all_screen)
            if pos is None:
                continue
            if isinstance(pkt, CollisionAlertPacket):
                col = (0xF4, 0xC0, 0xD1)
            elif isinstance(pkt, AvoidanceCommandPacket):
                col = (0xCE, 0xCB, 0xF6)
            else:
                col = (0xA0, 0x98, 0xE8)
            pygame.draw.circle(surface, col, pos, 3)

    def _draw_packet_tracer(self, surface, network, all_screen, anim_t):
        ov = self._overlay
        ov.fill((0, 0, 0, 0))
        traces = network.get_recent_packet_traces()
        for idx, (path, ptype, _src, _dst) in enumerate(traces):
            col = _TRACER_PALETTE[idx % len(_TRACER_PALETTE)]
            pts = []
            for node in path:
                p = all_screen.get(node)
                if p:
                    pts.append(p)
            if len(pts) < 2:
                continue
            for i in range(len(pts) - 1):
                pygame.draw.line(ov, (*col, 200), pts[i], pts[i + 1], 2)
            phase = (anim_t * 0.4 + idx * 0.17) % 1.0
            nseg = len(pts) - 1
            seg_f = phase * nseg
            si = min(int(seg_f), nseg - 1)
            tt = seg_f - si
            ax, ay = pts[si]
            bx, by = pts[si + 1]
            px = int(ax + (bx - ax) * tt)
            py = int(ay + (by - ay) * tt)
            pygame.draw.circle(ov, (*col, 255), (px, py), 5)
        surface.blit(ov, (0, 0))

    def _draw_tracer_legend(self, surface, network):
        traces = network.get_recent_packet_traces()
        if not traces:
            return
        lines = [f"{t}  {'->'.join(str(n) for n in p)}" for p, t, _, _ in traces]
        mw = max(self._font_sat.render(s, True, (255, 255, 255)).get_width() for s in lines) + 24
        mh = 18 * len(traces) + 12
        x0 = VP_W - mw - 10
        y0 = THREAT_BAR_H + 10
        bg = pygame.Surface((mw, mh), pygame.SRCALPHA)
        bg.fill((13, 0, 24, 200))
        surface.blit(bg, (x0 - 4, y0 - 4))
        for idx, (path, ptype, _s, _d) in enumerate(traces):
            col = _TRACER_PALETTE[idx % len(_TRACER_PALETTE)]
            pygame.draw.circle(surface, col, (x0 + 6, y0 + 9 + idx * 18), 4)
            txt = self._font_sat.render(lines[idx], True, (0xCE, 0xCB, 0xF6))
            surface.blit(txt, (x0 + 16, y0 + 2 + idx * 18))

    # ── Earth ─────────────────────────────────────────────────────────────────
    def _draw_earth(self, surface, anim_t):
        pygame.draw.circle(surface, EARTH_FILL, (CX_ORBIT, CY_ORBIT), EARTH_R_PX)
        # Terminator: lighter half (day side, approximate)
        term = pygame.Surface((VP_W, VP_H), pygame.SRCALPHA)
        term_pts = [(CX_ORBIT, CY_ORBIT)]
        for i in range(33):
            ang = -math.pi / 2 + math.pi * i / 32
            term_pts.append((
                CX_ORBIT + int(EARTH_R_PX * math.cos(ang)),
                CY_ORBIT + int(EARTH_R_PX * math.sin(ang)),
            ))
        pygame.draw.polygon(term, (*EARTH_TERM_LIT, 45), term_pts)
        surface.blit(term, (0, 0))
        for poly in self._continent_polys:
            pygame.draw.polygon(surface, EARTH_LAND, poly)
        for mult, al in zip((1.3, 1.6, 2.0, 2.5, 3.2), (35, 22, 14, 8, 4)):
            r = int(EARTH_R_PX * mult)
            dim = r * 2 + 4
            halo = pygame.Surface((dim, dim), pygame.SRCALPHA)
            pygame.draw.circle(halo, (*HALO_PURPLE, al), (dim // 2, dim // 2), r)
            surface.blit(halo, (CX_ORBIT - dim // 2, CY_ORBIT - dim // 2))

    # ── Ground stations ───────────────────────────────────────────────────────
    def _draw_ground_stations(self, surface, network, sat_screen, gs_screen, anim_t):
        if self._font_gs is None:
            return
        uplink_layer = pygame.Surface((VP_W, VP_H), pygame.SRCALPHA)
        uplink_layer.fill((0, 0, 0, 0))
        pulse = (math.sin(anim_t * 2.0) + 1.0) * 0.5
        dash_phase = anim_t * 38.0

        for n, data in network.graph.nodes(data=True):
            if not (isinstance(n, str) and n.startswith("GS")):
                continue
            sx, sy = gs_screen[n]

            for spread in (20, 35, 50):
                rad = int(15 + pulse * spread)
                a = int((1.0 - pulse) * 80)
                dim = rad * 2 + 4
                rs = pygame.Surface((dim, dim), pygame.SRCALPHA)
                pygame.draw.circle(rs, (*GS_COL, a), (dim // 2, dim // 2), rad, 1)
                surface.blit(rs, (sx - dim // 2, sy - dim // 2))

            diamond = [(sx, sy - 5), (sx + 5, sy), (sx, sy + 5), (sx - 5, sy)]
            pygame.draw.polygon(surface, GS_COL, diamond)

            for sid in network.graph.neighbors(n):
                if isinstance(sid, int) and network.graph[n][sid].get("kind") == "uplink":
                    p2 = sat_screen.get(sid)
                    if p2:
                        _dashed_line_alpha(
                            uplink_layer,
                            (sx, sy),
                            p2,
                            (*GS_COL, 200),
                            dash=6.0,
                            gap=5.0,
                            phase=dash_phase,
                        )

            lbl = self._font_gs.render(n, True, (0xF4, 0xC0, 0xD1))
            lw, lh = lbl.get_width() + 12, lbl.get_height() + 6
            pill = pygame.Surface((lw, lh), pygame.SRCALPHA)
            pygame.draw.rect(pill, (0x1A, 0x00, 0x30), (0, 0, lw, lh), border_radius=lh // 2)
            pygame.draw.rect(
                pill,
                (0x99, 0x35, 0x56),
                (0, 0, lw, lh),
                1,
                border_radius=lh // 2,
            )
            pill.blit(lbl, (6, lh // 2 - lbl.get_height() // 2))
            dx, dy = CX_ORBIT - sx, CY_ORBIT - sy
            dist = math.hypot(dx, dy) or 1.0
            ox = int(-dx / dist * 30)
            oy = int(-dy / dist * 30)
            surface.blit(pill, (sx + ox - lw // 2, sy + oy - lh // 2))

        surface.blit(uplink_layer, (0, 0))

    # ── Pairwise warning lines ────────────────────────────────────────────────
    def _draw_sat_pair_warnings(self, surface, satellites, display_positions, anim_t):
        thr = WARNING_THRESHOLD_KM
        n = len(satellites)
        pulse = 0.5 + 0.5 * math.sin(anim_t * 4.0)
        col = (int(212 + 43 * pulse), int(83 + 40 * pulse), int(126 + 30 * pulse))
        for i in range(n):
            for j in range(i + 1, n):
                a, b = satellites[i], satellites[j]
                if a.state != State.WARNING and b.state != State.WARNING:
                    continue
                pa = display_positions.get(a.sat_id, a.position)
                pb = display_positions.get(b.sat_id, b.position)
                if OrbitalMechanics.distance_3d(pa, pb) > thr:
                    continue
                sa, sb = _proj(pa), _proj(pb)
                pygame.draw.line(surface, col, sa, sb, 2)

    # ── Danger zones ──────────────────────────────────────────────────────────
    def _draw_danger_zones(self, surface, satellites, display_positions, anim_t):
        wr = self._warn_r_px
        dash_off = (anim_t * 8) % 12
        for sat in satellites:
            if sat.state != State.WARNING:
                continue
            pos = display_positions.get(sat.sat_id, sat.position)
            sx, sy = _proj(pos)
            dz = pygame.Surface((wr * 2 + 4, wr * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(dz, (0xD4, 0x53, 0x7E, 25), (wr + 2, wr + 2), wr)
            surface.blit(dz, (sx - wr - 2, sy - wr - 2))
            # dashed border
            nseg = 48
            for k in range(nseg):
                a0 = 2 * math.pi * k / nseg + dash_off * 0.05
                a1 = 2 * math.pi * (k + 0.4) / nseg + dash_off * 0.05
                if k % 2 == 0:
                    x1 = sx + int(wr * math.cos(a0))
                    y1 = sy + int(wr * math.sin(a0))
                    x2 = sx + int(wr * math.cos(a1))
                    y2 = sy + int(wr * math.sin(a1))
                    pygame.draw.line(surface, (0xD4, 0x53, 0x7E), (x1, y1), (x2, y2), 1)

    def _draw_debris(self, surface, debris_list, display_positions):
        col = (180, 60, 60)
        for d in debris_list:
            pos = display_positions.get(d.debris_id, d.position)
            sx, sy = _proj(pos)
            s = 5
            pygame.draw.line(surface, col, (sx - s, sy - s), (sx + s, sy + s), 1)
            pygame.draw.line(surface, col, (sx - s, sy + s), (sx + s, sy - s), 1)

    # ── Trails ──────────────────────────────────────────────────────────────
    def _draw_motion_trails(self, surface, satellites, display_positions, anim_t):
        for sat in satellites:
            pos = display_positions.get(sat.sat_id, sat.position)
            sx, sy = _proj(pos)
            tr = self._trails[sat.sat_id]
            tr.append((sx, sy))
            st = SAT_STYLE[sat.state]
            base = st["core"]
            pts = list(tr)
            if len(pts) < 2:
                continue
            for i in range(len(pts) - 1):
                t0 = i / max(1, len(pts) - 1)
                alpha = int(180 * (1.0 - t0))
                if i == len(pts) - 2:
                    alpha = 200
                if alpha < 8:
                    continue
                seg = pygame.Surface((VP_W, VP_H), pygame.SRCALPHA)
                pygame.draw.line(seg, (*base, alpha), pts[i], pts[i + 1], 2)
                surface.blit(seg, (0, 0))

    # ── Satellites (3-layer) ─────────────────────────────────────────────────
    def _draw_satellites(self, surface, satellites, display_positions, anim_t, selected_sat):
        for sat in satellites:
            pos = display_positions.get(sat.sat_id, sat.position)
            sx, sy = _proj(pos)
            st = SAT_STYLE[sat.state]
            core, glow_c = st["core"], st["glow"]

            og = pygame.Surface((40, 40), pygame.SRCALPHA)
            pygame.draw.circle(og, (*glow_c, 50), (20, 20), 18)
            surface.blit(og, (sx - 20, sy - 20))
            mg = pygame.Surface((20, 20), pygame.SRCALPHA)
            pygame.draw.circle(mg, (*glow_c, 110), (10, 10), 9)
            surface.blit(mg, (sx - 10, sy - 10))
            pygame.draw.circle(surface, core, (sx, sy), 5)

            if sat.state == State.WARNING:
                s6 = abs(math.sin(anim_t * 6.0))
                pr = int(s6 * 10.0 + 14.0)
                fa = int(s6 * 140.0)
                dim = pr * 2 + 4
                rg = pygame.Surface((dim, dim), pygame.SRCALPHA)
                pygame.draw.circle(
                    rg,
                    (*SAT_STYLE[State.WARNING]["core"], fa),
                    (dim // 2, dim // 2),
                    pr,
                    2,
                )
                surface.blit(rg, (sx - dim // 2, sy - dim // 2))

            if sat.state == State.MANEUVERING:
                mx, my, mz = sat.maneuver_vector
                tip_3d = (pos[0] + mx * 8000, pos[1] + my * 8000, pos[2] + mz * 8000)
                tx, ty = _proj(tip_3d)
                dx, dy = tx - sx, ty - sy
                ln = math.hypot(dx, dy) or 1.0
                if ln > 2:
                    ux, uy = dx / ln, dy / ln
                    L = min(30, ln)
                    ex = int(sx + ux * L)
                    ey = int(sy + uy * L)
                    pygame.draw.line(surface, SAT_STYLE[State.MANEUVERING]["core"], (sx, sy), (ex, ey), 2)
                    base = (ex, ey)
                    left = (int(ex - ux * 8 - uy * 5), int(ey - uy * 8 + ux * 5))
                    right = (int(ex - ux * 8 + uy * 5), int(ey - uy * 8 - ux * 5))
                    pygame.draw.polygon(surface, SAT_STYLE[State.MANEUVERING]["core"], [(ex, ey), left, right])

            if selected_sat is not None and sat.sat_id == selected_sat.sat_id:
                pygame.draw.circle(surface, (255, 255, 255), (sx, sy), 18, 2)

            if self._font_sat:
                lbl = self._font_sat.render(f"S{sat.sat_id}", True, (0xAF, 0xA9, 0xEC))
                surface.blit(lbl, (sx + 10, sy - 6))

    def _draw_threat_bar(self, surface, satellites: list, anim_t: float):
        near_misses = sum(getattr(s, "near_miss_count", 0) for s in satellites)
        warning_count = sum(1 for s in satellites if s.state == State.WARNING)
        maneuvering_count = sum(1 for s in satellites if s.state == State.MANEUVERING)
        pct = min(
            100.0,
            near_misses * 8.0 + warning_count * 15.0 + maneuvering_count * 25.0,
        )

        pygame.draw.rect(surface, (0x0A, 0x00, 0x18), (0, 0, VP_W, THREAT_BAR_H))
        pygame.draw.line(
            surface,
            (0x2A, 0x1A, 0x4A),
            (0, THREAT_BAR_H - 1),
            (VP_W, THREAT_BAR_H - 1),
            1,
        )

        bar_w, bar_h = 300, 10
        bx = (VP_W - bar_w) // 2
        by = (THREAT_BAR_H - bar_h) // 2
        pygame.draw.rect(surface, (0x1A, 0x0A, 0x3A), (bx, by, bar_w, bar_h), border_radius=5)

        fill = int(bar_w * pct / 100.0)
        if pct <= 30:
            col = (0x7F, 0x77, 0xDD)
        elif pct <= 60:
            col = (0xEF, 0x9F, 0x27)
        else:
            pulse = 0.85 + 0.15 * math.sin(anim_t * 6.0)
            col = (int(0xD4 * pulse), int(0x53 * pulse), int(0x7E * pulse))
        if fill > 0:
            pygame.draw.rect(surface, col, (bx, by, fill, bar_h), border_radius=5)

        if pct <= 30:
            tc = (0x7F, 0x77, 0xDD)
        elif pct <= 60:
            tc = (0xEF, 0x9F, 0x27)
        else:
            pulse = 0.85 + 0.15 * math.sin(anim_t * 6.0)
            tc = (int(0xD4 * pulse), int(0x53 * pulse), int(0x7E * pulse))

        if self._font_threat_label and self._font_threat_pct:
            tl = self._font_threat_label.render("THREAT LEVEL", True, (0x7F, 0x77, 0xDD))
            surface.blit(tl, (12, (THREAT_BAR_H - tl.get_height()) // 2))
            tr = self._font_threat_pct.render(f"{pct:.0f}%", True, tc)
            surface.blit(tr, (VP_W - 14 - tr.get_width(), (THREAT_BAR_H - tr.get_height()) // 2))

    def _draw_vignette(self, surface, screen_w: int, screen_h: int):
        now = time.monotonic()
        if now >= self._vignette_start + self._vignette_duration:
            return
        u = 1.0 - (now - self._vignette_start) / self._vignette_duration
        peak = 120 * max(0.0, min(1.0, math.sin(u * math.pi)))
        if peak < 1:
            return
        v = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
        pink = (0xFF, 0x78, 0xB8)
        for t in range(40):
            a = int(peak * (1.0 - t / 40.0))
            pygame.draw.rect(v, (*pink, a), (t, t, screen_w - 2 * t, screen_h - 2 * t), 1)
        surface.blit(v, (0, 0))

    def _draw_inspector_bottom_left(self, surface, sat, network, display_positions):
        pos = display_positions.get(sat.sat_id, sat.position)
        spd = math.sqrt(sum(v * v for v in sat.velocity))
        lines = [
            f"ID {sat.sat_id}   {sat.state.name}",
            f"Pos km  {pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}",
            f"Speed   {spd:.4f} km/s",
            f"ISL     {self._isl_neighbor_ids(network, sat.sat_id)}",
            f"Pkts    sent {sat.messages_sent}  recv {sat.messages_received}",
            f"Near misses  {sat.near_miss_count}",
        ]
        pad = 12
        lh = 16
        w = max(self._font_popup.render(s, True, (255, 255, 255)).get_width() for s in lines) + pad * 2
        h = pad * 2 + len(lines) * lh
        bx, by = 14, VP_H - h - 16
        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(bg, (13, 0, 24, 220), (0, 0, w, h), border_radius=8)
        pygame.draw.rect(bg, (0x7F, 0x77, 0xDD), (0, 0, w, h), 2, border_radius=8)
        surface.blit(bg, (bx, by))
        y = by + pad
        for s in lines:
            surf = self._font_popup.render(s, True, (0xCE, 0xCB, 0xF6))
            surface.blit(surf, (bx + pad, y))
            y += lh

    def pick_satellite_at(
        self, satellites, mx, my, radius_px=20.0, display_positions=None
    ):
        if mx < 0 or mx >= VP_W or my < THREAT_BAR_H or my >= VP_H:
            return None
        best, best_d = None, radius_px * radius_px
        for sat in satellites:
            pos = display_positions.get(sat.sat_id, sat.position) if display_positions else sat.position
            sx, sy = _proj(pos)
            dx, dy = sx - mx, sy - my
            d2 = dx * dx + dy * dy
            if d2 <= best_d:
                best_d, best = d2, sat
        return best

    def _isl_neighbor_ids(self, network, sat_id: int) -> list[int]:
        out = []
        if not network.graph.has_node(sat_id):
            return out
        for n in network.graph.neighbors(sat_id):
            if isinstance(n, int) and network.graph[sat_id][n].get("kind") == "isl":
                out.append(n)
        return sorted(out)
