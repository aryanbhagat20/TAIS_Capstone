"""
field_derivation.py — GPS math utilities for deriving TelemetryRecord fields.
=============================================================================

Used when raw GPS datasets provide only lat/lon/timestamp and we need to
compute speed, heading, distance, and acceleration — fields that AIS-140
devices report natively but that public GPS datasets often omit.

All functions operate on standard units:
    - Coordinates: decimal degrees (WGS-84)
    - Distance: metres
    - Speed: km/h (AIS-140 convention)
    - Heading/bearing: degrees, 0-359 (0=North, 90=East)
    - Time: seconds
"""

import math
from datetime import datetime

# Earth's mean radius in metres (WGS-84 approximation)
EARTH_RADIUS_M = 6_371_000


def haversine_distance(lat1: float, lon1: float,
                       lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two GPS points in metres.

    Uses the Haversine formula — accurate to ~0.5% for distances under
    a few hundred km, which is more than sufficient for consecutive
    telemetry points logged at 1–30 second intervals.

    Args:
        lat1, lon1: First point (decimal degrees).
        lat2, lon2: Second point (decimal degrees).

    Returns:
        Distance in metres.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing(lat1: float, lon1: float,
            lat2: float, lon2: float) -> float:
    """
    Initial bearing (forward azimuth) from point 1 to point 2.

    Returns:
        Bearing in degrees, 0-359 (0 = North, 90 = East).
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)

    x = math.sin(dlam) * math.cos(phi2)
    y = (math.cos(phi1) * math.sin(phi2) -
         math.sin(phi1) * math.cos(phi2) * math.cos(dlam))

    theta = math.atan2(x, y)
    return (math.degrees(theta) + 360) % 360


def derive_speed(lat1: float, lon1: float, t1: datetime,
                 lat2: float, lon2: float, t2: datetime) -> float:
    """
    Derive speed (km/h) between two consecutive GPS fixes.

    If the time delta is zero or negative, returns 0.0 to avoid
    division-by-zero — this can happen with duplicate timestamps
    in noisy GPS logs.

    Args:
        lat1, lon1, t1: Previous fix.
        lat2, lon2, t2: Current fix.

    Returns:
        Speed in km/h.
    """
    dt = (t2 - t1).total_seconds()
    if dt <= 0:
        return 0.0

    dist_m = haversine_distance(lat1, lon1, lat2, lon2)
    speed_ms = dist_m / dt       # m/s
    return speed_ms * 3.6         # km/h


def derive_heading(lat1: float, lon1: float,
                   lat2: float, lon2: float) -> float:
    """
    Derive heading (degrees, 0-359) from previous to current point.

    If both points are identical (stationary), returns 0.0.
    """
    if lat1 == lat2 and lon1 == lon2:
        return 0.0
    return bearing(lat1, lon1, lat2, lon2)


def derive_acceleration(speed1_kmh: float, speed2_kmh: float,
                        dt_seconds: float) -> float:
    """
    Derive acceleration in m/s² from two consecutive speed readings.

    Positive = accelerating, negative = braking.
    Returns 0.0 if dt is zero.
    """
    if dt_seconds <= 0:
        return 0.0
    # Convert km/h to m/s
    v1 = speed1_kmh / 3.6
    v2 = speed2_kmh / 3.6
    return (v2 - v1) / dt_seconds


def is_harsh_acceleration(accel_ms2: float, threshold: float = 3.0) -> bool:
    """Acceleration exceeds threshold (default 3.0 m/s² ≈ 0.3g)."""
    return accel_ms2 > threshold


def is_harsh_braking(accel_ms2: float, threshold: float = -3.5) -> bool:
    """Deceleration exceeds threshold (default -3.5 m/s² ≈ -0.36g)."""
    return accel_ms2 < threshold


def is_harsh_cornering(heading1: float, heading2: float,
                       dt_seconds: float,
                       threshold_deg_per_sec: float = 30.0) -> bool:
    """
    Heading change rate exceeds threshold.

    Handles the 359° → 1° wraparound correctly.
    Default threshold: 30°/s (a very sharp turn at speed).
    """
    if dt_seconds <= 0:
        return False

    delta = abs(heading2 - heading1)
    if delta > 180:
        delta = 360 - delta

    rate = delta / dt_seconds
    return rate > threshold_deg_per_sec


def cumulative_mileage(distances_m: list[float]) -> list[float]:
    """
    Convert a list of per-segment distances (metres) into cumulative
    mileage (km) — matching the AIS-140 odometer convention.

    Args:
        distances_m: List of distances between consecutive points.

    Returns:
        List of cumulative mileage values in km (same length + 1 as input,
        starting from 0.0).
    """
    result = [0.0]
    running = 0.0
    for d in distances_m:
        running += d
        result.append(running / 1000.0)  # m → km
    return result
