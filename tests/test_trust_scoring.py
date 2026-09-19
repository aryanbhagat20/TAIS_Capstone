"""
Tests for trust_scoring_engine.py — all 7 rules + composite scoring.
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.schema import TelemetryRecord, TrustAssessment, Confidence, Action
from src.engine.trust_scoring_engine import (
    TrustScoringEngine, ScoringConfig, RuleResult,
)


# ── Test helpers ──

def _make_record(
    device_id="TEST_001",
    timestamp=None,
    lat=12.97, lon=79.15,
    speed=40.0, heading=0.0,
    hdop=1.0, satellite_count=10,
    **kwargs,
) -> TelemetryRecord:
    """Create a TelemetryRecord with sensible defaults."""
    if timestamp is None:
        timestamp = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    return TelemetryRecord(
        device_id=device_id,
        timestamp=timestamp,
        latitude=lat, longitude=lon,
        speed=speed, heading=heading,
        hdop=hdop, satellite_count=satellite_count,
        **kwargs,
    )


def _make_clean_sequence(n: int = 30) -> list[TelemetryRecord]:
    """
    Generate a clean sequence of records simulating a vehicle
    moving north at ~40 km/h with 10s intervals.
    """
    base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    records = []
    for i in range(n):
        # ~40 km/h ≈ 11.1 m/s, in 10s = 111m ≈ 0.001° latitude
        records.append(TelemetryRecord(
            device_id="TEST_001",
            timestamp=base_time + timedelta(seconds=i * 10),
            latitude=12.97 + i * 0.001,
            longitude=79.15,
            speed=40.0,
            heading=0.0,   # Moving north
            hdop=1.0,
            satellite_count=10,
        ))
    return records


@pytest.fixture
def engine():
    return TrustScoringEngine()


@pytest.fixture
def clean_records():
    return _make_clean_sequence(30)


# ── Engine instantiation ──

class TestEngineBasics:
    def test_default_config(self, engine):
        """Engine should initialize with default config."""
        assert engine.config.speed_critical_kmh == 200.0
        assert engine.config.weight_motion == 0.35

    def test_custom_config(self):
        """Engine should accept custom config."""
        cfg = ScoringConfig(speed_critical_kmh=150.0)
        engine = TrustScoringEngine(config=cfg)
        assert engine.config.speed_critical_kmh == 150.0

    def test_empty_sequence(self, engine):
        """Empty input should return empty output."""
        result = engine.assess_sequence([])
        assert result == []

    def test_single_record(self, engine):
        """Single record (no previous) should get perfect score."""
        rec = _make_record()
        assessments = engine.assess_sequence([rec])
        assert len(assessments) == 1
        assert assessments[0].trust_score == 100.0
        assert assessments[0].action == Action.NORMAL

    def test_sequence_length_matches(self, engine, clean_records):
        """Output should have same length as input."""
        assessments = engine.assess_sequence(clean_records)
        assert len(assessments) == len(clean_records)


# ── Clean data should score well ──

class TestCleanData:
    def test_clean_sequence_all_normal(self, engine, clean_records):
        """Clean data should produce all-Normal assessments."""
        assessments = engine.assess_sequence(clean_records)
        for a in assessments:
            assert a.action == Action.NORMAL, (
                f"Record at {a.timestamp} scored {a.trust_score} "
                f"with reasons: {a.reasons}"
            )

    def test_clean_sequence_high_scores(self, engine, clean_records):
        """Clean data should score > 90 on every record."""
        assessments = engine.assess_sequence(clean_records)
        for a in assessments:
            assert a.trust_score >= 90.0, (
                f"Expected ≥90, got {a.trust_score}. Reasons: {a.reasons}"
            )

    def test_clean_first_record_perfect(self, engine, clean_records):
        """First record (no predecessor) should be 100."""
        assessments = engine.assess_sequence(clean_records)
        assert assessments[0].trust_score == 100.0

    def test_clean_no_reasons(self, engine, clean_records):
        """Clean data should produce no flagged reasons."""
        assessments = engine.assess_sequence(clean_records)
        for a in assessments:
            assert len(a.reasons) == 0, f"Unexpected reasons: {a.reasons}"


# ── R1: Speed limit ──

class TestR1Speed:
    def test_extreme_speed_critical(self, engine):
        """Speed > 200 km/h should be flagged as critical."""
        prev = _make_record(speed=40.0)
        rec = _make_record(
            speed=500.0,
            timestamp=prev.timestamp + timedelta(seconds=10),
            lat=prev.latitude + 0.013,  # consistent with high speed
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R1" in r for r in assessment.reasons)
        assert assessment.trust_score < 80.0

    def test_warn_speed(self, engine):
        """Speed 160-200 km/h should get a warning penalty."""
        prev = _make_record(speed=40.0)
        rec = _make_record(
            speed=180.0,
            timestamp=prev.timestamp + timedelta(seconds=10),
            lat=prev.latitude + 0.005,
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R1" in r for r in assessment.reasons)

    def test_normal_speed_no_flag(self, engine):
        """Speed < 160 km/h should not trigger R1."""
        rec = _make_record(speed=120.0)
        assessment = engine.assess_record(rec)
        r1_reasons = [r for r in assessment.reasons if "R1" in r]
        assert len(r1_reasons) == 0


# ── R2: Acceleration ──

class TestR2Acceleration:
    def test_impossible_acceleration(self, engine):
        """Going 0 → 300 km/h in 5s should flag R2."""
        prev = _make_record(speed=0.0)
        rec = _make_record(
            speed=300.0,
            timestamp=prev.timestamp + timedelta(seconds=5),
            lat=prev.latitude + 0.002,
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R2" in r for r in assessment.reasons)

    def test_normal_acceleration_no_flag(self, engine):
        """Gentle acceleration should not trigger R2."""
        prev = _make_record(speed=40.0)
        rec = _make_record(
            speed=45.0,
            timestamp=prev.timestamp + timedelta(seconds=10),
            lat=prev.latitude + 0.001,
        )
        assessment = engine.assess_record(rec, prev)
        r2_reasons = [r for r in assessment.reasons if "R2" in r]
        assert len(r2_reasons) == 0

    def test_harsh_braking_flags(self, engine):
        """Extreme braking should also flag R2."""
        prev = _make_record(speed=120.0)
        rec = _make_record(
            speed=0.0,
            timestamp=prev.timestamp + timedelta(seconds=2),
            lat=prev.latitude + 0.0003,
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R2" in r for r in assessment.reasons)


# ── R3: Position-speed mismatch ──

class TestR3PositionSpeed:
    def test_speed_but_no_movement(self, engine):
        """Reporting high speed but same position = R3 critical."""
        prev = _make_record(speed=100.0, lat=12.97, lon=79.15)
        rec = _make_record(
            speed=100.0,
            lat=12.97, lon=79.15,   # Same position!
            timestamp=prev.timestamp + timedelta(seconds=30),
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R3" in r for r in assessment.reasons)

    def test_movement_but_zero_speed(self, engine):
        """Position moved significantly but speed ≈ 0 = R3."""
        prev = _make_record(speed=0.0, lat=12.97, lon=79.15)
        rec = _make_record(
            speed=0.0,
            lat=12.97 + 0.01, lon=79.15,   # ~1.1 km movement
            timestamp=prev.timestamp + timedelta(seconds=10),
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R3" in r for r in assessment.reasons)

    def test_consistent_speed_position_no_flag(self, engine):
        """Consistent speed and position should not trigger R3."""
        prev = _make_record(speed=40.0, lat=12.97, lon=79.15)
        rec = _make_record(
            speed=40.0,
            lat=12.97 + 0.001, lon=79.15,  # ~111m, ≈ 40 km/h in 10s
            timestamp=prev.timestamp + timedelta(seconds=10),
        )
        assessment = engine.assess_record(rec, prev)
        r3_reasons = [r for r in assessment.reasons if "R3" in r]
        assert len(r3_reasons) == 0


# ── R4: Heading-bearing mismatch ──

class TestR4HeadingBearing:
    def test_heading_opposite_to_movement(self, engine):
        """Moving north but heading says south = R4."""
        prev = _make_record(lat=12.97, lon=79.15, speed=40.0, heading=180.0)
        rec = _make_record(
            lat=12.97 + 0.001, lon=79.15,  # Moved north
            speed=40.0, heading=180.0,      # Says south
            timestamp=prev.timestamp + timedelta(seconds=10),
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R4" in r for r in assessment.reasons)

    def test_heading_matches_movement_no_flag(self, engine):
        """Moving north with heading=0 should not trigger R4."""
        prev = _make_record(lat=12.97, lon=79.15, speed=40.0, heading=0.0)
        rec = _make_record(
            lat=12.97 + 0.001, lon=79.15,
            speed=40.0, heading=0.0,  # North = correct
            timestamp=prev.timestamp + timedelta(seconds=10),
        )
        assessment = engine.assess_record(rec, prev)
        r4_reasons = [r for r in assessment.reasons if "R4" in r]
        assert len(r4_reasons) == 0

    def test_no_check_at_low_speed(self, engine):
        """Heading check should be skipped at very low speeds."""
        prev = _make_record(lat=12.97, lon=79.15, speed=2.0, heading=180.0)
        rec = _make_record(
            lat=12.97 + 0.0001, lon=79.15,
            speed=2.0, heading=180.0,
            timestamp=prev.timestamp + timedelta(seconds=10),
        )
        assessment = engine.assess_record(rec, prev)
        r4_reasons = [r for r in assessment.reasons if "R4" in r]
        assert len(r4_reasons) == 0


# ── R5: HDOP degradation ──

class TestR5HDOP:
    def test_very_high_hdop(self, engine):
        """HDOP > 5.0 should trigger R5 critical."""
        rec = _make_record(hdop=8.0)
        assessment = engine.assess_record(rec)
        assert any("R5" in r for r in assessment.reasons)

    def test_normal_hdop_no_flag(self, engine):
        """HDOP < 3.0 should not trigger R5."""
        rec = _make_record(hdop=1.2)
        assessment = engine.assess_record(rec)
        r5_reasons = [r for r in assessment.reasons if "R5" in r]
        assert len(r5_reasons) == 0


# ── R6: Satellite count ──

class TestR6Satellites:
    def test_very_few_satellites(self, engine):
        """< 4 satellites should trigger R6 critical."""
        rec = _make_record(satellite_count=2)
        assessment = engine.assess_record(rec)
        assert any("R6" in r for r in assessment.reasons)

    def test_normal_satellite_count_no_flag(self, engine):
        """10 satellites should not trigger R6."""
        rec = _make_record(satellite_count=10)
        assessment = engine.assess_record(rec)
        r6_reasons = [r for r in assessment.reasons if "R6" in r]
        assert len(r6_reasons) == 0


# ── R7: Temporal anomaly ──

class TestR7Temporal:
    def test_timestamp_regression(self, engine):
        """Time going backwards should trigger R7 critical."""
        prev = _make_record(
            timestamp=datetime(2026, 9, 1, 10, 5, 0, tzinfo=timezone.utc)
        )
        rec = _make_record(
            timestamp=datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R7" in r for r in assessment.reasons)
        assert "regression" in " ".join(assessment.reasons).lower()

    def test_large_timestamp_gap(self, engine):
        """> 5 min gap should trigger R7 critical."""
        prev = _make_record()
        rec = _make_record(
            timestamp=prev.timestamp + timedelta(minutes=10)
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R7" in r for r in assessment.reasons)

    def test_normal_interval_no_flag(self, engine):
        """10s interval should not trigger R7."""
        prev = _make_record()
        rec = _make_record(
            timestamp=prev.timestamp + timedelta(seconds=10),
            lat=prev.latitude + 0.001,
        )
        assessment = engine.assess_record(rec, prev)
        r7_reasons = [r for r in assessment.reasons if "R7" in r]
        assert len(r7_reasons) == 0

    def test_near_duplicate_timestamp(self, engine):
        """< 0.5s gap should trigger R7 warning."""
        prev = _make_record()
        rec = _make_record(
            timestamp=prev.timestamp + timedelta(milliseconds=100),
        )
        assessment = engine.assess_record(rec, prev)
        assert any("R7" in r for r in assessment.reasons)


# ── Composite scoring ──

class TestCompositeScoring:
    def test_multiple_violations_compound(self, engine):
        """Multiple rule violations should compound penalties."""
        prev = _make_record(speed=40.0, lat=12.97, lon=79.15)
        # Terrible record: impossible speed, bad HDOP, low sats
        rec = _make_record(
            speed=500.0,
            lat=12.97, lon=79.15,  # no movement despite 500 km/h
            hdop=10.0,
            satellite_count=2,
            timestamp=prev.timestamp + timedelta(seconds=10),
        )
        assessment = engine.assess_record(rec, prev)
        assert assessment.trust_score < 35.0
        assert assessment.action == Action.ESCALATE
        assert len(assessment.reasons) >= 3

    def test_sub_scores_populated(self, engine, clean_records):
        """Sub-scores dict should have all 4 dimensions."""
        assessments = engine.assess_sequence(clean_records)
        for a in assessments:
            assert "motion" in a.sub_scores
            assert "trajectory" in a.sub_scores
            assert "signal" in a.sub_scores
            assert "temporal" in a.sub_scores

    def test_sub_scores_range(self, engine, clean_records):
        """Sub-scores should be in [0, 100]."""
        assessments = engine.assess_sequence(clean_records)
        for a in assessments:
            for dim, score in a.sub_scores.items():
                assert 0.0 <= score <= 100.0, (
                    f"{dim} sub-score {score} out of range"
                )


# ── Action thresholds ──

class TestActionThresholds:
    def test_normal_action(self, engine):
        """Score ≥ 70 should be Normal."""
        rec = _make_record()
        assessment = engine.assess_record(rec)
        assert assessment.action == Action.NORMAL

    def test_escalate_action(self, engine):
        """Very low score should Escalate."""
        prev = _make_record()
        # Create maximally bad record
        rec = _make_record(
            speed=800.0,
            lat=prev.latitude + 2.0,   # 220 km jump
            hdop=15.0,
            satellite_count=0,
            timestamp=prev.timestamp + timedelta(seconds=10),
            heading=180.0,
        )
        assessment = engine.assess_record(rec, prev)
        assert assessment.action == Action.ESCALATE


# ── Confidence levels ──

class TestConfidence:
    def test_high_confidence(self, engine, clean_records):
        """Good signal + long sequence → High confidence."""
        assessments = engine.assess_sequence(clean_records)
        # After enough records, should be High
        assert assessments[-1].confidence == Confidence.HIGH

    def test_low_confidence_bad_signal(self, engine):
        """Bad signal + short sequence → Low confidence."""
        rec = _make_record(hdop=5.0, satellite_count=3)
        assessment = engine.assess_record(rec, sequence_length=3)
        assert assessment.confidence == Confidence.LOW


# ── Summary statistics ──

class TestSequenceSummary:
    def test_summary_structure(self, engine, clean_records):
        """Summary should have expected keys."""
        assessments = engine.assess_sequence(clean_records)
        summary = engine.sequence_summary(assessments)
        assert "count" in summary
        assert "mean_score" in summary
        assert "min_score" in summary
        assert "max_score" in summary
        assert "normal_count" in summary
        assert "flagged_count" in summary
        assert "escalate_count" in summary
        assert summary["count"] == 30

    def test_clean_summary_all_normal(self, engine, clean_records):
        """Clean data summary should show all Normal."""
        assessments = engine.assess_sequence(clean_records)
        summary = engine.sequence_summary(assessments)
        assert summary["normal_count"] == 30
        assert summary["flagged_count"] == 0
        assert summary["escalate_count"] == 0

    def test_empty_summary(self, engine):
        """Empty assessments should return minimal summary."""
        summary = engine.sequence_summary([])
        assert summary["count"] == 0


# ── Integration with anomaly injector ──

class TestIntegrationWithInjector:
    """Test that the engine properly detects injected anomalies."""

    def test_detects_position_jump(self, engine, clean_records):
        """Engine should detect position jumps from the anomaly injector."""
        from src.injector.anomaly_injector import AnomalyInjector, AnomalyType

        injector = AnomalyInjector(seed=42)
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.POSITION_JUMP
        )

        assessments = engine.assess_sequence(anomalous)

        # Position jump causes massive R3 mismatch on adjacent records.
        # Check the jump record itself AND neighbours — at least one
        # should score below 75 (clear anomaly detection).
        jump_idx = labels[0].record_index
        nearby_indices = [
            i for i in range(max(0, jump_idx), min(len(assessments), jump_idx + 2))
        ]
        min_score = min(assessments[i].trust_score for i in nearby_indices)
        assert min_score <= 75.0, (
            f"Position jump at index {jump_idx} not detected. "
            f"Nearby scores: {[assessments[i].trust_score for i in nearby_indices]}"
        )

    def test_detects_speed_injection(self, engine, clean_records):
        """Engine should detect injected impossible speeds."""
        from src.injector.anomaly_injector import AnomalyInjector, AnomalyType

        injector = AnomalyInjector(seed=42)
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.SPEED_INJECTION
        )

        assessments = engine.assess_sequence(anomalous)

        # All injected records should trigger at least R1
        for label in labels:
            idx = label.record_index
            a = assessments[idx]
            assert any("R1" in r for r in a.reasons), (
                f"Speed injection at index {idx} not caught by R1. "
                f"Speed: {anomalous[idx].speed}, reasons: {a.reasons}"
            )

    def test_detects_gps_freeze(self, engine, clean_records):
        """Engine should detect GPS freeze anomaly."""
        from src.injector.anomaly_injector import AnomalyInjector, AnomalyType

        injector = AnomalyInjector(seed=42)
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.GPS_FREEZE
        )

        assessments = engine.assess_sequence(anomalous)

        # GPS freeze records report speed > 0 but position doesn't change
        # Should trigger R3 (position-speed mismatch)
        freeze_detected = False
        for label in labels[1:]:  # Skip first (no prev comparison)
            idx = label.record_index
            a = assessments[idx]
            if any("R3" in r for r in a.reasons):
                freeze_detected = True
                break

        assert freeze_detected, (
            "GPS freeze should trigger R3 (speed reported but no movement)"
        )
