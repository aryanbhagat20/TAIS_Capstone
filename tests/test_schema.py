"""
test_schema.py — sanity tests for the locked AIS-140 schema.
Run with: pytest tests/test_schema.py -v
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timezone
from schema import (
    TelemetryRecord, TrustAssessment,
    PositionValidity, DeviceStatus, Confidence, Action,
)


def make_sample_record(**overrides) -> TelemetryRecord:
    defaults = dict(
        device_id="DL1ZAA1234",
        timestamp=datetime.now(timezone.utc),
        latitude=12.9716,
        longitude=77.5946,
        speed=48.0,
        heading=92.0,
        hdop=0.8,
        satellite_count=12,
    )
    defaults.update(overrides)
    return TelemetryRecord(**defaults)


def test_record_creates_with_defaults():
    r = make_sample_record()
    assert r.device_id == "DL1ZAA1234"
    assert r.position_validity == PositionValidity.VALID
    assert r.device_status == DeviceStatus.OK
    assert r.harsh_braking is False


def test_record_to_dict_serializes_enums_and_timestamp():
    r = make_sample_record()
    d = r.to_dict()
    assert isinstance(d["timestamp"], str)
    assert d["position_validity"] == "A"
    assert d["device_status"] == "OK"


def test_record_to_json_roundtrip():
    r = make_sample_record()
    j = r.to_json()
    assert '"device_id": "DL1ZAA1234"' in j


def test_field_names_locked_count():
    # If this test breaks, someone changed the schema — that's fine,
    # but every downstream module (simulator, injector, engine) needs
    # to be checked against the change. Treat this as a tripwire, not
    # a hard rule never to touch.
    names = TelemetryRecord.field_names()
    assert "latitude" in names
    assert "longitude" in names
    assert "hdop" in names
    assert "satellite_count" in names
    # Explicitly confirm the known limitation is NOT silently "fixed"
    # by someone adding fields that don't exist in real AIS-140 packets:
    assert "gps_satellite_count" not in names
    assert "navic_satellite_count" not in names


def test_tamper_flag_defaults_false():
    r = make_sample_record()
    assert r.tamper_status is False


def test_trust_assessment_creates_and_serializes():
    ta = TrustAssessment(
        device_id="DL1ZAA1234",
        timestamp=datetime.now(timezone.utc),
        trust_score=28.0,
        confidence=Confidence.HIGH,
        action=Action.FLAGGED,
        reasons=["HDOP abnormal", "impossible speed"],
        sub_scores={"motion": 10, "trajectory": 5, "signal_quality": 8, "temporal": 5},
    )
    d = ta.to_dict()
    assert d["confidence"] == "High"
    assert d["action"] == "Flagged for review"
    assert "HDOP abnormal" in d["reasons"]


def test_trust_score_bounds_are_sane_inputs():
    # Not enforcing clamping inside the dataclass itself (that's the
    # Trust-Scoring Engine's job in Week 6) — this just documents the
    # expected range so a future contributor doesn't assume otherwise.
    ta = TrustAssessment(
        device_id="X", timestamp=datetime.now(timezone.utc),
        trust_score=0.0, confidence=Confidence.LOW, action=Action.ESCALATE,
    )
    assert 0 <= ta.trust_score <= 100
