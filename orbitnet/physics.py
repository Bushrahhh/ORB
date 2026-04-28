import math
from config import (
    ORBITAL_RADIUS_KM, ORBITAL_VELOCITY_KM_S,
    EARTH_RADIUS_KM, NUM_SATELLITES, NUM_ORBITAL_PLANES,
)

# J2 zonal harmonic — Earth oblateness coefficient
J2 = 1.08263e-3

# Walker constellation inclination (53° matches Starlink shell 1)
_INCLINATION_RAD = math.radians(53.0)
# Planes separated by 60° in RAAN
_RAAN_SPACING_RAD = math.radians(60.0)


class OrbitalMechanics:
    def __init__(self):
        self.R = ORBITAL_RADIUS_KM
        self.v = ORBITAL_VELOCITY_KM_S
        # T = circumference / speed
        self.T = 2.0 * math.pi * self.R / self.v          # seconds (~5726 s)
        self.omega = 2.0 * math.pi / self.T               # rad/s (~0.001098)
        self._sats_per_plane = NUM_SATELLITES // NUM_ORBITAL_PLANES  # 4

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _phase(self, index_in_plane: int) -> float:
        """Evenly-spaced mean anomaly offset for a satellite within its plane."""
        return 2.0 * math.pi * index_in_plane / self._sats_per_plane

    def _argument_of_latitude(self, index_in_plane: int, time_seconds: float) -> float:
        return self.omega * time_seconds + self._phase(index_in_plane)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_position(
        self,
        satellite_id: int,
        plane: int,
        index_in_plane: int,
        time_seconds: float,
    ) -> tuple[float, float, float]:
        """
        Circular orbit position in km (ECI-like Cartesian frame).

        Formula:
            base = R * [cos(u), sin(u)*cos(i), sin(u)*sin(i)]
            then rotated by RAAN around the z-axis.

        Planes are separated by 60° in RAAN.
        """
        inc = _INCLINATION_RAD
        raan = _RAAN_SPACING_RAD * plane
        u = self._argument_of_latitude(index_in_plane, time_seconds)

        # Base position in the plane's local frame (RAAN = 0)
        x_b = self.R * math.cos(u)
        y_b = self.R * math.sin(u) * math.cos(inc)
        z   = self.R * math.sin(u) * math.sin(inc)

        # Rotate by RAAN around the z-axis to place the plane correctly
        cos_r, sin_r = math.cos(raan), math.sin(raan)
        x = x_b * cos_r - y_b * sin_r
        y = x_b * sin_r + y_b * cos_r

        return (x, y, z)

    def compute_velocity(
        self,
        satellite_id: int,
        plane: int,
        time_seconds: float,
    ) -> tuple[float, float, float]:
        """
        Inertial velocity (km/s) — analytical derivative of compute_position.
        """
        index_in_plane = satellite_id % self._sats_per_plane
        inc = _INCLINATION_RAD
        raan = _RAAN_SPACING_RAD * plane
        u = self._argument_of_latitude(index_in_plane, time_seconds)

        # Time derivatives of the base position components
        dx_b = -self.R * self.omega * math.sin(u)
        dy_b =  self.R * self.omega * math.cos(u) * math.cos(inc)
        dz   =  self.R * self.omega * math.cos(u) * math.sin(inc)

        cos_r, sin_r = math.cos(raan), math.sin(raan)
        vx = dx_b * cos_r - dy_b * sin_r
        vy = dx_b * sin_r + dy_b * cos_r
        vz = dz

        return (vx, vy, vz)

    def apply_j2_perturbation(
        self,
        position: tuple[float, float, float],
        time: float,
    ) -> tuple[float, float, float]:
        """
        Applies two J2 effects to a 3-D position vector:
          1. Secular RAAN precession (dominant long-term drift).
          2. Short-period radial displacement due to Earth oblateness.
        """
        x, y, z = position
        r = math.sqrt(x * x + y * y + z * z)
        if r == 0.0:
            return position

        re_over_r = EARTH_RADIUS_KM / r

        # --- secular RAAN drift ---
        # dΩ/dt = -(3/2) n J2 (R_E/a)² cos(i)   [circular orbit, e=0]
        raan_rate = -1.5 * self.omega * J2 * re_over_r**2 * math.cos(_INCLINATION_RAD)
        raan_drift = raan_rate * time

        cos_d, sin_d = math.cos(raan_drift), math.sin(raan_drift)
        x1 = x * cos_d - y * sin_d
        y1 = x * sin_d + y * cos_d
        z1 = z

        # --- short-period radial perturbation ---
        sin_lat = z1 / r                           # sin of geocentric latitude
        delta_r = -1.5 * J2 * re_over_r**2 * r * (sin_lat**2 - 1.0 / 3.0)

        rx, ry, rz = x1 / r, y1 / r, z1 / r      # unit radial vector
        return (x1 + rx * delta_r, y1 + ry * delta_r, z1 + rz * delta_r)

    @staticmethod
    def distance_3d(
        pos1: tuple[float, float, float],
        pos2: tuple[float, float, float],
    ) -> float:
        """Euclidean distance between two 3-D points in km."""
        dx = pos1[0] - pos2[0]
        dy = pos1[1] - pos2[1]
        dz = pos1[2] - pos2[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    @staticmethod
    def project_to_screen(
        pos_3d: tuple[float, float, float],
        screen_w: int,
        screen_h: int,
    ) -> tuple[int, int]:
        """
        Isometric-style projection: rotates the 3-D ECI vector by fixed
        azimuth (20°) and elevation (25°) angles, then scales to screen.
        """
        x, y, z = pos_3d

        # Azimuth rotation around z-axis
        az = math.radians(20.0)
        cos_az, sin_az = math.cos(az), math.sin(az)
        x1 = x * cos_az - y * sin_az
        y1 = x * sin_az + y * cos_az

        # Elevation tilt around x-axis (brings z into the picture plane)
        el = math.radians(25.0)
        cos_el, sin_el = math.cos(el), math.sin(el)
        x2 = x1
        y2 = y1 * cos_el - z * sin_el

        scale = min(screen_w, screen_h) * 0.35 / ORBITAL_RADIUS_KM
        px = screen_w  // 2 + int(x2 * scale)
        py = screen_h  // 2 - int(y2 * scale)   # screen y is flipped
        return (px, py)
