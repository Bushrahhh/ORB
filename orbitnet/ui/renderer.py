import math
import random
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pygame
from config import (
    ORBITAL_RADIUS_KM, NUM_ORBITAL_PLANES, COLORS,
    WARNING_THRESHOLD_KM, COLLISION_THRESHOLD_KM,
)
from physics import OrbitalMechanics
from agents import State
from packets import CollisionAlertPacket, TelemetryPacket, AvoidanceCommandPacket

# ── Viewport constants ──────────────────────────────────────────────────────
VP_W = 900
VP_H = 900
CX   = VP_W // 2   # 450
CY   = VP_H // 2   # 450

EARTH_R_PX   = 120
ORBIT_SCALE  = VP_W * 0.35 / ORBITAL_RADIUS_KM   # px/km

_INC_RAD  = math.radians(53.0)
_RAAN_GAP = math.radians(60.0)
_AZ       = math.radians(20.0)
_EL       = math.radians(25.0)
_COS_AZ, _SIN_AZ = math.cos(_AZ), math.sin(_AZ)
_COS_EL, _SIN_EL = math.cos(_EL), math.sin(_EL)

# ── Pre-baked star field (fixed seed for consistency) ───────────────────────
_rng = random.Random(31337)
_STARS = [
    (_rng.randint(0, VP_W - 1), _rng.randint(0, VP_H - 1), _rng.randint(80, 200))
    for _ in range(220)
]

# ── Color aliases ───────────────────────────────────────────────────────────
_C = COLORS
BG          = _C["BACKGROUND"]
EARTH_C     = _C["EARTH"]
EARTH_BD    = _C["EARTH_BORDER"]
SAT_NOM     = _C["SAT_NOMINAL"]
SAT_WARN    = _C["SAT_WARNING"]
SAT_MAN     = _C["SAT_MANEUVERING"]
SAT_SAFE    = _C["SAT_SAFE"]
ISL_LO      = _C["ISL_ACTIVE"]
ISL_HI      = _C["ISL_CONGESTED"]
DANGER_C    = _C["DANGER_ZONE"]
PKT_ALERT   = _C["ALERT_PACKET"]
PKT_DATA    = _C["DATA_PACKET"]
GS_C        = _C["GROUND_STATION"]
TXT_PRI     = _C["TEXT_PRIMARY"]
TXT_SEC     = _C["TEXT_SECONDARY"]

# ── State → color map ───────────────────────────────────────────────────────
_STATE_COLOR = {
    State.NOMINAL:     SAT_NOM,
    State.WARNING:     SAT_WARN,
    State.MANEUVERING: SAT_MAN,
    State.SAFE:        SAT_SAFE,
}


def _proj(pos_3d: tuple) -> tuple[int, int]:
    """Project 3-D ECI position to the 900×900 simulation viewport."""
    x, y, z = pos_3d
    x1 = x * _COS_AZ - y * _SIN_AZ
    y1 = x * _SIN_AZ + y * _COS_AZ
    x2 = x1
    y2 = y1 * _COS_EL - z * _SIN_EL
    return (CX + int(x2 * ORBIT_SCALE), CY - int(y2 * ORBIT_SCALE))


def _lerp_pt(p1, p2, t):
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def _draw_arrow(surf, p1, p2, color, shaft_w=2, head_len=10, head_w=5):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < 4:
        return
    ux, uy = dx / length, dy / length
    pygame.draw.line(surf, color, p1, p2, shaft_w)
    # Arrowhead polygon
    tip  = p2
    base = (p2[0] - ux * head_len, p2[1] - uy * head_len)
    left = (base[0] - uy * head_w, base[1] + ux * head_w)
    rght = (base[0] + uy * head_w, base[1] - ux * head_w)
    pygame.draw.polygon(surf, color, [tip, left, rght])


def _gs_border_pos(gs_3d):
    """Map a GS ECEF position to a point on the visual Earth circle border."""
    raw_x, raw_y = _proj(gs_3d)
    dx, dy = raw_x - CX, raw_y - CY
    dist = math.hypot(dx, dy) or 1.0
    return (int(CX + dx / dist * EARTH_R_PX), int(CY + dy / dist * EARTH_R_PX))


def _packet_pos_on_path(path: list, progress: float,
                        node_screen: dict) -> tuple | None:
    """Interpolate a packet's screen position along its routed path."""
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


# ── Pre-compute orbital ring point lists ────────────────────────────────────
def _ring_points(plane: int) -> list[tuple[int, int]]:
    raan = _RAAN_GAP * plane
    cos_r, sin_r = math.cos(raan), math.sin(raan)
    pts = []
    for i in range(90):
        u = 2 * math.pi * i / 90
        x_b = ORBITAL_RADIUS_KM * math.cos(u)
        y_b = ORBITAL_RADIUS_KM * math.sin(u) * math.cos(_INC_RAD)
        z   = ORBITAL_RADIUS_KM * math.sin(u) * math.sin(_INC_RAD)
        x = x_b * cos_r - y_b * sin_r
        y = x_b * sin_r + y_b * cos_r
        pts.append(_proj((x, y, z)))
    return pts


_RING_PTS = [_ring_points(p) for p in range(NUM_ORBITAL_PLANES)]


# ════════════════════════════════════════════════════════════════════════════
class OrbitalRenderer:
    def __init__(self):
        self._font_sat  = None
        self._font_gs   = None
        # Reusable alpha surfaces (allocated after pygame.init)
        self._overlay: pygame.Surface | None = None
        self._glow_surf: pygame.Surface | None = None
        self._warn_r_px = max(1, int(WARNING_THRESHOLD_KM * ORBIT_SCALE))

    def init_fonts(self):
        self._font_sat = pygame.font.SysFont("monospace", 9)
        self._font_gs  = pygame.font.SysFont("monospace", 10, bold=True)
        self._overlay   = pygame.Surface((VP_W, VP_H), pygame.SRCALPHA)
        glow_r = EARTH_R_PX + 50
        self._glow_surf = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)

    # ── Master draw call ────────────────────────────────────────────────────
    def draw(self, surface: pygame.Surface, satellites: list,
             debris_list: list, network, anim_t: float) -> None:
        self._draw_background(surface)
        self._draw_orbital_rings(surface)
        self._draw_network_edges(surface, satellites, network, anim_t)
        self._draw_packets(surface, satellites, network)
        self._draw_earth(surface, anim_t)
        self._draw_ground_stations(surface, network)
        self._draw_danger_zones(surface, satellites, anim_t)
        self._draw_debris(surface, debris_list)
        self._draw_satellites(surface, satellites, anim_t)
        self._draw_maneuver_arrows(surface, satellites)

    # ── Background + stars ──────────────────────────────────────────────────
    def _draw_background(self, surface: pygame.Surface) -> None:
        # Fill only the left viewport — dashboard draws its own BG
        pygame.draw.rect(surface, BG, (0, 0, VP_W, VP_H))
        for sx, sy, brightness in _STARS:
            b = brightness
            surface.set_at((sx, sy), (b // 4, 0, b // 3))
            if brightness > 170:            # brighter stars get a 1-px halo
                surface.set_at((sx + 1, sy), (b // 8, 0, b // 6))
                surface.set_at((sx, sy + 1), (b // 8, 0, b // 6))

    # ── Orbital path rings ──────────────────────────────────────────────────
    def _draw_orbital_rings(self, surface: pygame.Surface) -> None:
        ov = self._overlay
        ov.fill((0, 0, 0, 0))
        ring_alpha = 28
        for plane, pts in enumerate(_RING_PTS):
            col = (*EARTH_BD, ring_alpha)
            pygame.draw.lines(ov, col, True, pts, 1)
        surface.blit(ov, (0, 0))

    # ── ISL + uplink edges ──────────────────────────────────────────────────
    def _draw_network_edges(self, surface, satellites, network, anim_t):
        ov = self._overlay
        ov.fill((0, 0, 0, 0))

        sat_screen = {s.sat_id: _proj(s.position) for s in satellites}
        gs_screen  = {}
        for n, data in network.graph.nodes(data=True):
            if isinstance(n, str) and n.startswith("GS"):
                gs_screen[n] = _gs_border_pos(data["pos"])
        all_screen = {**sat_screen, **gs_screen}

        for u, v, data in network.graph.edges(data=True):
            kind = data.get("kind", "")
            p1 = all_screen.get(u)
            p2 = all_screen.get(v)
            if p1 is None or p2 is None:
                continue

            if kind == "isl":
                load = data.get("current_load", 0.0)
                if load < 0.3:
                    color, alpha = ISL_LO, 70
                elif load < 0.7:
                    # interpolate between ISL_LO and SAT_NOM
                    t = (load - 0.3) / 0.4
                    color = tuple(int(ISL_LO[i] + (SAT_NOM[i] - ISL_LO[i]) * t) for i in range(3))
                    alpha = 130
                else:
                    color, alpha = ISL_HI, 200
                pygame.draw.line(ov, (*color, alpha), p1, p2, 1)

            elif kind == "uplink":
                # Dashed uplink — animate with anim_t for moving dashes
                dash_len = 8
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                seg_len = math.hypot(dx, dy)
                if seg_len < 1:
                    continue
                n_dashes = int(seg_len / dash_len)
                offset = (anim_t * 30) % dash_len
                for k in range(n_dashes + 1):
                    t0 = ((k * dash_len + offset) % seg_len) / seg_len
                    t1 = ((k * dash_len + offset + dash_len * 0.5) % seg_len) / seg_len
                    if t1 > t0:
                        pa = _lerp_pt(p1, p2, t0)
                        pb = _lerp_pt(p1, p2, t1)
                        pygame.draw.line(ov, (*GS_C, 160),
                                         (int(pa[0]), int(pa[1])),
                                         (int(pb[0]), int(pb[1])), 1)

        surface.blit(ov, (0, 0))

    # ── Packet animation dots ───────────────────────────────────────────────
    def _draw_packets(self, surface, satellites, network):
        sat_screen = {s.sat_id: _proj(s.position) for s in satellites}
        gs_screen  = {}
        for n, data in network.graph.nodes(data=True):
            if isinstance(n, str) and n.startswith("GS"):
                gs_screen[n] = _gs_border_pos(data["pos"])
        all_screen = {**sat_screen, **gs_screen}

        for pkt, progress in network.in_flight_packets:
            pos = _packet_pos_on_path(pkt.path, progress, all_screen)
            if pos is None:
                continue
            if isinstance(pkt, CollisionAlertPacket):
                col = PKT_ALERT
                r = 4
            elif isinstance(pkt, AvoidanceCommandPacket):
                col = (220, 220, 255)
                r = 3
            else:
                col = PKT_DATA
                r = 3
            pygame.draw.circle(surface, col, pos, r)
            # Tiny glow ring
            pygame.draw.circle(surface, (*col, 80), pos, r + 2, 1)

    # ── Earth ───────────────────────────────────────────────────────────────
    def _draw_earth(self, surface, anim_t):
        pulse = 0.6 + 0.4 * math.sin(anim_t * 1.8)
        glow_r = EARTH_R_PX + 50
        gs = self._glow_surf
        gs.fill((0, 0, 0, 0))

        # Glow rings
        for layer in range(10):
            r = glow_r - layer * 5
            a = int(pulse * 55 * (10 - layer) / 10)
            pygame.draw.circle(gs, (*EARTH_BD, a), (glow_r, glow_r), r, 2)
        surface.blit(gs, (CX - glow_r, CY - glow_r))

        # Solid Earth fill
        pygame.draw.circle(surface, EARTH_C, (CX, CY), EARTH_R_PX)
        # Border (double ring)
        pygame.draw.circle(surface, EARTH_BD, (CX, CY), EARTH_R_PX, 2)
        inner_col = tuple(min(255, c + 30) for c in EARTH_BD)
        pygame.draw.circle(surface, inner_col, (CX, CY), EARTH_R_PX - 3, 1)

    # ── Ground stations ─────────────────────────────────────────────────────
    def _draw_ground_stations(self, surface, network):
        if self._font_gs is None:
            return
        for n, data in network.graph.nodes(data=True):
            if not (isinstance(n, str) and n.startswith("GS")):
                continue
            sx, sy = _gs_border_pos(data["pos"])
            # Triangle pointing toward Earth center
            tip = (sx, sy)
            dx, dy = CX - sx, CY - sy
            dist = math.hypot(dx, dy) or 1.0
            ux, uy = dx / dist, dy / dist
            # Two base points perpendicular to inward direction
            base = (sx - ux * 12, sy - uy * 12)
            lx = int(base[0] - uy * 6)
            ly = int(base[1] + ux * 6)
            rx = int(base[0] + uy * 6)
            ry = int(base[1] - ux * 6)
            pygame.draw.polygon(surface, GS_C, [tip, (lx, ly), (rx, ry)])
            pygame.draw.polygon(surface, (255, 255, 255), [tip, (lx, ly), (rx, ry)], 1)
            lbl = self._font_gs.render(n, True, GS_C)
            # Label offset away from Earth
            ox = int(-ux * 20)
            oy = int(-uy * 20)
            surface.blit(lbl, (sx + ox - lbl.get_width() // 2,
                                sy + oy - lbl.get_height() // 2))

    # ── Danger zones (WARNING satellites) ───────────────────────────────────
    def _draw_danger_zones(self, surface, satellites, anim_t):
        ov = self._overlay
        ov.fill((0, 0, 0, 0))
        wr = self._warn_r_px
        pulse = int(20 + 15 * math.sin(anim_t * 3.0))
        for sat in satellites:
            if sat.state not in (State.WARNING, State.MANEUVERING):
                continue
            sx, sy = _proj(sat.position)
            a_fill = max(0, min(255, pulse))
            pygame.draw.circle(ov, (*DANGER_C, a_fill), (sx, sy), wr)
            pygame.draw.circle(ov, (*DANGER_C, a_fill + 40), (sx, sy), wr, 2)
        surface.blit(ov, (0, 0))

    # ── Debris (X marks) ────────────────────────────────────────────────────
    def _draw_debris(self, surface, debris_list):
        col = (180, 60, 60)
        for d in debris_list:
            sx, sy = _proj(d.position)
            s = 5
            pygame.draw.line(surface, col, (sx - s, sy - s), (sx + s, sy + s), 1)
            pygame.draw.line(surface, col, (sx - s, sy + s), (sx + s, sy - s), 1)
            # Faint halo
            pygame.draw.circle(surface, (100, 30, 30), (sx, sy), s + 3, 1)

    # ── Satellites ──────────────────────────────────────────────────────────
    def _draw_satellites(self, surface, satellites, anim_t):
        ov = self._overlay
        for sat in satellites:
            sx, sy = _proj(sat.position)
            col = _STATE_COLOR[sat.state]
            r = 6

            if sat.state == State.MANEUVERING:
                pulse = 0.5 + 0.5 * math.sin(anim_t * 10.0)
                r = int(5 + 4 * pulse)
                ov.fill((0, 0, 0, 0))
                pygame.draw.circle(ov, (*col, int(80 * pulse)), (sx, sy), r + 6)
                surface.blit(ov, (0, 0))
            elif sat.state == State.WARNING:
                ov.fill((0, 0, 0, 0))
                pygame.draw.circle(ov, (*col, 60), (sx, sy), r + 4)
                surface.blit(ov, (0, 0))

            pygame.draw.circle(surface, col, (sx, sy), r)
            pygame.draw.circle(surface, (255, 255, 255), (sx, sy), r, 1)

            if self._font_sat:
                lbl = self._font_sat.render(f"S{sat.sat_id}", True, TXT_SEC)
                surface.blit(lbl, (sx + r + 2, sy - 4))

    # ── Maneuver arrows ──────────────────────────────────────────────────────
    def _draw_maneuver_arrows(self, surface, satellites):
        for sat in satellites:
            if sat.state != State.MANEUVERING:
                continue
            sx, sy = _proj(sat.position)
            mx, my, mz = sat.maneuver_vector
            mag = math.hypot(mx, my)
            if mag < 1e-9:
                continue
            # Project delta-v direction: use position + scaled maneuver vector
            tip_3d = (
                sat.position[0] + mx * 5000,
                sat.position[1] + my * 5000,
                sat.position[2] + mz * 5000,
            )
            tx, ty = _proj(tip_3d)
            _draw_arrow(surface, (sx, sy), (tx, ty), SAT_MAN, shaft_w=2,
                        head_len=8, head_w=5)
