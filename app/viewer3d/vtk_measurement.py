from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Measurement:
    p1: tuple[float, float, float]
    p2: tuple[float, float, float]

    @property
    def dx(self) -> float:
        return self.p2[0] - self.p1[0]

    @property
    def dy(self) -> float:
        return self.p2[1] - self.p1[1]

    @property
    def dz(self) -> float:
        return self.p2[2] - self.p1[2]

    @property
    def distance(self) -> float:
        return math.sqrt(self.dx * self.dx + self.dy * self.dy + self.dz * self.dz)

    def to_dict(self) -> dict[str, object]:
        return {
            "p1": self.p1,
            "p2": self.p2,
            "distance": self.distance,
            "dx": self.dx,
            "dy": self.dy,
            "dz": self.dz,
        }
