"""
anomaly_injector.py — Inject deliberate anomalies into telemetry sequences.
============================================================================

Takes a genuine (clean) sequence of TelemetryRecord objects and produces
an anomalous variant by modifying specific fields. Every injected record
is labelled with metadata so the Trust-Scoring Engine's output can be
evaluated against known ground truth.

Six anomaly types (matching the project proposal):
    1. POSITION_JUMP   — Impossible teleport (lat/lon jumps)
    2. DRIFT           — Unrealistic positional drift while stationary
    3. SPEED_INJECTION — Impossible acceleration/speed value
    4. HEADING_CHANGE  — Impossible turning angle for the time interval
    5. REPLAY          — Old telemetry re-sent as current
    6. GPS_FREEZE      — Vehicle moves but GPS location stays fixed

Usage:
    injector = AnomalyInjector(seed=42)
    anomalous, labels = injector.inject(clean_records, AnomalyType.POSITION_JUMP)
"""

import copy
import random
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum

from src.schema import TelemetryRecord, PositionValidity


class AnomalyType(Enum):
    """The six deliberate anomaly categories defined in the project scope."""
    POSITION_JUMP = "position_jump"
    DRIFT = "drift"
    SPEED_INJECTION = "speed_injection"
    HEADING_CHANGE = "heading_change"
    REPLAY = "replay"
    GPS_FREEZE = "gps_freeze"


@dataclass
class AnomalyLabel:
    """
    Ground-truth label for an injected anomaly.

    Attached to each modified record so that evaluation metrics
    (precision, recall, F1) can be computed against the Trust-Scoring
    Engine's output.
    """
    record_index: int
    anomaly_type: AnomalyType
    original_values: dict = field(default_factory=dict)
    description: str = ""


class AnomalyInjector:
    """
    Inject anomalies into clean TelemetryRecord sequences.

    The injector works on deep copies — it never modifies the original
    input records. Each injection method targets a contiguous window
    of records within the sequence.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def inject(self, records: list[TelemetryRecord],
               anomaly_type: AnomalyType,
               start_pct: float = 0.3,
               end_pct: float = 0.5) -> tuple[list[TelemetryRecord],
                                               list[AnomalyLabel]]:
        """
        Inject a specific anomaly type into a copy of the record sequence.

        Args:
            records: Clean input sequence (not modified).
            anomaly_type: Which anomaly to inject.
            start_pct: Start of injection window as fraction of sequence
                       length (0.0–1.0). Default 0.3 = start at 30%.
            end_pct: End of injection window. Default 0.5 = end at 50%.

        Returns:
            (anomalous_records, labels):
                anomalous_records — deep copy with injected anomalies.
                labels — list of AnomalyLabel for each modified record.
        """
        if len(records) < 10:
            raise ValueError(
                f"Need at least 10 records to inject anomalies, got {len(records)}"
            )

        # Deep copy to avoid mutating input
        modified = copy.deepcopy(records)

        # Calculate injection window
        start_idx = max(1, int(len(modified) * start_pct))
        end_idx = min(len(modified) - 1, int(len(modified) * end_pct))
        if start_idx >= end_idx:
            end_idx = start_idx + max(3, len(modified) // 10)

        # Dispatch to specific injection method
        inject_fn = {
            AnomalyType.POSITION_JUMP: self._inject_position_jump,
            AnomalyType.DRIFT: self._inject_drift,
            AnomalyType.SPEED_INJECTION: self._inject_speed,
            AnomalyType.HEADING_CHANGE: self._inject_heading_change,
            AnomalyType.REPLAY: self._inject_replay,
            AnomalyType.GPS_FREEZE: self._inject_gps_freeze,
        }

        labels = inject_fn[anomaly_type](modified, start_idx, end_idx)
        return modified, labels

    def inject_random(self, records: list[TelemetryRecord]
                      ) -> tuple[list[TelemetryRecord], list[AnomalyLabel]]:
        """
        Inject a randomly chosen anomaly type at a random position.

        Useful for generating diverse test sets.
        """
        anomaly_type = self.rng.choice(list(AnomalyType))
        start_pct = self.rng.uniform(0.2, 0.6)
        window_size = self.rng.uniform(0.1, 0.3)
        end_pct = min(0.9, start_pct + window_size)

        return self.inject(records, anomaly_type, start_pct, end_pct)

    def inject_all_types(self, records: list[TelemetryRecord]
                         ) -> dict[AnomalyType,
                                   tuple[list[TelemetryRecord],
                                         list[AnomalyLabel]]]:
        """
        Generate one anomalous variant per anomaly type.

        Returns:
            Dict mapping AnomalyType → (anomalous_records, labels).
        """
        result = {}
        for atype in AnomalyType:
            result[atype] = self.inject(records, atype)
        return result

    # ================================================================
    # Individual anomaly injection methods
    # ================================================================

    def _inject_position_jump(self, records: list[TelemetryRecord],
                              start: int, end: int) -> list[AnomalyLabel]:
        """
        POSITION_JUMP: Teleport the vehicle to an impossible location.

        Shifts lat/lon by a large offset (0.5–2.0 degrees ≈ 55–220 km)
        at a single point, then optionally reverts — simulating a
        spoofed GPS fix that appears as an impossible teleport.
        """
        labels = []
        jump_idx = self.rng.randint(start, end)
        rec = records[jump_idx]

        lat_offset = self.rng.uniform(0.5, 2.0) * self.rng.choice([-1, 1])
        lon_offset = self.rng.uniform(0.5, 2.0) * self.rng.choice([-1, 1])

        original = {"latitude": rec.latitude, "longitude": rec.longitude}
        rec.latitude += lat_offset
        rec.longitude += lon_offset

        labels.append(AnomalyLabel(
            record_index=jump_idx,
            anomaly_type=AnomalyType.POSITION_JUMP,
            original_values=original,
            description=(f"Position jumped by ({lat_offset:.3f}°, "
                         f"{lon_offset:.3f}°) ≈ "
                         f"{abs(lat_offset) * 111:.0f} km displacement"),
        ))
        return labels

    def _inject_drift(self, records: list[TelemetryRecord],
                      start: int, end: int) -> list[AnomalyLabel]:
        """
        DRIFT: Vehicle appears stationary but position drifts slowly.

        Sets speed to ~0 while gradually shifting lat/lon by small
        increments — simulating a device that reports no movement but
        whose position creeps unrealistically.
        """
        labels = []
        drift_rate = self.rng.uniform(0.0001, 0.0005)  # degrees per record

        for i in range(start, end):
            rec = records[i]
            original = {
                "latitude": rec.latitude,
                "longitude": rec.longitude,
                "speed": rec.speed,
            }

            rec.speed = self.rng.uniform(0.0, 2.0)  # Near-zero speed
            rec.latitude += drift_rate * (i - start)
            rec.longitude += drift_rate * (i - start) * 0.7

            labels.append(AnomalyLabel(
                record_index=i,
                anomaly_type=AnomalyType.DRIFT,
                original_values=original,
                description=(f"Drift: speed set to {rec.speed:.1f} km/h "
                             f"but position shifted by "
                             f"{drift_rate * (i - start) * 111000:.1f}m"),
            ))
        return labels

    def _inject_speed(self, records: list[TelemetryRecord],
                      start: int, end: int) -> list[AnomalyLabel]:
        """
        SPEED_INJECTION: Report an impossible speed value.

        Sets speed to 300–800 km/h (physically impossible for road
        vehicles) for a window of records, while leaving position
        unchanged — creating a clear speed/distance contradiction.
        """
        labels = []
        injected_speed = self.rng.uniform(300, 800)

        for i in range(start, end):
            rec = records[i]
            original = {"speed": rec.speed}
            rec.speed = injected_speed + self.rng.uniform(-20, 20)

            labels.append(AnomalyLabel(
                record_index=i,
                anomaly_type=AnomalyType.SPEED_INJECTION,
                original_values=original,
                description=(f"Speed injected: {rec.speed:.1f} km/h "
                             f"(original: {original['speed']:.1f} km/h)"),
            ))
        return labels

    def _inject_heading_change(self, records: list[TelemetryRecord],
                               start: int, end: int) -> list[AnomalyLabel]:
        """
        HEADING_CHANGE: Impossible turning angle for the time interval.

        Flips heading by 90–180 degrees between consecutive records,
        which is physically impossible at reported speeds unless the
        vehicle is stationary.
        """
        labels = []

        for i in range(start, end):
            rec = records[i]
            original = {"heading": rec.heading}

            flip = self.rng.uniform(90, 180) * self.rng.choice([-1, 1])
            rec.heading = (rec.heading + flip) % 360

            labels.append(AnomalyLabel(
                record_index=i,
                anomaly_type=AnomalyType.HEADING_CHANGE,
                original_values=original,
                description=(f"Heading flipped by {flip:.0f}°: "
                             f"{original['heading']:.0f}° → {rec.heading:.0f}°"),
            ))
        return labels

    def _inject_replay(self, records: list[TelemetryRecord],
                       start: int, end: int) -> list[AnomalyLabel]:
        """
        REPLAY: Old telemetry re-sent as current.

        Copies a block of earlier records and pastes them into the
        injection window with updated timestamps — the position/speed
        sequence will be identical to an earlier segment, which is the
        signature of a replay attack.
        """
        labels = []

        # Source block: earlier in the sequence
        source_len = end - start
        source_start = max(0, start - source_len - 5)

        for i in range(start, end):
            source_idx = source_start + (i - start)
            if source_idx >= start or source_idx >= len(records):
                break

            rec = records[i]
            source = records[source_idx]

            original = {
                "latitude": rec.latitude,
                "longitude": rec.longitude,
                "speed": rec.speed,
                "heading": rec.heading,
            }

            # Copy position/motion from earlier record, keep current timestamp
            rec.latitude = source.latitude
            rec.longitude = source.longitude
            rec.speed = source.speed
            rec.heading = source.heading

            labels.append(AnomalyLabel(
                record_index=i,
                anomaly_type=AnomalyType.REPLAY,
                original_values=original,
                description=(f"Replayed data from record {source_idx} "
                             f"(timestamp {source.timestamp.isoformat()}) "
                             f"into position {i}"),
            ))
        return labels

    def _inject_gps_freeze(self, records: list[TelemetryRecord],
                           start: int, end: int) -> list[AnomalyLabel]:
        """
        GPS_FREEZE: Vehicle moves but GPS location stays fixed.

        Freezes lat/lon at the start-of-window value for all records
        in the window, while speed and heading may still vary — creating
        a contradiction between reported movement and static position.
        """
        labels = []

        frozen_lat = records[start].latitude
        frozen_lon = records[start].longitude

        for i in range(start, end):
            rec = records[i]
            original = {"latitude": rec.latitude, "longitude": rec.longitude}

            rec.latitude = frozen_lat
            rec.longitude = frozen_lon

            labels.append(AnomalyLabel(
                record_index=i,
                anomaly_type=AnomalyType.GPS_FREEZE,
                original_values=original,
                description=(f"GPS frozen at ({frozen_lat:.6f}, {frozen_lon:.6f}) "
                             f"while speed={rec.speed:.1f} km/h"),
            ))
        return labels
