import math
import sys
import os
import collections
import subprocess
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

from physics import OrbitalMechanics
from config import (
    NUM_SATELLITES, NUM_ORBITAL_PLANES, SIMULATION_SPEED,
    SCREEN_WIDTH, SCREEN_HEIGHT, FPS, COLORS,
)
from agents import (
    create_constellation, create_debris, State,
    spawn_chaos_debris,
)
from network import ConstellationNetwork
from metrics import MetricsCollector
from ui.renderer import OrbitalRenderer
from ui.dashboard import MetricsDashboard

# Internal physics step (sim seconds). Smaller = smoother motion at high time warp.
FIXED_SIM_DT = 0.05

# ── Event record ────────────────────────────────────────────────────────────
class _Event:
    __slots__ = ("sim_time", "category", "message")
    def __init__(self, t, cat, msg):
        self.sim_time = t
        self.category = cat
        self.message  = msg


# ── Helpers ──────────────────────────────────────────────────────────────────
def _plane_and_index(sat_id):
    spp = NUM_SATELLITES // NUM_ORBITAL_PLANES
    return sat_id // spp, sat_id % spp


def _all_positions(satellites, debris_list):
    pos = {s.sat_id: s.position for s in satellites}
    pos.update({d.debris_id: d.position for d in debris_list})
    return pos


def _lerp3(a: tuple, b: tuple, t: float) -> tuple:
    t = max(0.0, min(1.0, t))
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _interpolated_positions(start_pos: dict, end_pos: dict, alpha: float) -> dict:
    keys = set(start_pos) | set(end_pos)
    out = {}
    for k in keys:
        if k in start_pos and k in end_pos:
            out[k] = _lerp3(start_pos[k], end_pos[k], alpha)
        elif k in end_pos:
            out[k] = end_pos[k]
        else:
            out[k] = start_pos[k]
    return out


def _next_debris_id(debris_list):
    return max((d.debris_id for d in debris_list), default=99) + 1


def _run_analysis_and_open():
    base = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(base, "results.csv")
    png_path = os.path.join(base, "results_analysis.png")
    try:
        import analysis as orbit_analysis
        orbit_analysis.generate_plots(csv_path, png_path)
    except Exception as ex:
        print(f"  Analysis failed: {ex}")
        return
    if os.path.isfile(png_path):
        if sys.platform == "win32":
            os.startfile(png_path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", png_path], check=False)
        else:
            subprocess.run(["xdg-open", png_path], check=False)


# ════════════════════════════════════════════════════════════════════════════
def run():
    pygame.init()
    pygame.display.set_caption("ORB — LEO Satellite CCN")
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    clock  = pygame.time.Clock()

    orb        = OrbitalMechanics()
    satellites = create_constellation(orb)
    debris     = create_debris(orb, count=5)
    network    = ConstellationNetwork()
    metrics    = MetricsCollector()
    renderer   = OrbitalRenderer()
    dashboard  = MetricsDashboard()

    renderer.init_fonts()
    dashboard.init_fonts()

    sim_time     = 0.0
    sim_speed    = SIMULATION_SPEED
    paused       = False
    event_log    = collections.deque(maxlen=50)
    chaos_mode   = False
    chaos_inj_accum = 0.0
    next_debris_id = _next_debris_id(debris)
    selected_sat = None

    ap = _all_positions(satellites, debris)
    network.update_topology({k: v for k, v in ap.items() if k < 100})

    prev_states  = {s.sat_id: s.state for s in satellites}
    metrics_tick = 0.0
    sim_accum    = 0.0
    curr_snap    = _all_positions(satellites, debris)
    prev_snap    = dict(curr_snap)

    running = True
    while running:
        dt_real = clock.tick(FPS) / 1000.0
        dt_real = min(dt_real, 0.05)
        anim_t  = pygame.time.get_ticks() / 1000.0

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif ev.key == pygame.K_SPACE:
                    paused = not paused
                    event_log.appendleft(_Event(
                        sim_time, "INFO",
                        "Simulation PAUSED" if paused else "Simulation RESUMED"
                    ))
                elif ev.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                    sim_speed = min(sim_speed + 10, 500)
                elif ev.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    sim_speed = max(sim_speed - 10, 1)
                elif ev.key == pygame.K_c:
                    chaos_mode = not chaos_mode
                    event_log.appendleft(_Event(
                        sim_time, "INFO",
                        f"Chaos mode {'ON' if chaos_mode else 'OFF'}"
                    ))
                elif ev.key == pygame.K_g:
                    out_csv = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "results.csv"
                    )
                    metrics.export_csv(out_csv)
                    _run_analysis_and_open()
                elif ev.key == pygame.K_r:
                    satellites  = create_constellation(orb)
                    debris      = create_debris(orb, count=5)
                    network     = ConstellationNetwork()
                    metrics     = MetricsCollector()
                    sim_time    = 0.0
                    sim_accum   = 0.0
                    chaos_inj_accum = 0.0
                    next_debris_id = _next_debris_id(debris)
                    selected_sat = None
                    event_log.clear()
                    event_log.appendleft(_Event(0.0, "INFO", "Simulation RESET"))
                    prev_states = {s.sat_id: s.state for s in satellites}
                    ap = _all_positions(satellites, debris)
                    curr_snap = dict(ap)
                    prev_snap = dict(curr_snap)
                    network.update_topology({k: v for k, v in ap.items() if k < 100})
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                mx, my = ev.pos
                if mx < 900:
                    disp = _all_positions(satellites, debris)
                    hit = renderer.pick_satellite_at(
                        satellites, mx, my, display_positions=disp
                    )
                    selected_sat = hit

        if paused:
            disp = _all_positions(satellites, debris)
            renderer.draw(
                screen, satellites, debris, network, anim_t,
                display_positions=disp,
                screen_wh=(SCREEN_WIDTH, SCREEN_HEIGHT),
                selected_sat=selected_sat,
            )
            dashboard.draw(
                screen, satellites, debris, network, metrics,
                event_log, sim_time, sim_speed,
                display_positions=disp, chaos_mode=chaos_mode, anim_t=anim_t,
            )
            font = pygame.font.SysFont("monospace", 28, bold=True)
            txt  = font.render("  PAUSED  ", True, COLORS["TEXT_PRIMARY"],
                               COLORS["PANEL_BG"])
            screen.blit(txt, (450 - txt.get_width() // 2, 430))
            pygame.display.flip()
            continue

        dt_sim = dt_real * sim_speed
        sim_accum += dt_sim
        substeps_this_frame = 0

        while sim_accum >= FIXED_SIM_DT:
            sim_accum -= FIXED_SIM_DT
            sub = FIXED_SIM_DT
            substeps_this_frame += 1
            prev_snap = dict(curr_snap)

            if chaos_mode:
                chaos_inj_accum += sub
                if chaos_inj_accum >= 30.0:
                    chaos_inj_accum = 0.0
                    rng = random.Random(int(sim_time * 1000) & 0xFFFFFFFF)
                    for _ in range(3):
                        target = rng.choice(satellites)
                        debris.append(
                            spawn_chaos_debris(next_debris_id, target.position, rng)
                        )
                        next_debris_id += 1
                    event_log.appendleft(_Event(
                        sim_time, "INFO",
                        "Chaos: injected 3 intercept debris objects"
                    ))

            ap = _all_positions(satellites, debris)
            sat_pos = {k: v for k, v in ap.items() if k < 100}
            network.update_topology(sat_pos)

            for sat in satellites:
                sat.step(sim_time, sub, ap, network)
            for d in debris:
                d.step(sim_time, sub, ap, network)

            network.tick(sub, satellites)

            sim_time += sub

            for sat in satellites:
                if sat.state != prev_states[sat.sat_id]:
                    new_s = sat.state
                    if new_s == State.WARNING:
                        event_log.appendleft(_Event(
                            sim_time, "ALERT",
                            f"SAT {sat.sat_id} → WARNING proximity"
                        ))
                        renderer.trigger_collision_flash(0.5)
                    elif new_s == State.MANEUVERING:
                        metrics.total_maneuvers += 1
                        event_log.appendleft(_Event(
                            sim_time, "MANEUVER",
                            f"SAT {sat.sat_id} → MANEUVERING avoidance burn"
                        ))
                    elif new_s == State.SAFE:
                        event_log.appendleft(_Event(
                            sim_time, "INFO",
                            f"SAT {sat.sat_id} → SAFE maneuver complete"
                        ))
                    elif new_s == State.NOMINAL:
                        event_log.appendleft(_Event(
                            sim_time, "INFO",
                            f"SAT {sat.sat_id} → NOMINAL threat cleared"
                        ))
                prev_states[sat.sat_id] = sat.state

            metrics_tick += sub
            while metrics_tick >= 1.0:
                metrics_tick -= 1.0
                metrics.update(sim_time, satellites, network)

            curr_snap = _all_positions(satellites, debris)

        if substeps_this_frame:
            t = 1.0 - (sim_accum / FIXED_SIM_DT) if FIXED_SIM_DT > 0 else 1.0
            disp = _interpolated_positions(prev_snap, curr_snap, t)
        else:
            disp = dict(curr_snap)
        renderer.draw(
            screen, satellites, debris, network, anim_t,
            display_positions=disp,
            screen_wh=(SCREEN_WIDTH, SCREEN_HEIGHT),
            selected_sat=selected_sat,
        )
        dashboard.draw(
            screen, satellites, debris, network, metrics,
            event_log, sim_time, sim_speed,
            display_positions=disp, chaos_mode=chaos_mode, anim_t=anim_t,
        )
        pygame.display.flip()

    metrics.export_csv(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.csv")
    )
    pygame.quit()


# ════════════════════════════════════════════════════════════════════════════
# Phase-1 + Phase-2 CLI verification (no window needed)
# ════════════════════════════════════════════════════════════════════════════
def verify_constellation():
    orb = OrbitalMechanics()
    print("=" * 72)
    print("  ORB — LEO Satellite CCN  |  Constellation geometry verification")
    print("=" * 72)
    print(f"  Orbital radius : {orb.R:.1f} km")
    print(f"  Orbital period : {orb.T:.1f} s  ({orb.T/60:.2f} min)")
    print(f"  Angular velocity: {orb.omega*1000:.6f} mrad/s")
    print()

    for t_label, t in [("t = 0 s", 0.0), ("t = 1000 s", 1000.0)]:
        print(f"  {t_label}")
        print(f"  {'SAT':>4}  {'PLANE':>5}  {'IDX':>3}  "
              f"{'X (km)':>10}  {'Y (km)':>10}  {'Z (km)':>10}  {'R (km)':>10}")
        print("  " + "-" * 64)
        for sat_id in range(NUM_SATELLITES):
            plane, idx = _plane_and_index(sat_id)
            pos = orb.compute_position(sat_id, plane, idx, t)
            r   = math.sqrt(sum(c * c for c in pos))
            print(f"  {sat_id:>4}  {plane:>5}  {idx:>3}  "
                  f"{pos[0]:>10.2f}  {pos[1]:>10.2f}  {pos[2]:>10.2f}  {r:>10.2f}")
        print()

    print("  Sanity checks:")
    errors = []
    for sat_id in range(NUM_SATELLITES):
        plane, idx = _plane_and_index(sat_id)
        for t in [0, 500, 1000, 5000]:
            pos = orb.compute_position(sat_id, plane, idx, t)
            r   = math.sqrt(sum(c * c for c in pos))
            if abs(r - orb.R) > 0.01:
                errors.append(f"  SAT {sat_id} at t={t}: r={r:.4f}")
    if errors:
        print("  FAILED:", *errors, sep="\n")
    else:
        print("  All radii correct  |  Geometry OK")
    print("=" * 72)


def run_simulation_test(ticks=100, dt=1.0):
    from agents import create_constellation, create_debris
    orb        = OrbitalMechanics()
    satellites = create_constellation(orb)
    debris     = create_debris(orb, count=5)
    net        = ConstellationNetwork()
    sim_time   = 0.0

    for _ in range(ticks):
        ap = _all_positions(satellites, debris)
        net.update_topology({k: v for k, v in ap.items() if k < 100})
        for sat in satellites:
            sat.step(sim_time, dt, ap, net)
        for d in debris:
            d.step(sim_time, dt, ap, net)
        net.tick(dt, satellites)
        sim_time += dt

    print()
    print("=" * 72)
    print(f"  Phase-2 test ({ticks} ticks, dt={dt}s)")
    print("=" * 72)
    print(f"  {'ID':>4}  {'PLANE':>5}  {'STATE':>12}  "
          f"{'NEAR-MISS':>9}  {'MSG-SENT':>8}")
    print("  " + "-" * 50)
    for sat in satellites:
        print(f"  {sat.sat_id:>4}  {sat.plane:>5}  {sat.state.name:>12}  "
              f"{sat.near_miss_count:>9}  {sat.messages_sent:>8}")

    stats = net.get_network_stats()
    print()
    print("  Network stats:")
    for k, v in stats.items():
        print(f"    {k:<22}: {v}")
    print("=" * 72)


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify_constellation()
        run_simulation_test()
    else:
        run()
