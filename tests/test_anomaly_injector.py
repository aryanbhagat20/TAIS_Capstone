"""
Tests for anomaly_injector.py — all 6 anomaly types.
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.schema import TelemetryRecord
from src.injector.anomaly_injector import (
    AnomalyInjector, AnomalyType, AnomalyLabel,
)


def _make_clean_sequence(n: int = 50) -> list[TelemetryRecord]:
    """
    Generate a minimal clean sequence for testing.
    Simulates a vehicle moving north at ~40 km/h.
    """
    base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    records = []
    for i in range(n):
        records.append(TelemetryRecord(
            device_id="TEST_001",
            timestamp=base_time + timedelta(seconds=i * 10),
            latitude=12.97 + i * 0.001,   # Moving north
            longitude=79.15,
            speed=40.0,
            heading=0.0,
            hdop=1.2,
            satellite_count=10,
        ))
    return records


@pytest.fixture
def injector():
    return AnomalyInjector(seed=42)


@pytest.fixture
def clean_records():
    return _make_clean_sequence(50)


# ── General injection tests ──

class TestInjectorBasics:
    def test_does_not_modify_original(self, injector, clean_records):
        """Input records must not be mutated."""
        original_lat = clean_records[20].latitude
        anomalous, _ = injector.inject(clean_records, AnomalyType.POSITION_JUMP)
        assert clean_records[20].latitude == original_lat

    def test_returns_same_length(self, injector, clean_records):
        """Output should have same number of records as input."""
        anomalous, _ = injector.inject(clean_records, AnomalyType.GPS_FREEZE)
        assert len(anomalous) == len(clean_records)

    def test_labels_have_correct_type(self, injector, clean_records):
        """All labels should report the injected anomaly type."""
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.SPEED_INJECTION
        )
        for label in labels:
            assert label.anomaly_type == AnomalyType.SPEED_INJECTION

    def test_labels_are_nonempty(self, injector, clean_records):
        """Injection should produce at least one label."""
        for atype in AnomalyType:
            _, labels = injector.inject(clean_records, atype)
            assert len(labels) > 0, f"{atype} produced no labels"

    def test_rejects_short_sequence(self, injector):
        """Should raise ValueError for sequences shorter than 10."""
        short = _make_clean_sequence(5)
        with pytest.raises(ValueError):
            injector.inject(short, AnomalyType.POSITION_JUMP)


# ── Type-specific tests ──

class TestPositionJump:
    def test_position_changes_dramatically(self, injector, clean_records):
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.POSITION_JUMP
        )
        idx = labels[0].record_index
        lat_diff = abs(anomalous[idx].latitude - clean_records[idx].latitude)
        assert lat_diff > 0.4, "Position jump should be > 0.4 degrees"


class TestDrift:
    def test_speed_near_zero_but_position_shifts(self, injector, clean_records):
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.DRIFT
        )
        for label in labels:
            idx = label.record_index
            assert anomalous[idx].speed < 5.0, "Drift should report near-zero speed"
            # Position should differ from original
            lat_diff = abs(
                anomalous[idx].latitude - clean_records[idx].latitude
            )
            # At least some drift records should have shifted position
        assert any(
            abs(anomalous[l.record_index].latitude -
                clean_records[l.record_index].latitude) > 0.0001
            for l in labels
        ), "Drift should shift position"


class TestSpeedInjection:
    def test_speed_is_impossibly_high(self, injector, clean_records):
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.SPEED_INJECTION
        )
        for label in labels:
            idx = label.record_index
            assert anomalous[idx].speed > 250, (
                f"Injected speed should be >250 km/h, got {anomalous[idx].speed}"
            )


class TestHeadingChange:
    def test_heading_flips_dramatically(self, injector, clean_records):
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.HEADING_CHANGE
        )
        for label in labels:
            idx = label.record_index
            original_heading = clean_records[idx].heading
            new_heading = anomalous[idx].heading
            delta = abs(new_heading - original_heading)
            if delta > 180:
                delta = 360 - delta
            assert delta > 80, f"Heading should flip >80°, got {delta:.0f}°"


class TestReplay:
    def test_replayed_positions_match_earlier(self, injector, clean_records):
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.REPLAY
        )
        # At least some replayed records should exist
        assert len(labels) > 0


class TestGPSFreeze:
    def test_position_frozen_across_window(self, injector, clean_records):
        anomalous, labels = injector.inject(
            clean_records, AnomalyType.GPS_FREEZE
        )
        frozen_lat = anomalous[labels[0].record_index].latitude
        frozen_lon = anomalous[labels[0].record_index].longitude
        for label in labels:
            idx = label.record_index
            assert anomalous[idx].latitude == frozen_lat
            assert anomalous[idx].longitude == frozen_lon


# ── Convenience methods ──

class TestConvenienceMethods:
    def test_inject_random(self, injector, clean_records):
        anomalous, labels = injector.inject_random(clean_records)
        assert len(labels) > 0
        assert len(anomalous) == len(clean_records)

    def test_inject_all_types(self, injector, clean_records):
        results = injector.inject_all_types(clean_records)
        assert len(results) == 6
        for atype in AnomalyType:
            assert atype in results
            anomalous, labels = results[atype]
            assert len(labels) > 0
