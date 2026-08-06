"""
telemetry_simulator.py — SKELETON (Week 2)
=============================================

Class and method contracts only. Full implementation is Week 4's work.
Defined now so the architecture is reviewable at Review-1 and so
Week 4 has a locked interface to build against instead of designing
from scratch under time pressure.

Do not implement scenario logic here yet — that's explicitly Week 4.
"""

from __future__ import annotations
from enum import Enum
from datetime import datetime, timedelta
from typing import List

import sys
import os
# Unlike tests/ (which now rely on the root conftest.py), this file needs
# its own path handling because it's also run standalone
# (`python src/simulator/telemetry_simulator.py`, see __main__ below),
# a context conftest.py doesn't cover.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from schema import TelemetryRecord  # noqa: E402


class Scenario(Enum):
    HIGHWAY = "highway"
    CITY = "city"
    DEGRADED_SIGNAL = "degraded_signal"


class TelemetrySimulator:
    """
    Generates labelled, scenario-driven telemetry sequences conforming to
    the locked TelemetryRecord schema (src/schema.py, Week 1).

    Week 4 implementation plan (recorded here so the plan doesn't drift):
      - HIGHWAY: sustained speed 70-100 km/h, low HDOP (~0.6-1.0),
        satellite_count 10-14, gentle heading changes only.
      - CITY: speed 10-50 km/h, frequent stop/start, moderate HDOP
        (~1.0-2.5), more frequent heading changes, occasional
        harsh_braking events at realistic intersection-stop rates.
      - DEGRADED_SIGNAL: elevated HDOP (3.0-8.0), satellite_count
        dropping to 3-5, simulating tunnels/urban canyons — used
        specifically to generate the false-positive test cases the
        Trust-Scoring Engine must NOT flag as attacks (Week 9-10
        evaluation depends on having these on hand).
    """

    def __init__(self, device_id: str, scenario: Scenario, seed: int | None = None):
        self.device_id = device_id
        self.scenario = scenario
        self.seed = seed

    def generate_route(self, start_lat: float, start_lon: float,
                        duration_minutes: int, sample_rate_seconds: int = 5
                        ) -> List[TelemetryRecord]:
        """
        Generate a full labelled sequence of TelemetryRecord objects for
        this scenario, starting at (start_lat, start_lon), running for
        duration_minutes, sampled every sample_rate_seconds.

        WEEK 4 TODO: implement actual route-walking physics
        (speed/heading evolution per scenario profile above).
        Currently raises NotImplementedError intentionally — this is a
        skeleton, not a stub that silently returns fake data.
        """
        raise NotImplementedError("Week 4: implement scenario-specific route generation")

    def _next_position(self, lat: float, lon: float, speed_kmh: float,
                        heading_deg: float, dt_seconds: int) -> tuple[float, float]:
        """
        WEEK 4 TODO: basic dead-reckoning step — given current position,
        speed, heading, and elapsed time, compute the next lat/lon.
        Standard formula (haversine-based or simple flat-earth
        approximation, fine at these distances/durations).
        """
        raise NotImplementedError("Week 4: implement dead-reckoning position update")

    def _sample_signal_quality(self) -> tuple[float, float, int]:
        """
        WEEK 4 TODO: return (hdop, pdop, satellite_count) sampled
        appropriately for self.scenario, with realistic random jitter
        rather than a fixed constant — a simulator that always returns
        exactly HDOP=0.8 will make Week 6's rules trivially easy to
        pass and won't survive real evaluation.
        """
        raise NotImplementedError("Week 4: implement scenario-specific signal-quality sampling")

    def to_csv(self, records: List[TelemetryRecord], filepath: str) -> None:
        """
        WEEK 4 TODO: write a list of TelemetryRecord to CSV using
        TelemetryRecord.field_names() as the header — keeps this in
        sync with schema.py automatically if the schema ever changes.
        """
        raise NotImplementedError("Week 4: implement CSV export")


if __name__ == "__main__":
    # This will intentionally raise NotImplementedError right now —
    # that's correct for Week 2. Week 4 replaces the raise statements
    # above with real logic, and this same smoke test should then pass.
    sim = TelemetrySimulator(device_id="DL1ZAA1234", scenario=Scenario.HIGHWAY, seed=42)
    print(f"Skeleton instantiated OK: {sim.device_id}, scenario={sim.scenario.value}")
    print("Calling generate_route() will raise NotImplementedError until Week 4 — expected.")
