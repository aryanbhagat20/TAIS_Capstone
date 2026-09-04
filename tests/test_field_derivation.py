"""
Tests for field_derivation.py — GPS math utilities.
"""

import math
import pytest
from datetime import datetime, timezone, timedelta

from src.data_loader.field_derivation import (
    haversine_distance,
    bearing,
    derive_speed,
    derive_heading,
    derive_acceleration,
    is_harsh_acceleration,
    is_harsh_braking,
    is_harsh_cornering,
    cumulative_mileage,
)


# ── Haversine distance tests ──

def test_haversine_same_point_is_zero():
    """Distance from a point to itself should be 0."""
    assert haversine_distance(12.9716, 77.5946, 12.9716, 77.5946) == 0.0


def test_haversine_known_distance():
    """VIT Vellore to Chennai Central ≈ 130 km (within 5% tolerance)."""
    # VIT Vellore: 12.9692°N, 79.1559°E
    # Chennai Central: 13.0827°N, 80.2707°E
    dist = haversine_distance(12.9692, 79.1559, 13.0827, 80.2707)
    assert 120_000 < dist < 140_000, f"Expected ~130 km, got {dist/1000:.1f} km"


def test_haversine_short_distance():
    """Two points ~111 metres apart (0.001° latitude at equator)."""
    dist = haversine_distance(0.0, 0.0, 0.001, 0.0)
    assert 100 < dist < 120, f"Expected ~111 m, got {dist:.1f} m"


# ── Bearing tests ──

def test_bearing_due_north():
    """Moving north should give bearing ≈ 0°."""
    b = bearing(10.0, 77.0, 11.0, 77.0)
    assert abs(b - 0.0) < 1.0 or abs(b - 360.0) < 1.0


def test_bearing_due_east():
    """Moving east should give bearing ≈ 90°."""
    b = bearing(10.0, 77.0, 10.0, 78.0)
    assert 85 < b < 95, f"Expected ~90°, got {b:.1f}°"


def test_bearing_due_south():
    """Moving south should give bearing ≈ 180°."""
    b = bearing(11.0, 77.0, 10.0, 77.0)
    assert 175 < b < 185, f"Expected ~180°, got {b:.1f}°"


# ── Speed derivation tests ──

def test_derive_speed_stationary():
    """Same point at different times → 0 speed."""
    t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 1, 10, 0, 10, tzinfo=timezone.utc)
    speed = derive_speed(12.97, 79.15, t1, 12.97, 79.15, t2)
    assert speed == 0.0


def test_derive_speed_known_value():
    """~111 m in 10 seconds ≈ 40 km/h."""
    t1 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 1, 10, 0, 10, tzinfo=timezone.utc)
    speed = derive_speed(0.0, 0.0, t1, 0.001, 0.0, t2)
    assert 35 < speed < 45, f"Expected ~40 km/h, got {speed:.1f}"


def test_derive_speed_zero_dt():
    """Same timestamp → 0 speed (avoid division by zero)."""
    t = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    speed = derive_speed(0.0, 0.0, t, 1.0, 1.0, t)
    assert speed == 0.0


# ── Heading derivation tests ──

def test_derive_heading_same_point():
    """Same point → heading 0."""
    h = derive_heading(12.0, 77.0, 12.0, 77.0)
    assert h == 0.0


# ── Acceleration tests ──

def test_acceleration_positive():
    """0 → 36 km/h in 5 seconds = 2 m/s²."""
    accel = derive_acceleration(0.0, 36.0, 5.0)
    assert abs(accel - 2.0) < 0.01


def test_acceleration_braking():
    """72 → 0 km/h in 5 seconds = -4 m/s²."""
    accel = derive_acceleration(72.0, 0.0, 5.0)
    assert abs(accel - (-4.0)) < 0.01


def test_harsh_acceleration_flag():
    assert is_harsh_acceleration(3.5) is True
    assert is_harsh_acceleration(2.0) is False


def test_harsh_braking_flag():
    assert is_harsh_braking(-4.0) is True
    assert is_harsh_braking(-2.0) is False


# ── Cornering tests ──

def test_harsh_cornering_fast_turn():
    """45° in 1 second = 45°/s → harsh."""
    assert is_harsh_cornering(0, 45, 1.0) is True


def test_harsh_cornering_slow_turn():
    """10° in 1 second = 10°/s → not harsh."""
    assert is_harsh_cornering(90, 100, 1.0) is False


def test_cornering_wraparound():
    """350° to 10° = 20° change, not 340°."""
    assert is_harsh_cornering(350, 10, 1.0) is False


# ── Mileage tests ──

def test_cumulative_mileage_empty():
    assert cumulative_mileage([]) == [0.0]


def test_cumulative_mileage_values():
    distances_m = [1000, 2000, 500]  # metres
    result = cumulative_mileage(distances_m)
    assert len(result) == 4
    assert result[0] == 0.0
    assert abs(result[1] - 1.0) < 0.001   # 1 km
    assert abs(result[2] - 3.0) < 0.001   # 3 km
    assert abs(result[3] - 3.5) < 0.001   # 3.5 km
