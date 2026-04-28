import math
import random
from enum import Enum, auto

from config import (
    COLLISION_THRESHOLD_KM, WARNING_THRESHOLD_KM,
    NUM_SATELLITES, NUM_ORBITAL_PLANES, ORBITAL_RADIUS_KM,
    ORBITAL_VELOCITY_KM_S,
)
from physics import OrbitalMechanics
from packets import CollisionAlertPacket, TelemetryPacket

MANEUVER_DURATION = 30.0        # simulation seconds
TELEMETRY_INTERVAL = 10.0       # sim-seconds between telemetry broadcasts
_MAX_DV = 0.05                  # km/s delta-v cap

# IDs for debris start above the satellite range
_DEBRIS_ID_OFFSET = 100


class State(Enum):
    NOMINAL     = auto()
    WARNING     = auto()
    MANEUVERING = auto()
    SAFE        = auto()


class SatelliteAgent:
    def __init__(self, sat_id: int, plane: int, index_in_plane: int,
                 orb: OrbitalMechanics):
        self.sat_id = sat_id
        self.plane = plane
        self.index = index_in_plane
        self._orb = orb

        self.position: tuple[float, float, float] = orb.compute_position(
            sat_id, plane, index_in_plane, 0.0)
        self.velocity: tuple[float, float, float] = orb.compute_velocity(
            sat_id, plane, 0.0)
        self.state: State = State.NOMINAL

        self.maneuver_vector: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.maneuver_timer: float = 0.0

        self.messages_sent: int = 0
        self.messages_received: int = 0
        self.near_miss_count: int = 0

        self._telemetry_clock: float = 0.0

    # ------------------------------------------------------------------
    # Sensing
    # ------------------------------------------------------------------

    def sense(self, all_positions: dict) -> list[tuple[int, float]]:
        """
        Scan all other objects. Returns list of (other_id, distance_km)
        for threats. Transitions state machine based on closest threat.
        """
        threats = []
        min_dist = math.inf
        min_id = -1

        for other_id, pos in all_positions.items():
            if other_id == self.sat_id:
                continue
            d = OrbitalMechanics.distance_3d(self.position, pos)
            if d < WARNING_THRESHOLD_KM:
                threats.append((other_id, d))
                if d < min_dist:
                    min_dist = d
                    min_id = other_id

        if min_dist < COLLISION_THRESHOLD_KM:
            if self.state != State.MANEUVERING:
                self.near_miss_count += 1
                self.maneuver_vector = self.compute_avoidance(
                    all_positions[min_id])
                self.maneuver_timer = MANEUVER_DURATION
                self.state = State.MANEUVERING
        elif min_dist < WARNING_THRESHOLD_KM:
            if self.state == State.NOMINAL:
                self.state = State.WARNING
        else:
            if self.state == State.WARNING:
                self.state = State.NOMINAL
            elif self.state == State.SAFE and self.maneuver_timer <= 0.0:
                self.state = State.NOMINAL

        return threats

    # ------------------------------------------------------------------
    # Avoidance
    # ------------------------------------------------------------------

    def compute_avoidance(self,
                          threat_position: tuple[float, float, float]
                          ) -> tuple[float, float, float]:
        """
        Delta-v perpendicular to the threat vector, magnitude ∝ 1/d².
        """
        tx, ty, tz = threat_position
        sx, sy, sz = self.position
        dx, dy, dz = sx - tx, sy - ty, sz - tz
        d = math.sqrt(dx*dx + dy*dy + dz*dz)
        if d < 1e-9:
            return (0.0, _MAX_DV, 0.0)

        # Threat unit vector
        ux, uy, uz = dx/d, dy/d, dz/d

        # Build a vector perpendicular to threat in the orbital plane.
        # Cross threat with velocity to get an out-of-plane component.
        vx, vy, vz = self.velocity
        v_mag = math.sqrt(vx*vx + vy*vy + vz*vz) or 1.0
        nvx, nvy, nvz = vx/v_mag, vy/v_mag, vz/v_mag

        # perp = threat × velocity (gives out-of-plane direction)
        px = uy*nvz - uz*nvy
        py = uz*nvx - ux*nvz
        pz = ux*nvy - uy*nvx
        p_mag = math.sqrt(px*px + py*py + pz*pz) or 1.0
        px, py, pz = px/p_mag, py/p_mag, pz/p_mag

        # Magnitude: proportional to 1/d², capped
        mag = min(_MAX_DV, 1.0 / max(d, 0.1) ** 2 * 50.0)
        return (px * mag, py * mag, pz * mag)

    # ------------------------------------------------------------------
    # Maneuver execution
    # ------------------------------------------------------------------

    def execute_maneuver(self, dt: float) -> None:
        if self.maneuver_timer <= 0.0:
            if self.state == State.MANEUVERING:
                self.state = State.SAFE
                self.maneuver_timer = 0.0
                self.maneuver_vector = (0.0, 0.0, 0.0)
            return

        mx, my, mz = self.maneuver_vector
        vx, vy, vz = self.velocity
        # Apply impulse scaled by dt/MANEUVER_DURATION (spread over burn)
        frac = dt / MANEUVER_DURATION
        self.velocity = (vx + mx*frac, vy + my*frac, vz + mz*frac)
        self.maneuver_timer -= dt

    # ------------------------------------------------------------------
    # Communication
    # ------------------------------------------------------------------

    def broadcast_alert(self, network, threat_id: int,
                        threat_distance: float, sim_time: float) -> None:
        nearest_gs = "GS0"      # simplified: always alert GS0
        pkt = CollisionAlertPacket(
            source=self.sat_id,
            destination=nearest_gs,
            created_at=sim_time,
            threat_id=threat_id,
            threat_distance=threat_distance,
        )
        if network.send_packet(pkt):
            self.messages_sent += 1

    def _send_telemetry(self, network, sim_time: float) -> None:
        from routing import RoutingEngine
        path = RoutingEngine.find_ground_station_path(self.sat_id, network.graph)
        dest = path[-1] if path else "GS0"
        pkt = TelemetryPacket(
            source=self.sat_id,
            destination=dest,
            created_at=sim_time,
            position=self.position,
            velocity=self.velocity,
            sat_state=self.state.name,
        )
        if network.send_packet(pkt):
            self.messages_sent += 1

    # ------------------------------------------------------------------
    # Step
    # ------------------------------------------------------------------

    def step(self, sim_time: float, dt: float,
             all_positions: dict, network) -> None:
        # 1. Update position from physics
        self.position = self._orb.compute_position(
            self.sat_id, self.plane, self.index, sim_time)
        self.velocity = self._orb.compute_velocity(
            self.sat_id, self.plane, sim_time)

        # Apply maneuver delta-v on top of nominal velocity
        if self.state == State.MANEUVERING:
            self.execute_maneuver(dt)
            # Integrate modified velocity into position offset
            mx, my, mz = self.maneuver_vector
            px, py, pz = self.position
            self.position = (px + mx*dt*0.5, py + my*dt*0.5, pz + mz*dt*0.5)

        # 2. Sense threats
        threats = self.sense(all_positions)

        # 3. Broadcast alert when entering WARNING or MANEUVERING
        if threats and self.state in (State.WARNING, State.MANEUVERING):
            closest_id, closest_d = min(threats, key=lambda t: t[1])
            self.broadcast_alert(network, closest_id, closest_d, sim_time)

        # 4. Periodic telemetry
        self._telemetry_clock += dt
        if self._telemetry_clock >= TELEMETRY_INTERVAL:
            self._telemetry_clock = 0.0
            self._send_telemetry(network, sim_time)

        # 5. Count incoming messages (packets destined for this sat)
        # (incremented externally by network delivery — see ConstellationNetwork)


# ---------------------------------------------------------------------------
# Debris — dumb drifting objects, no comms, no avoidance
# ---------------------------------------------------------------------------

class DebrisAgent:
    """Non-maneuvering debris on a fixed trajectory."""

    def __init__(self, debris_id: int, orb: OrbitalMechanics,
                 seed: int | None = None):
        rng = random.Random(seed if seed is not None else debris_id)
        self.debris_id = debris_id

        # Random orbital parameters: slight altitude variation and inclination
        self._R = ORBITAL_RADIUS_KM + rng.uniform(-50.0, 50.0)
        self._inc = math.radians(rng.uniform(20.0, 80.0))
        self._raan = math.radians(rng.uniform(0.0, 360.0))
        self._phase0 = math.radians(rng.uniform(0.0, 360.0))

        # Orbital velocity adjusted for radius
        v = ORBITAL_VELOCITY_KM_S * math.sqrt(ORBITAL_RADIUS_KM / self._R)
        self._omega = 2.0 * math.pi * v / (2.0 * math.pi * self._R)

        self.position: tuple[float, float, float] = self._compute_pos(0.0)
        self.velocity: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.state: State = State.NOMINAL   # always NOMINAL — no avoidance

    def _compute_pos(self, t: float) -> tuple[float, float, float]:
        u = self._omega * t + self._phase0
        x_b = self._R * math.cos(u)
        y_b = self._R * math.sin(u) * math.cos(self._inc)
        z   = self._R * math.sin(u) * math.sin(self._inc)
        cos_r, sin_r = math.cos(self._raan), math.sin(self._raan)
        x = x_b * cos_r - y_b * sin_r
        y = x_b * sin_r + y_b * cos_r
        return (x, y, z)

    def step(self, sim_time: float, dt: float,
             all_positions: dict, network) -> None:
        self.position = self._compute_pos(sim_time)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_constellation(orb: OrbitalMechanics) -> list[SatelliteAgent]:
    sats_per_plane = NUM_SATELLITES // NUM_ORBITAL_PLANES
    return [
        SatelliteAgent(
            sat_id=p * sats_per_plane + i,
            plane=p,
            index_in_plane=i,
            orb=orb,
        )
        for p in range(NUM_ORBITAL_PLANES)
        for i in range(sats_per_plane)
    ]


def create_debris(orb: OrbitalMechanics, count: int = 5) -> list[DebrisAgent]:
    return [
        DebrisAgent(debris_id=_DEBRIS_ID_OFFSET + k, orb=orb, seed=k)
        for k in range(count)
    ]


def _unit3(v: tuple[float, float, float]) -> tuple[float, float, float]:
    m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / m, v[1] / m, v[2] / m)


class InterceptDebris:
    """
    Debris chunk on a near-collision trajectory (constant velocity, demo physics).
    """

    def __init__(self, debris_id: int,
                 position: tuple[float, float, float],
                 velocity: tuple[float, float, float]):
        self.debris_id = debris_id
        self.position = position
        self.velocity = velocity
        self.state: State = State.NOMINAL

    def step(self, sim_time: float, dt: float,
             all_positions: dict, network) -> None:
        vx, vy, vz = self.velocity
        px, py, pz = self.position
        self.position = (px + vx * dt, py + vy * dt, pz + vz * dt)


def spawn_chaos_debris(
    debris_id: int,
    target_position: tuple[float, float, float],
    rng: random.Random,
    speed: float = 0.42,
) -> InterceptDebris:
    """Spawn debris on an intercept-like path toward ``target_position``."""
    # Random offset from target (40–140 km)
    u = rng.random()
    v = rng.random()
    theta = 2.0 * math.pi * u
    phi = math.acos(2.0 * v - 1.0)
    r = rng.uniform(40.0, 140.0)
    ox = r * math.sin(phi) * math.cos(theta)
    oy = r * math.sin(phi) * math.sin(theta)
    oz = r * math.cos(phi)
    pos = (
        target_position[0] + ox,
        target_position[1] + oy,
        target_position[2] + oz,
    )
    toward = _unit3((
        target_position[0] - pos[0],
        target_position[1] - pos[1],
        target_position[2] - pos[2],
    ))
    # Small perpendicular component for visual crossing paths
    perp = _unit3((
        toward[1] - toward[2],
        toward[2] - toward[0],
        toward[0] - toward[1],
    ))
    t = rng.uniform(0.15, 0.45)
    vel = (
        toward[0] * speed + perp[0] * speed * t,
        toward[1] * speed + perp[1] * speed * t,
        toward[2] * speed + perp[2] * speed * t,
    )
    mag = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2) or 1.0
    scale = speed / mag
    vel = (vel[0] * scale, vel[1] * scale, vel[2] * scale)
    return InterceptDebris(debris_id, pos, vel)
