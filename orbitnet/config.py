# ORB — LEO Satellite CCN
# Simulation configuration constants

NUM_SATELLITES = 12
NUM_ORBITAL_PLANES = 3          # 4 satellites per plane
ALTITUDE_KM = 550
EARTH_RADIUS_KM = 6371
ORBITAL_RADIUS_KM = EARTH_RADIUS_KM + ALTITUDE_KM   # 6921 km
ORBITAL_VELOCITY_KM_S = 7.6

COLLISION_THRESHOLD_KM = 2.0
WARNING_THRESHOLD_KM = 10.0
ISL_MAX_RANGE_KM = 2000

SIMULATION_SPEED = 50           # time multiplier

SCREEN_WIDTH = 1400
SCREEN_HEIGHT = 900
FPS = 60

COLORS = {
    "BACKGROUND":       (8,   0,  20),
    "EARTH":            (20,  0,  50),
    "EARTH_BORDER":     (83,  74, 183),
    "SAT_NOMINAL":      (127, 119, 221),
    "SAT_WARNING":      (212, 83,  126),
    "SAT_MANEUVERING":  (237, 147, 177),
    "SAT_SAFE":         (175, 169, 236),
    "ISL_ACTIVE":       (83,  74,  183),
    "ISL_CONGESTED":    (153, 53,  86),
    "DANGER_ZONE":      (212, 83,  126),
    "ALERT_PACKET":     (244, 192, 209),
    "DATA_PACKET":      (206, 203, 246),
    "GROUND_STATION":   (237, 147, 177),
    "TEXT_PRIMARY":     (206, 203, 246),
    "TEXT_SECONDARY":   (127, 119, 221),
    "PANEL_BG":         (13,  0,  24),
    "PANEL_BORDER":     (83,  74, 183),
    "METRIC_GOOD":      (93,  202, 165),
    "METRIC_WARN":      (239, 159, 39),
    "METRIC_DANGER":    (240, 149, 149),
}
