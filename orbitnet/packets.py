import time
import itertools
from dataclasses import dataclass, field
from typing import Optional

_id_counter = itertools.count(1)


def _new_id() -> int:
    return next(_id_counter)


@dataclass
class BasePacket:
    source: int | str
    destination: int | str
    created_at: float
    size_bytes: int = 512
    packet_id: int = field(default_factory=_new_id)
    delivered_at: Optional[float] = None
    hops: int = 0
    path: list = field(default_factory=list)

    @property
    def latency_ms(self) -> Optional[float]:
        if self.delivered_at is None:
            return None
        return (self.delivered_at - self.created_at) * 1000.0


@dataclass
class CollisionAlertPacket(BasePacket):
    threat_id: int = -1
    threat_distance: float = 0.0
    urgency: str = "MEDIUM"          # "HIGH" | "MEDIUM"

    def __post_init__(self):
        if self.threat_distance < 5.0:
            self.urgency = "HIGH"
        self.size_bytes = 128


@dataclass
class TelemetryPacket(BasePacket):
    position: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))
    velocity: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))
    sat_state: str = "NOMINAL"

    def __post_init__(self):
        self.size_bytes = 256


@dataclass
class AvoidanceCommandPacket(BasePacket):
    target_sat_id: int = -1
    maneuver_vector: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))

    def __post_init__(self):
        self.size_bytes = 128
