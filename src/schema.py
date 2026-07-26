"""
schema.py — AIS-140 Telemetry Data Schema (LOCKED, Week 1)
=============================================================

This is the single source of truth for what a telemetry record looks like
in TAIS. Every later module (simulator, anomaly injector, trust-scoring
engine, dashboard) imports TelemetryRecord from here. Do not redefine
these fields anywhere else in the project.

Field set verified against real AIS-140 protocol documentation (a
commercial telematics platform's field-level parser was used as ground
truth, since the primary ARAI specification PDF is not publicly
fetchable). See docs/literature_survey.md, Section "Verified Data
Fields" for the source reasoning.

Fields marked (derived) are NOT part of the raw AIS-140 packet — they
are computed later by the Trust-Scoring Engine and attached to a record
for output/dashboard purposes. Keeping them in the same dataclass (but
clearly separated) avoids a second parallel schema.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
import json


class PositionValidity(Enum):
    """Whether the device itself considers this fix valid."""
    VALID = "A"
    INVALID = "V"


class DeviceStatus(Enum):
    """Coarse device health status, as transmitted by real AIS-140 devices."""
    OK = "OK"
    TAMPER = "TAMPER"
    LOW_BATTERY = "LOW_BATTERY"
    NO_GPS_FIX = "NO_GPS_FIX"


@dataclass
class TelemetryRecord:
    # --- Identity & time ---
    device_id: str                      # e.g. "DL1ZAA1234"
    timestamp: datetime                 # UTC

    # --- Position ---
    latitude: float                     # degrees, e.g. 12.9716
    longitude: float                    # degrees, e.g. 77.5946
    altitude: float = 0.0                # metres

    # --- Motion ---
    speed: float = 0.0                   # km/h
    heading: float = 0.0                 # degrees, 0-359

    # --- Signal quality (critical for Trust-Scoring Engine, Week 6) ---
    hdop: float = 1.0                    # Horizontal Dilution of Precision
    pdop: float = 1.0                    # Positional Dilution of Precision
    satellite_count: int = 8              # number of satellites used in fix
    position_validity: PositionValidity = PositionValidity.VALID

    # --- Motion-event flags (boolean, as transmitted — NOT raw IMU data) ---
    harsh_acceleration: bool = False
    harsh_braking: bool = False
    harsh_cornering: bool = False

    # --- Device / vehicle status ---
    tamper_status: bool = False          # physical tamper flag (existing AIS-140 check)
    tilt_status: bool = False
    sos_status: bool = False
    mileage: float = 0.0                  # cumulative odometer, km
    battery_status: str = "OK"           # e.g. "OK", "LOW", "CHARGING"
    device_status: DeviceStatus = DeviceStatus.OK

    # --- GSM/network context (present in real packets; useful for
    #     temporal/replay checks even though not GNSS-specific) ---
    gsm_cell_id: str = ""
    gsm_signal_strength: int = 0          # 0-31 typical GSM RSSI scale

    # ------------------------------------------------------------------
    # NOTE: There is deliberately NO per-constellation (GPS-only vs.
    # NavIC-only) breakdown here. Verified finding from research phase:
    # standard AIS-140 devices fuse GPS+NavIC internally before
    # transmission and report one blended fix. Do not add
    # gps_satellite_count / navic_satellite_count fields pretending this
    # data exists at the backend — it doesn't, for any device following
    # the standard packet format. This limitation is exactly what
    # motivates the "Future Scope: protocol extension" section of the
    # project (see one-pager, Section "What Data You Actually Have").
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to a plain dict (for CSV/JSON export in later weeks)."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        d["position_validity"] = self.position_validity.value
        d["device_status"] = self.device_status.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @staticmethod
    def field_names() -> list:
        """Convenience for building CSV headers in the simulator (Week 4)."""
        return list(TelemetryRecord.__dataclass_fields__.keys())


# ----------------------------------------------------------------------
# Derived / output schema (produced by the Trust-Scoring Engine, Week 6-7)
# Kept separate from TelemetryRecord on purpose: this is TAIS's OUTPUT,
# not part of the AIS-140 input contract.
# ----------------------------------------------------------------------

class Confidence(Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Action(Enum):
    NORMAL = "Normal"
    FLAGGED = "Flagged for review"
    ESCALATE = "Escalate"


@dataclass
class TrustAssessment:
    device_id: str
    timestamp: datetime
    trust_score: float                  # 0-100
    confidence: Confidence
    action: Action
    reasons: list = field(default_factory=list)   # e.g. ["HDOP abnormal", "impossible speed"]
    sub_scores: dict = field(default_factory=dict)  # {"motion": .., "trajectory": .., ...}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        d["confidence"] = self.confidence.value
        d["action"] = self.action.value
        return d


if __name__ == "__main__":
    # Quick sanity check — run with: python src/schema.py
    sample = TelemetryRecord(
        device_id="DL1ZAA1234",
        timestamp=datetime.now(timezone.utc),
        latitude=12.9716,
        longitude=77.5946,
        speed=48.0,
        heading=92.0,
        hdop=0.8,
        satellite_count=12,
    )
    print("Sample TelemetryRecord:")
    print(json.dumps(sample.to_dict(), indent=2))
    print("\nLocked field set (import this list, don't redefine it):")
    print(TelemetryRecord.field_names())
