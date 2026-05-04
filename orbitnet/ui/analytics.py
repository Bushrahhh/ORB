"""
ORB — CCN Analytics Panel
Full-screen analytics overlay: 8 live-updating panels covering orbital mechanics,
ISL link budget, packet delivery, per-satellite utilisation, and CCN graph metrics.
Press P to toggle from the main simulation view.
"""
import math
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pygame
from config import (
    ORBITAL_RADIUS_KM, ORBITAL_VELOCITY_KM_S, EARTH_RADIUS_KM,
    NUM_SATELLITES, NUM_ORBITAL_PLANES, ISL_MAX_RANGE_KM,
    COLLISION_THRESHOLD_KM, WARNING_THRESHOLD_KM,
)
from agents import State
from physics import OrbitalMechanics

# ─── Pre-computed physical constants ─────────────────────────────────────────
_J2        = 1.08263e-3
_INC_RAD   = math.radians(53.0)
_OMEGA     = ORBITAL_VELOCITY_KM_S / ORBITAL_RADIUS_KM          # rad/s
_RAAN_RATE = (-1.5 * _OMEGA * _J2
              * (EARTH_RADIUS_KM / ORBITAL_RADIUS_KM) ** 2
              * math.cos(_INC_RAD))                              # rad/s
_RAAN_DEG_S  = _RAAN_RATE * (180.0 / math.pi)
_RAAN_DEG_D  = _RAAN_DEG_S * 86400.0                            # °/day

_C_KM_S      = 299_792.458                                      # km/s
_MAX_DELAY_MS = ISL_MAX_RANGE_KM / (_C_KM_S / 1000.0)          # ms

_F_GHZ       = 26.5                                             # Ka-band carrier
_FSPL_DB     = (20 * math.log10(ISL_MAX_RANGE_KM * 1e3)
                + 20 * math.log10(_F_GHZ * 1e9)
                + 20 * math.log10(4 * math.pi / 3e8))           # dB

_DOPPLER_KHZ = (_F_GHZ * 1e9 * ORBITAL_VELOCITY_KM_S * 1e3
                / 3e8 / 1e3)                                    # kHz (max, head-on)

_B_MHZ       = 100.0                                            # ISL bandwidth MHz
_SNR_DB      = 30.0                                             # assumed SNR
_SNR_LIN     = 10 ** (_SNR_DB / 10.0)
_SHANNON_MBPS = _B_MHZ * math.log2(1.0 + _SNR_LIN)             # ≈ 997 Mbps

_T_PERIOD    = 2.0 * math.pi * ORBITAL_RADIUS_KM / ORBITAL_VELOCITY_KM_S  # s

# ─── Palette ─────────────────────────────────────────────────────────────────
BG         = (5, 0, 14)
PANEL_BG   = (11, 0, 24)
BORDER     = (83, 74, 183)
ACCENT     = (127, 119, 221)
PINK       = (212, 83, 126)
L_PINK     = (237, 147, 177)
TXT        = (206, 203, 246)
TXT2       = (127, 119, 221)
GOOD       = (93, 202, 165)
WARN_COL   = (239, 159, 39)
DANGER_COL = (240, 149, 149)
GRID_C     = (28, 8, 52)
HDR_BG     = (18, 0, 36)
SAT_COLORS = {
    State.NOMINAL:     (127, 119, 221),
    State.WARNING:     (212, 83, 126),
    State.MANEUVERING: (237, 147, 177),
    State.SAFE:        (175, 169, 236),
}

# ─── Layout (1400 × 900) ──────────────────────────────────────────────────────
W, H       = 1400, 900
TITLE_H    = 46
ROW1_Y     = TITLE_H + 4
ROW1_H     = 230
ROW2_Y     = ROW1_Y + ROW1_H + 4
ROW2_H     = 204
ROW3_Y     = ROW2_Y + ROW2_H + 4
ROW3_H     = H - ROW3_Y - 2

# Top row: 3 equal charts
_CW = (W - 16) // 3
_R1 = [pygame.Rect(4 + i * (_CW + 4), ROW1_Y, _CW, ROW1_H) for i in range(3)]

# Middle row: per-sat bars | state pie | proximity timeline
_R2 = [
    pygame.Rect(4,   ROW2_Y, 570, ROW2_H),
    pygame.Rect(578, ROW2_Y, 214, ROW2_H),
    pygame.Rect(796, ROW2_Y, 600, ROW2_H),
]

# Bottom row: formulas panel | satellite table
_R3 = [
    pygame.Rect(4,   ROW3_Y, 694, ROW3_H),
    pygame.Rect(702, ROW3_Y, 694, ROW3_H),
]


# ═════════════════ Drawing helpers ═══════════════════════════════════════════

def _panel(surf: pygame.Surface, rect: pygame.Rect, title: str, f_sec):
    """Draw a panel card: background, border, title bar, grid lines."""
    pygame.draw.rect(surf, PANEL_BG, rect, border_radius=4)
    pygame.draw.rect(surf, BORDER, rect, 1, border_radius=4)
    # header strip
    hdr = pygame.Rect(rect.x + 1, rect.y + 1, rect.w - 2, 18)
    pygame.draw.rect(surf, HDR_BG, hdr, border_radius=3)
    lbl = f_sec.render(title, True, ACCENT)
    surf.blit(lbl, (rect.x + 6, rect.y + 3))
    # inner plot area
    plot = pygame.Rect(rect.x + 38, rect.y + 22, rect.w - 42, rect.h - 26)
    # grid
    for i in range(1, 5):
        y = plot.y + plot.h * i // 5
        pygame.draw.line(surf, GRID_C, (plot.x, y), (plot.right, y), 1)
    for j in range(1, 7):
        x = plot.x + plot.w * j // 7
        pygame.draw.line(surf, GRID_C, (x, plot.y), (x, plot.bottom), 1)
    return plot


def _line(surf, plot, data, color, y_min, y_max, lw=1, filled=False, alpha=35):
    if len(data) < 2:
        return
    n  = len(data)
    rng = y_max - y_min or 1e-9
    pts = []
    for i, v in enumerate(data):
        x = plot.x + int(plot.w * i / max(n - 1, 1))
        y = plot.bottom - int(plot.h * max(0.0, min(1.0, (v - y_min) / rng)))
        pts.append((x, y))
    if filled and len(pts) >= 2:
        poly = pts + [(pts[-1][0], plot.bottom), (pts[0][0], plot.bottom)]
        ov = pygame.Surface((plot.w, plot.h), pygame.SRCALPHA)
        lp = [(p[0] - plot.x, p[1] - plot.y) for p in poly]
        pygame.draw.polygon(ov, (*color, alpha), lp)
        surf.blit(ov, (plot.x, plot.y))
    pygame.draw.lines(surf, color, False, pts, lw)


def _y_labels(surf, plot, y_min, y_max, f_tiny, n=4, fmt="{:.0f}", unit=""):
    for i in range(n + 1):
        v = y_min + (y_max - y_min) * i / n
        y = plot.bottom - plot.h * i // n
        t = f_tiny.render(fmt.format(v) + unit, True, TXT2)
        surf.blit(t, (plot.x - t.get_width() - 2, y - 5))


def _v_bars(surf, plot, values, colors, labels, y_max, f_tiny):
    """Vertical bar chart."""
    n = len(values)
    if n == 0:
        return
    bar_w = max(1, (plot.w - n - 1) // n)
    for i, (v, col) in enumerate(zip(values, colors)):
        h = int(plot.h * min(1.0, v / max(y_max, 1e-9)))
        x = plot.x + i * (bar_w + 1)
        pygame.draw.rect(surf, col, (x, plot.bottom - h, bar_w, h))
        if labels and i < len(labels):
            lbl = f_tiny.render(labels[i], True, TXT2)
            surf.blit(lbl, (x + bar_w // 2 - lbl.get_width() // 2, plot.bottom + 2))


def _h_bars(surf, rect, values, colors, labels, x_max, f_tiny):
    """Horizontal bar chart (one row per satellite)."""
    n = len(values)
    if n == 0:
        return
    row_h  = max(6, (rect.h - 4) // n)
    for i, (v, col, lbl_txt) in enumerate(zip(values, colors, labels)):
        bar_w = int((rect.w - 60) * min(1.0, v / max(x_max, 1e-9)))
        y     = rect.y + i * row_h + 2
        # label
        lbl = f_tiny.render(lbl_txt, True, TXT2)
        surf.blit(lbl, (rect.x, y + row_h // 2 - lbl.get_height() // 2))
        # bar
        bx = rect.x + 54
        if bar_w > 0:
            pygame.draw.rect(surf, col, (bx, y + 1, bar_w, row_h - 2))
        pygame.draw.rect(surf, GRID_C, (bx, y + 1, rect.right - bx - 2, row_h - 2), 1)
        # value label
        val_s = f_tiny.render(f"{v:.2f}", True, TXT)
        surf.blit(val_s, (bx + bar_w + 3, y + row_h // 2 - val_s.get_height() // 2))


def _pie(surf, cx, cy, r, segments, f_tiny):
    """Simple pie chart. segments = list of (value, color, label)."""
    total = sum(v for v, _, _ in segments)
    if total <= 0:
        pygame.draw.circle(surf, GRID_C, (cx, cy), r, 2)
        return
    angle = -90.0
    for v, col, lbl in segments:
        sweep = 360.0 * v / total
        if sweep < 0.5:
            continue
        pts = [(cx, cy)]
        for deg in range(int(angle), int(angle + sweep) + 1, 2):
            rad = math.radians(deg)
            pts.append((cx + r * math.cos(rad), cy + r * math.sin(rad)))
        if len(pts) >= 3:
            pygame.draw.polygon(surf, col, pts)
        angle += sweep
    pygame.draw.circle(surf, PANEL_BG, (cx, cy), r // 3)
    pygame.draw.circle(surf, BORDER, (cx, cy), r, 1)


def _row_text(surf, x, y, label, value, f_lbl, f_val, v_col=None):
    ls = f_lbl.render(label, True, TXT2)
    vs = f_val.render(value, True, v_col or TXT)
    surf.blit(ls, (x, y))
    surf.blit(vs, (x + ls.get_width() + 6, y))
    return y + ls.get_height() + 3


def _section_hdr(surf, x, y, text, f_bold, w=680):
    pygame.draw.line(surf, BORDER, (x, y + 8), (x + w, y + 8), 1)
    lbl = f_bold.render(text, True, ACCENT)
    bg  = pygame.Surface((lbl.get_width() + 8, lbl.get_height()), pygame.SRCALPHA)
    bg.fill((*PANEL_BG, 255))
    surf.blit(bg,  (x + 6, y))
    surf.blit(lbl, (x + 10, y))
    return y + 18


# ═════════════════ Network analysis helpers ════════════════════════════════════

def _graph_stats(network):
    """Returns dict of CCN graph metrics computed from the live ISL graph."""
    import networkx as nx
    G = network.graph
    sat_nodes = [n for n in G.nodes if isinstance(n, int)]
    sub = G.subgraph(sat_nodes)
    stats = {
        "n_nodes":   len(sat_nodes),
        "n_edges":   sub.number_of_edges(),
        "density":   nx.density(sub) if len(sat_nodes) > 1 else 0.0,
        "diameter":  0,
        "avg_path":  0.0,
        "avg_degree": 0.0,
        "connected": nx.is_connected(sub) if len(sat_nodes) > 0 else False,
        "components": nx.number_connected_components(sub) if len(sat_nodes) > 0 else 0,
    }
    if len(sat_nodes) > 0:
        degrees = [d for _, d in sub.degree()]
        stats["avg_degree"] = sum(degrees) / len(degrees)
    if stats["connected"] and len(sat_nodes) > 1:
        try:
            stats["diameter"] = nx.diameter(sub)
            stats["avg_path"] = nx.average_shortest_path_length(sub)
        except Exception:
            pass
    return stats


# ═════════════════ AnalyticsPanel ═════════════════════════════════════════════

class AnalyticsPanel:
    def __init__(self):
        self._fa = self._fb = self._fc = self._fd = self._fe = None
        self._orb = OrbitalMechanics()

    def init_fonts(self):
        self._fa = pygame.font.SysFont("arial",    20, bold=True)   # title
        self._fb = pygame.font.SysFont("arial",    11, bold=True)   # section header
        self._fc = pygame.font.SysFont("consolas", 10)              # body mono
        self._fd = pygame.font.SysFont("arial",    9)               # tiny labels
        self._fe = pygame.font.SysFont("consolas", 9)               # tiny mono
        self._ff = pygame.font.SysFont("consolas", 11, bold=True)   # value emphasis

    # ── master draw ──────────────────────────────────────────────────────────
    def draw(self, surface: pygame.Surface, satellites: list, debris: list,
             network, metrics, sim_time: float, anim_t: float) -> None:
        surface.fill(BG)
        self._title_bar(surface, sim_time)
        self._chart_latency(surface, metrics)
        self._chart_delivery(surface, metrics)
        self._chart_isls(surface, metrics)
        self._chart_sat_util(surface, satellites, metrics)
        self._chart_state_pie(surface, satellites)
        self._chart_proximity(surface, metrics)
        self._panel_formulas(surface, satellites, network, metrics, sim_time, debris)
        self._panel_sat_table(surface, satellites, network)

    # ── title bar ─────────────────────────────────────────────────────────────
    def _title_bar(self, surface, sim_time):
        pygame.draw.rect(surface, HDR_BG, (0, 0, W, TITLE_H))
        pygame.draw.line(surface, BORDER, (0, TITLE_H), (W, TITLE_H), 1)
        t1 = self._fa.render("ORB — CCN ANALYTICS & CONTROL PANEL", True, ACCENT)
        t2 = self._fd.render(
            f"CE313  ·  Simulation time {sim_time:.1f} s  ·  "
            f"Press  P  to return to simulation", True, TXT2)
        surface.blit(t1, (16, 8))
        surface.blit(t2, (16, 32))
        # decorative right side
        badge = self._fb.render("LEO · CCN · PHASE 3", True, PINK)
        surface.blit(badge, (W - badge.get_width() - 16, 16))

    # ── ROW 1: Latency ────────────────────────────────────────────────────────
    def _chart_latency(self, surface, metrics):
        plot = _panel(surface, _R1[0], "AVG ISL LATENCY  (ms)", self._fb)
        data = list(metrics.chart_latency_ms)
        if not data:
            self._no_data(surface, plot)
            return
        y_max = max(max(data) * 1.15, 1.0)
        _line(surface, plot, data, ACCENT, 0, y_max, lw=2, filled=True, alpha=30)
        _y_labels(surface, plot, 0, y_max, self._fe, n=4, fmt="{:.1f}", unit=" ms")
        # current value
        cur = self._ff.render(f"{data[-1]:.2f} ms", True, GOOD if data[-1] < 20 else WARN_COL)
        surface.blit(cur, (plot.right - cur.get_width() - 2, plot.y + 2))
        # min / max annotation
        mn = min(data); mx_v = max(data)
        surface.blit(self._fe.render(f"min {mn:.2f}", True, GOOD),
                     (plot.x + 2, plot.bottom - 12))
        surface.blit(self._fe.render(f"max {mx_v:.2f}", True, DANGER_COL),
                     (plot.x + 2, plot.y + 2))

    # ── ROW 1: Delivery rate ──────────────────────────────────────────────────
    def _chart_delivery(self, surface, metrics):
        plot = _panel(surface, _R1[1], "PACKET DELIVERY RATE  (%)", self._fb)
        hist = metrics.history
        if not hist:
            self._no_data(surface, plot)
            return
        rates = [f.delivery_rate_pct for f in hist]
        pkts  = [f.packets_delivered  for f in hist]
        # secondary: scale delivered count to 0-100 for overlay
        pk_max = max(max(pkts), 1)
        pk_norm = [v * 100 / pk_max for v in pkts]
        _line(surface, plot, pk_norm,  (60, 40, 90), 0, 100, lw=1, filled=True, alpha=20)
        _line(surface, plot, rates,    GOOD,          0, 100, lw=2)
        _y_labels(surface, plot, 0, 100, self._fe, n=4, fmt="{:.0f}", unit="%")
        cur = self._ff.render(f"{rates[-1]:.1f}%", True,
                              GOOD if rates[-1] > 90 else (WARN_COL if rates[-1] > 50 else DANGER_COL))
        surface.blit(cur, (plot.right - cur.get_width() - 2, plot.y + 2))
        surface.blit(self._fe.render("── delivery rate   ░ pkts delivered (scaled)", True, TXT2),
                     (plot.x + 2, plot.bottom - 12))

    # ── ROW 1: ISL count ──────────────────────────────────────────────────────
    def _chart_isls(self, surface, metrics):
        plot = _panel(surface, _R1[2], "ACTIVE ISLs + TOTAL LINKS  (count)", self._fb)
        hist = metrics.history
        if not hist:
            self._no_data(surface, plot)
            return
        active = [f.active_links for f in hist]
        total  = [f.total_links  for f in hist]
        y_max  = max(max(total, default=1), 1) * 1.2
        _line(surface, plot, total,  GRID_C,  0, y_max, lw=1, filled=True, alpha=40)
        _line(surface, plot, active, L_PINK,  0, y_max, lw=2, filled=True, alpha=25)
        _y_labels(surface, plot, 0, y_max, self._fe, n=4, fmt="{:.0f}")
        surface.blit(self._fe.render("── active    ░ total graph edges", True, TXT2),
                     (plot.x + 2, plot.bottom - 12))
        cur = self._ff.render(f"{active[-1]} active", True, L_PINK)
        surface.blit(cur, (plot.right - cur.get_width() - 2, plot.y + 2))

    # ── ROW 2: Per-satellite ISL utilisation ──────────────────────────────────
    def _chart_sat_util(self, surface, satellites, metrics):
        rect = _R2[0]
        pygame.draw.rect(surface, PANEL_BG, rect, border_radius=4)
        pygame.draw.rect(surface, BORDER, rect, 1, border_radius=4)
        pygame.draw.rect(surface, HDR_BG, pygame.Rect(rect.x+1, rect.y+1, rect.w-2, 18), border_radius=3)
        surface.blit(self._fb.render("PER-SATELLITE ISL UTILISATION", True, ACCENT),
                     (rect.x + 6, rect.y + 3))

        hist = metrics.history
        util_vec = hist[-1].isl_util if hist else tuple([0.0] * NUM_SATELLITES)
        bar_rect = pygame.Rect(rect.x + 6, rect.y + 22, rect.w - 12, rect.h - 26)

        values = [util_vec[s.sat_id] if s.sat_id < len(util_vec) else 0.0
                  for s in sorted(satellites, key=lambda x: x.sat_id)]
        colors = [SAT_COLORS[s.state] for s in sorted(satellites, key=lambda x: x.sat_id)]
        labels = [f"S{s.sat_id}" for s in sorted(satellites, key=lambda x: x.sat_id)]
        _h_bars(surface, bar_rect, values, colors, labels, 1.0, self._fd)

    # ── ROW 2: State distribution pie ─────────────────────────────────────────
    def _chart_state_pie(self, surface, satellites):
        rect = _R2[1]
        pygame.draw.rect(surface, PANEL_BG, rect, border_radius=4)
        pygame.draw.rect(surface, BORDER,   rect, 1, border_radius=4)
        pygame.draw.rect(surface, HDR_BG, pygame.Rect(rect.x+1, rect.y+1, rect.w-2, 18), border_radius=3)
        surface.blit(self._fb.render("STATES", True, ACCENT), (rect.x + 6, rect.y + 3))

        counts = {s: sum(1 for sat in satellites if sat.state == s) for s in State}
        segs = [(v, SAT_COLORS[s], s.name[:4]) for s, v in counts.items() if v > 0]
        cx = rect.x + rect.w // 2
        cy = rect.y + 22 + 65
        _pie(surface, cx, cy, 52, segs, self._fd)

        # Legend
        ly = cy + 58
        for s, col in SAT_COLORS.items():
            n = counts[s]
            pygame.draw.rect(surface, col, (rect.x + 8, ly, 10, 10))
            surface.blit(self._fd.render(f"{s.name[:4]}  {n}", True, TXT2),
                         (rect.x + 22, ly))
            ly += 14

    # ── ROW 2: Proximity / near-miss timeline ─────────────────────────────────
    def _chart_proximity(self, surface, metrics):
        plot = _panel(surface, _R2[2], "MIN INTER-SATELLITE SEPARATION  (km)", self._fb)
        hist = metrics.history
        if not hist:
            self._no_data(surface, plot)
            return
        sep_data = [f.min_separation_km for f in hist if f.min_separation_km < 1e5]
        if not sep_data:
            self._no_data(surface, plot)
            return
        y_max = max(max(sep_data) * 1.2, WARNING_THRESHOLD_KM * 2)
        _line(surface, plot, sep_data, ACCENT, 0, y_max, lw=2, filled=True, alpha=25)

        # Threshold lines
        def _threshold_line(thresh, col, label):
            if thresh > y_max:
                return
            y = plot.bottom - int(plot.h * thresh / y_max)
            pygame.draw.line(surface, col, (plot.x, y), (plot.right, y), 1)
            surface.blit(self._fe.render(label, True, col), (plot.x + 2, y - 10))

        _threshold_line(WARNING_THRESHOLD_KM,   WARN_COL,   f"WARN {WARNING_THRESHOLD_KM:.0f}km")
        _threshold_line(COLLISION_THRESHOLD_KM, DANGER_COL, f"COLL {COLLISION_THRESHOLD_KM:.0f}km")
        _y_labels(surface, plot, 0, y_max, self._fe, n=4, fmt="{:.0f}", unit=" km")

        cur_sep = sep_data[-1]
        col = DANGER_COL if cur_sep < COLLISION_THRESHOLD_KM else (
              WARN_COL   if cur_sep < WARNING_THRESHOLD_KM   else GOOD)
        cur = self._ff.render(f"now {cur_sep:.1f} km", True, col)
        surface.blit(cur, (plot.right - cur.get_width() - 2, plot.y + 2))

        # near-miss events as vertical ticks
        nm_data = [f.near_misses for f in hist]
        prev_nm = 0
        n = len(nm_data)
        for i, nm in enumerate(nm_data):
            if nm > prev_nm:
                x = plot.x + int(plot.w * i / max(n - 1, 1))
                pygame.draw.line(surface, PINK, (x, plot.y), (x, plot.bottom), 1)
            prev_nm = nm

    # ── ROW 3 left: CCN formulas & live calculations ───────────────────────────
    def _panel_formulas(self, surface, satellites, network, metrics,
                        sim_time, debris):
        rect = _R3[0]
        pygame.draw.rect(surface, PANEL_BG, rect, border_radius=4)
        pygame.draw.rect(surface, BORDER,   rect, 1, border_radius=4)
        pygame.draw.rect(surface, HDR_BG, pygame.Rect(rect.x+1, rect.y+1, rect.w-2, 18), border_radius=3)
        surface.blit(self._fb.render("CCN FORMULAS & COMPUTED VALUES", True, ACCENT),
                     (rect.x + 6, rect.y + 3))

        x0 = rect.x + 10
        y  = rect.y + 24
        W2 = rect.w // 2 - 14    # half-panel column width

        # ── ORBITAL MECHANICS ─────────────────────────────────────────────────
        y = _section_hdr(surface, x0, y, " ORBITAL MECHANICS ", self._fb, w=rect.w - 20)
        rows_orb = [
            ("Radius",          f"R  = {ORBITAL_RADIUS_KM:.1f} km"),
            ("Period",          f"T  = {_T_PERIOD:.1f} s  ({_T_PERIOD/60:.2f} min)"),
            ("Angular vel.",    f"ω  = {_OMEGA*1000:.4f} mrad/s"),
            ("Orbital vel.",    f"v  = {ORBITAL_VELOCITY_KM_S:.2f} km/s"),
            ("Inclination",     f"i  = 53.0°  (Walker 53°)"),
            ("RAAN spacing",    f"ΔΩ = 60.0° / plane  ({NUM_ORBITAL_PLANES} planes)"),
            ("J2 RAAN drift",   f"dΩ/dt = {_RAAN_DEG_S:.5f} °/s  ({_RAAN_DEG_D:.2f} °/day)"),
            ("Alt. (LEO)",      f"h  = {ORBITAL_RADIUS_KM - EARTH_RADIUS_KM:.0f} km"),
        ]
        for lbl, val in rows_orb:
            ls = self._fd.render(lbl, True, TXT2)
            vs = self._fc.render(val, True, TXT)
            surface.blit(ls, (x0,           y))
            surface.blit(vs, (x0 + W2 - 10, y))
            y += 14
        y += 4

        # ── ISL LINK BUDGET ────────────────────────────────────────────────────
        y = _section_hdr(surface, x0, y, " ISL LINK BUDGET ", self._fb, w=rect.w - 20)
        rows_link = [
            ("Max ISL range",     f"d_max = {ISL_MAX_RANGE_KM:.0f} km"),
            ("Speed of light",    f"c = {_C_KM_S:.0f} km/s"),
            ("Max prop. delay",   f"τ_max = d/c = {_MAX_DELAY_MS:.3f} ms"),
            ("ISL bandwidth",     f"B = {_B_MHZ:.0f} Mbps"),
            ("Shannon cap.",      f"C = B·log₂(1+SNR) = {_SHANNON_MBPS:.1f} Mbps"),
            (f"  SNR assumed",    f"{_SNR_DB:.0f} dB  (linear {_SNR_LIN:.0f}×)"),
            ("FSPL @ d_max",      f"FSPL = {_FSPL_DB:.1f} dB  ({_F_GHZ} GHz Ka)"),
            ("Doppler shift",     f"Δf = v·f/c = {_DOPPLER_KHZ:.1f} kHz  (max)"),
        ]
        for lbl, val in rows_link:
            ls = self._fd.render(lbl, True, TXT2)
            vs = self._fc.render(val, True, TXT)
            surface.blit(ls, (x0,           y))
            surface.blit(vs, (x0 + W2 - 10, y))
            y += 14
        y += 4

        # ── LIVE CCN PERFORMANCE ───────────────────────────────────────────────
        y = _section_hdr(surface, x0, y, " LIVE CCN PERFORMANCE ", self._fb, w=rect.w - 20)
        stats = network.get_network_stats()
        sent  = stats["total_packets_sent"]
        deliv = stats["delivered"]
        rate  = deliv / sent * 100 if sent else 0.0
        loss  = 100 - rate
        gstats = _graph_stats(network)

        rows_perf = [
            ("Pkts sent",      f"{sent}",                         None),
            ("Pkts delivered", f"{deliv}",                        None),
            ("Delivery rate",  f"η = {rate:.1f}%",
             GOOD if rate > 90 else (WARN_COL if rate > 50 else DANGER_COL)),
            ("Packet loss",    f"PL = {loss:.1f}%",
             GOOD if loss < 5 else (WARN_COL if loss < 20 else DANGER_COL)),
            ("Avg latency",    f"τ̄ = {stats['avg_latency_ms']:.3f} ms",     None),
            ("Max latency",    f"τ_max = {stats['max_latency_ms']:.3f} ms", None),
            ("In-flight pkts", f"{stats['in_flight']}",                     None),
            ("Graph nodes",    f"{gstats['n_nodes']} sats + 2 GS",          None),
            ("ISL edges",      f"{gstats['n_edges']}",                       None),
            ("Graph density",  f"ρ = {gstats['density']:.3f}",              None),
            ("Avg degree",     f"k̄ = {gstats['avg_degree']:.2f}",           None),
            ("Connected?",     "YES" if gstats["connected"] else f"NO  ({gstats['components']} comps)",
             GOOD if gstats["connected"] else DANGER_COL),
            ("Diameter",       f"{gstats['diameter']} hops" if gstats["connected"] else "—", None),
            ("Avg path",       f"{gstats['avg_path']:.2f} hops" if gstats["connected"] else "—", None),
        ]
        for lbl, val, col in rows_perf:
            ls = self._fd.render(lbl, True, TXT2)
            vs = self._fc.render(val, True, col or TXT)
            surface.blit(ls, (x0,           y))
            surface.blit(vs, (x0 + W2 - 10, y))
            y += 13
            if y > rect.bottom - 14:
                break
        y += 4

        # ── COLLISION SAFETY ──────────────────────────────────────────────────
        if y < rect.bottom - 60:
            y = _section_hdr(surface, x0, y, " COLLISION SAFETY ", self._fb, w=rect.w - 20)
            nm  = metrics.total_near_misses if metrics else 0
            man = metrics.total_maneuvers   if metrics else 0
            mn_sep = metrics.min_separation_km if metrics and metrics.min_separation_km < 1e5 else None
            rows_coll = [
                ("Collision thresh.", f"d_c = {COLLISION_THRESHOLD_KM:.1f} km"),
                ("Warning thresh.",   f"d_w = {WARNING_THRESHOLD_KM:.1f} km"),
                ("Avoidance Δv cap",  f"Δv_max = 0.05 km/s"),
                ("Maneuver duration", f"Δt_burn = 30 sim-s"),
                ("Near-misses",       str(nm)),
                ("Maneuvers exec.",   str(man)),
                ("Min separation",    f"{mn_sep:.1f} km" if mn_sep is not None else "—"),
                ("Debris tracked",    f"{len(debris)}"),
            ]
            for lbl, val in rows_coll:
                ls = self._fd.render(lbl, True, TXT2)
                vs = self._fc.render(val, True, TXT)
                surface.blit(ls, (x0,           y))
                surface.blit(vs, (x0 + W2 - 10, y))
                y += 13
                if y > rect.bottom - 4:
                    break

    # ── ROW 3 right: Satellite positions table ─────────────────────────────────
    def _panel_sat_table(self, surface, satellites, network):
        rect = _R3[1]
        pygame.draw.rect(surface, PANEL_BG, rect, border_radius=4)
        pygame.draw.rect(surface, BORDER,   rect, 1, border_radius=4)
        pygame.draw.rect(surface, HDR_BG, pygame.Rect(rect.x+1, rect.y+1, rect.w-2, 18), border_radius=3)
        surface.blit(self._fb.render("SATELLITE POSITIONS & LINK STATE", True, ACCENT),
                     (rect.x + 6, rect.y + 3))

        # Get per-satellite ISL degree and load
        isl_degree = {n: 0 for n in range(NUM_SATELLITES)}
        isl_load   = {n: 0.0 for n in range(NUM_SATELLITES)}
        for u, v, d in network.graph.edges(data=True):
            if d.get("kind") == "isl":
                for node in (u, v):
                    if isinstance(node, int) and node < NUM_SATELLITES:
                        isl_degree[node] = isl_degree.get(node, 0) + 1
                        isl_load[node]   = isl_load.get(node, 0.0) + d.get("current_load", 0.0)
        for node in isl_degree:
            if isl_degree[node] > 0:
                isl_load[node] /= isl_degree[node]

        # Column layout
        col_x  = [rect.x + 4, rect.x + 32, rect.x + 60,
                  rect.x + 108, rect.x + 220, rect.x + 332,
                  rect.x + 440, rect.x + 538, rect.x + 596, rect.x + 640]
        headers = ["ID", "PLN", "STATE", "X km", "Y km", "Z km",
                   "R km", "ISLs", "LOAD", "VEL km/s"]
        y = rect.y + 22

        # Header row
        for i, h in enumerate(headers):
            if i < len(col_x):
                surface.blit(self._fd.render(h, True, ACCENT), (col_x[i], y))
        y += 13
        pygame.draw.line(surface, BORDER, (rect.x + 4, y), (rect.right - 4, y), 1)
        y += 2

        orb = self._orb
        for row_i, sat in enumerate(sorted(satellites, key=lambda s: s.sat_id)):
            col = SAT_COLORS[sat.state]
            x, yp, zp = sat.position
            r   = math.sqrt(x*x + yp*yp + zp*zp)
            vx, vy, vz = sat.velocity
            vel = math.sqrt(vx*vx + vy*vy + vz*vz)
            deg = isl_degree.get(sat.sat_id, 0)
            ld  = isl_load.get(sat.sat_id, 0.0)

            bg_col = (16, 0, 30) if row_i % 2 == 0 else (11, 0, 22)
            pygame.draw.rect(surface, bg_col,
                             (rect.x + 2, y, rect.w - 4, 13))

            vals = [
                str(sat.sat_id),
                str(sat.plane),
                sat.state.name[:4],
                f"{x:,.0f}",
                f"{yp:,.0f}",
                f"{zp:,.0f}",
                f"{r:,.0f}",
                str(deg),
                f"{ld:.2f}",
                f"{vel:.3f}",
            ]
            for i, v in enumerate(vals):
                if i < len(col_x):
                    c = col if i == 2 else TXT
                    surface.blit(self._fe.render(v, True, c), (col_x[i], y))
            y += 13
            if y > rect.bottom - 14:
                break

        y += 4
        if y < rect.bottom - 60:
            # Network adjacency summary
            pygame.draw.line(surface, BORDER, (rect.x + 4, y), (rect.right - 4, y), 1)
            y += 4
            surface.blit(self._fb.render("NETWORK ADJACENCY (active ISL edges)", True, ACCENT),
                         (rect.x + 6, y))
            y += 14
            for u, v, d in network.graph.edges(data=True):
                if d.get("kind") != "isl":
                    continue
                if y > rect.bottom - 12:
                    break
                dist = d.get("distance_km", 0.0)
                delay = d.get("propagation_delay_ms", 0.0)
                load  = d.get("current_load", 0.0)
                lc = GOOD if load < 0.3 else (WARN_COL if load < 0.7 else DANGER_COL)
                txt = (f"  S{u:>2} ─ S{v:>2}   {dist:>7.1f} km   "
                       f"τ={delay:.3f} ms   load={load:.3f}")
                surface.blit(self._fe.render(txt, True, lc), (rect.x + 6, y))
                y += 12

            if y < rect.bottom - 16:
                # GS uplinks
                pygame.draw.line(surface, BORDER, (rect.x + 4, y + 2), (rect.right - 4, y + 2), 1)
                y += 6
                surface.blit(self._fd.render("GROUND STATION UPLINKS", True, ACCENT),
                             (rect.x + 6, y))
                y += 13
                for u, v, d in network.graph.edges(data=True):
                    if d.get("kind") != "uplink":
                        continue
                    if y > rect.bottom - 10:
                        break
                    gs = u if isinstance(u, str) else v
                    sat_n = v if isinstance(u, str) else u
                    dist = d.get("distance_km", 0.0)
                    delay = d.get("propagation_delay_ms", 0.0)
                    txt = f"  {gs} ─ S{sat_n}   {dist:>7.1f} km   τ={delay:.3f} ms"
                    surface.blit(self._fe.render(txt, True, L_PINK), (rect.x + 6, y))
                    y += 12

    # ── helper: "no data yet" placeholder ────────────────────────────────────
    def _no_data(self, surface, plot):
        lbl = self._fd.render("— waiting for data —", True, GRID_C)
        surface.blit(lbl, (plot.centerx - lbl.get_width() // 2,
                           plot.centery - lbl.get_height() // 2))
