"""
trust_scoring_engine.py — TAIS Trust-Scoring Engine (Week 6-7)
================================================================

The core analytical engine of TAIS.  Takes a sequence of TelemetryRecord
objects and produces a TrustAssessment for each record, scoring the
telemetry's kinematic plausibility on a 0-100 scale.

Scoring Architecture:
    100 − Σ(penalties)  →  Trust Score  ∈ [0, 100]

    Penalties are computed from four sub-score dimensions:
        1. Motion Consistency   — speed limits, acceleration bounds
        2. Trajectory Consistency — position-speed agreement, heading-bearing match
        3. Signal Quality       — HDOP thresholds, satellite count
        4. Temporal Consistency — timestamp gaps, freeze/replay detection

    Each dimension contributes weighted penalties to the composite score.
    Every penalty generates a human-readable reason string for the
    Explanation Layer.

Rules (R1-R7):
    R1: Speed exceeds physical limit (>200 km/h for road vehicles)
    R2: Impossible acceleration (>6 m/s² ≈ 0.6g sustained)
    R3: Position-speed contradiction (reported speed vs actual displacement)
    R4: Heading-bearing mismatch (heading doesn't match travel direction)
    R5: HDOP degradation (HDOP > 5.0 = unreliable fix)
    R6: Satellite dropout (< 4 satellites = no valid 3D fix)
    R7: Temporal anomaly (timestamp gap, freeze, or regression)

Usage:
    engine = TrustScoringEngine()
    assessments = engine.assess_sequence(records)
    for a in assessments:
        print(f"Score: {a.trust_score}, Action: {a.action.value}")
        print(f"Reasons: {a.reasons}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from src.schema import (
    TelemetryRecord, TrustAssessment,
    Confidence, Action,
)
from src.data_loader.field_derivation import (
    haversine_distance, bearing, derive_speed, derive_acceleration,
)


# ──────────────────────────────────────────────────────────────────────
# Configuration: rule thresholds and penalty weights
# ──────────────────────────────────────────────────────────────────────

@dataclass
class ScoringConfig:
    """
    All tuneable parameters in one place.

    Thresholds are intentionally conservative — designed to avoid
    false positives on legitimate degraded-signal scenarios (tunnels,
    urban canyons) while catching clearly implausible data.
    """

    # ── R1: Speed limits ──
    speed_warn_kmh: float = 160.0       # Flag above this
    speed_critical_kmh: float = 200.0   # Impossible for road vehicles

    # ── R2: Acceleration limits ──
    accel_warn_ms2: float = 4.0         # Strong but possible (sports car)
    accel_critical_ms2: float = 6.0     # Physically implausible sustained

    # ── R3: Position-speed mismatch ──
    speed_position_ratio_warn: float = 2.0    # Reported speed / actual > 2x
    speed_position_ratio_critical: float = 5.0  # > 5x = clearly anomalous
    min_distance_for_check_m: float = 5.0     # Skip check below 5m (GPS noise)

    # ── R4: Heading-bearing mismatch ──
    heading_bearing_warn_deg: float = 45.0    # > 45° deviation
    heading_bearing_critical_deg: float = 90.0  # > 90° = going backwards?
    min_speed_for_heading_check_kmh: float = 5.0  # Skip when near-stationary

    # ── R5: HDOP degradation ──
    hdop_warn: float = 3.0              # Degraded but possibly legitimate
    hdop_critical: float = 5.0          # Very poor fix quality

    # ── R6: Satellite dropout ──
    satellite_warn: int = 5             # Below ideal but may still fix
    satellite_critical: int = 4         # < 4 = no valid 3D fix possible

    # ── R7: Temporal anomaly ──
    timestamp_gap_warn_s: float = 60.0     # > 1 min gap between records
    timestamp_gap_critical_s: float = 300.0  # > 5 min gap
    timestamp_min_delta_s: float = 0.5     # < 0.5s = suspicious duplicate

    # ── Penalty weights per rule (max penalty each rule can contribute) ──
    penalty_r1_speed: float = 25.0
    penalty_r2_accel: float = 20.0
    penalty_r3_pos_speed: float = 25.0
    penalty_r4_heading: float = 15.0
    penalty_r5_hdop: float = 10.0
    penalty_r6_satellite: float = 10.0
    penalty_r7_temporal: float = 15.0

    # ── Sub-score dimension weights (for weighted composite) ──
    weight_motion: float = 0.35         # R1 + R2
    weight_trajectory: float = 0.30     # R3 + R4
    weight_signal: float = 0.15         # R5 + R6
    weight_temporal: float = 0.20       # R7

    # ── Action thresholds ──
    threshold_flagged: float = 70.0     # Below this → Flagged
    threshold_escalate: float = 40.0    # Below this → Escalate

    # ── Confidence thresholds ──
    confidence_high_min_records: int = 10    # Need 10+ records for High
    confidence_satellite_min: int = 6        # Good satellite count
    confidence_hdop_max: float = 2.5         # Good signal quality


# ──────────────────────────────────────────────────────────────────────
# Rule evaluation results
# ──────────────────────────────────────────────────────────────────────

@dataclass
class RuleResult:
    """Result from evaluating a single rule on a single record."""
    rule_id: str                # e.g. "R1"
    rule_name: str              # e.g. "Speed Limit"
    triggered: bool             # Whether the rule was violated
    penalty: float              # Penalty points (0 if not triggered)
    severity: str               # "none", "warn", "critical"
    reason: str                 # Human-readable explanation
    dimension: str              # "motion", "trajectory", "signal", "temporal"


# ──────────────────────────────────────────────────────────────────────
# Trust-Scoring Engine
# ──────────────────────────────────────────────────────────────────────

class TrustScoringEngine:
    """
    Assess telemetry integrity by computing Trust Scores.

    Operates on sequences of TelemetryRecord objects. Each record is
    scored independently against the 7 rules, but some rules (R2, R3,
    R4, R7) require the previous record for comparison — the first
    record in a sequence always gets a perfect score.

    Usage:
        engine = TrustScoringEngine()
        assessments = engine.assess_sequence(records)

        # Or assess a single record against its predecessor:
        assessment = engine.assess_record(current, previous)
    """

    def __init__(self, config: ScoringConfig | None = None):
        self.config = config or ScoringConfig()

    def assess_sequence(self, records: list[TelemetryRecord]
                        ) -> list[TrustAssessment]:
        """
        Assess an entire telemetry sequence.

        Args:
            records: Ordered list of TelemetryRecord (by timestamp).

        Returns:
            List of TrustAssessment, one per input record.
        """
        if not records:
            return []

        assessments = []
        for i, record in enumerate(records):
            prev = records[i - 1] if i > 0 else None
            assessment = self.assess_record(
                record, prev, sequence_length=len(records)
            )
            assessments.append(assessment)

        return assessments

    def assess_record(self, record: TelemetryRecord,
                      prev: TelemetryRecord | None = None,
                      sequence_length: int = 1) -> TrustAssessment:
        """
        Assess a single record against all 7 rules.

        Args:
            record: The current telemetry record.
            prev: The previous record (None for first in sequence).
            sequence_length: Total records in sequence (for confidence).

        Returns:
            TrustAssessment with score, confidence, action, and reasons.
        """
        rule_results = self._evaluate_all_rules(record, prev)

        # Compute sub-scores per dimension
        sub_scores = self._compute_sub_scores(rule_results)

        # Compute weighted composite trust score
        trust_score = self._compute_composite_score(sub_scores)

        # Collect triggered reasons
        reasons = [r.reason for r in rule_results if r.triggered]

        # Determine action
        action = self._determine_action(trust_score)

        # Determine confidence
        confidence = self._determine_confidence(
            record, prev, sequence_length, rule_results
        )

        return TrustAssessment(
            device_id=record.device_id,
            timestamp=record.timestamp,
            trust_score=round(trust_score, 2),
            confidence=confidence,
            action=action,
            reasons=reasons,
            sub_scores=sub_scores,
        )

    # ──────────────────────────────────────────────────────────────
    # Rule evaluation
    # ──────────────────────────────────────────────────────────────

    def _evaluate_all_rules(self, record: TelemetryRecord,
                            prev: TelemetryRecord | None
                            ) -> list[RuleResult]:
        """Evaluate all 7 rules against a record."""
        results = [
            self._rule_r1_speed(record),
            self._rule_r2_acceleration(record, prev),
            self._rule_r3_position_speed(record, prev),
            self._rule_r4_heading_bearing(record, prev),
            self._rule_r5_hdop(record),
            self._rule_r6_satellites(record),
            self._rule_r7_temporal(record, prev),
        ]
        return results

    def _rule_r1_speed(self, record: TelemetryRecord) -> RuleResult:
        """R1: Speed exceeds physical limit for road vehicles."""
        c = self.config
        speed = record.speed

        if speed > c.speed_critical_kmh:
            return RuleResult(
                rule_id="R1", rule_name="Speed Limit",
                triggered=True, penalty=c.penalty_r1_speed,
                severity="critical", dimension="motion",
                reason=(f"R1: Speed {speed:.1f} km/h exceeds physical "
                        f"limit ({c.speed_critical_kmh} km/h)"),
            )
        elif speed > c.speed_warn_kmh:
            # Proportional penalty between warn and critical
            ratio = ((speed - c.speed_warn_kmh) /
                     (c.speed_critical_kmh - c.speed_warn_kmh))
            penalty = c.penalty_r1_speed * 0.5 * ratio
            return RuleResult(
                rule_id="R1", rule_name="Speed Limit",
                triggered=True, penalty=penalty,
                severity="warn", dimension="motion",
                reason=(f"R1: Speed {speed:.1f} km/h is unusually high "
                        f"(warn threshold: {c.speed_warn_kmh} km/h)"),
            )

        return RuleResult(
            rule_id="R1", rule_name="Speed Limit",
            triggered=False, penalty=0.0,
            severity="none", dimension="motion", reason="",
        )

    def _rule_r2_acceleration(self, record: TelemetryRecord,
                              prev: TelemetryRecord | None) -> RuleResult:
        """R2: Impossible acceleration between consecutive records."""
        c = self.config

        if prev is None:
            return RuleResult(
                rule_id="R2", rule_name="Acceleration",
                triggered=False, penalty=0.0,
                severity="none", dimension="motion", reason="",
            )

        dt = (record.timestamp - prev.timestamp).total_seconds()
        if dt <= 0:
            return RuleResult(
                rule_id="R2", rule_name="Acceleration",
                triggered=False, penalty=0.0,
                severity="none", dimension="motion", reason="",
            )

        accel = derive_acceleration(prev.speed, record.speed, dt)
        abs_accel = abs(accel)

        if abs_accel > c.accel_critical_ms2:
            action_word = "deceleration" if accel < 0 else "acceleration"
            return RuleResult(
                rule_id="R2", rule_name="Acceleration",
                triggered=True, penalty=c.penalty_r2_accel,
                severity="critical", dimension="motion",
                reason=(f"R2: Impossible {action_word} "
                        f"{abs_accel:.2f} m/s² "
                        f"(limit: {c.accel_critical_ms2} m/s²)"),
            )
        elif abs_accel > c.accel_warn_ms2:
            ratio = ((abs_accel - c.accel_warn_ms2) /
                     (c.accel_critical_ms2 - c.accel_warn_ms2))
            penalty = c.penalty_r2_accel * 0.5 * ratio
            action_word = "deceleration" if accel < 0 else "acceleration"
            return RuleResult(
                rule_id="R2", rule_name="Acceleration",
                triggered=True, penalty=penalty,
                severity="warn", dimension="motion",
                reason=(f"R2: Extreme {action_word} "
                        f"{abs_accel:.2f} m/s² "
                        f"(warn: {c.accel_warn_ms2} m/s²)"),
            )

        return RuleResult(
            rule_id="R2", rule_name="Acceleration",
            triggered=False, penalty=0.0,
            severity="none", dimension="motion", reason="",
        )

    def _rule_r3_position_speed(self, record: TelemetryRecord,
                                prev: TelemetryRecord | None) -> RuleResult:
        """
        R3: Position-speed contradiction.

        Compares the reported speed to the actual displacement derived
        from lat/lon changes. A large mismatch indicates the reported
        speed is inconsistent with the actual movement.
        """
        c = self.config

        if prev is None:
            return RuleResult(
                rule_id="R3", rule_name="Position-Speed Match",
                triggered=False, penalty=0.0,
                severity="none", dimension="trajectory", reason="",
            )

        dt = (record.timestamp - prev.timestamp).total_seconds()
        if dt <= 0:
            return RuleResult(
                rule_id="R3", rule_name="Position-Speed Match",
                triggered=False, penalty=0.0,
                severity="none", dimension="trajectory", reason="",
            )

        # Actual distance from coordinates
        actual_dist_m = haversine_distance(
            prev.latitude, prev.longitude,
            record.latitude, record.longitude,
        )

        # Skip check for very small movements (GPS noise)
        if actual_dist_m < c.min_distance_for_check_m and record.speed < 10:
            return RuleResult(
                rule_id="R3", rule_name="Position-Speed Match",
                triggered=False, penalty=0.0,
                severity="none", dimension="trajectory", reason="",
            )

        # Expected distance from reported speed
        avg_speed_ms = (record.speed + prev.speed) / 2 / 3.6  # km/h → m/s
        expected_dist_m = avg_speed_ms * dt

        # Compute ratio (avoid division by zero)
        if expected_dist_m < 1.0 and actual_dist_m > c.min_distance_for_check_m:
            # Speed says stationary but position moved significantly
            return RuleResult(
                rule_id="R3", rule_name="Position-Speed Match",
                triggered=True, penalty=c.penalty_r3_pos_speed,
                severity="critical", dimension="trajectory",
                reason=(f"R3: Position moved {actual_dist_m:.0f}m but "
                        f"reported speed ≈ 0 km/h (GPS freeze or drift?)"),
            )

        if actual_dist_m < 1.0 and expected_dist_m > 50:
            # Speed says moving but position didn't change
            return RuleResult(
                rule_id="R3", rule_name="Position-Speed Match",
                triggered=True, penalty=c.penalty_r3_pos_speed,
                severity="critical", dimension="trajectory",
                reason=(f"R3: Reported speed implies {expected_dist_m:.0f}m "
                        f"travel but position unchanged (speed injection?)"),
            )

        # General ratio check
        if expected_dist_m > 0:
            ratio = max(actual_dist_m, expected_dist_m) / max(
                min(actual_dist_m, expected_dist_m), 0.1
            )
        else:
            ratio = 1.0

        if ratio > c.speed_position_ratio_critical:
            return RuleResult(
                rule_id="R3", rule_name="Position-Speed Match",
                triggered=True, penalty=c.penalty_r3_pos_speed,
                severity="critical", dimension="trajectory",
                reason=(f"R3: Speed-position mismatch ratio {ratio:.1f}x "
                        f"(actual: {actual_dist_m:.0f}m, "
                        f"expected: {expected_dist_m:.0f}m)"),
            )
        elif ratio > c.speed_position_ratio_warn:
            r = ((ratio - c.speed_position_ratio_warn) /
                 (c.speed_position_ratio_critical - c.speed_position_ratio_warn))
            penalty = c.penalty_r3_pos_speed * 0.5 * r
            return RuleResult(
                rule_id="R3", rule_name="Position-Speed Match",
                triggered=True, penalty=penalty,
                severity="warn", dimension="trajectory",
                reason=(f"R3: Speed-position mismatch ratio {ratio:.1f}x "
                        f"(actual: {actual_dist_m:.0f}m, "
                        f"expected: {expected_dist_m:.0f}m)"),
            )

        return RuleResult(
            rule_id="R3", rule_name="Position-Speed Match",
            triggered=False, penalty=0.0,
            severity="none", dimension="trajectory", reason="",
        )

    def _rule_r4_heading_bearing(self, record: TelemetryRecord,
                                 prev: TelemetryRecord | None) -> RuleResult:
        """
        R4: Heading doesn't match actual travel direction.

        At speeds above the minimum threshold, the reported heading
        should roughly match the bearing computed from consecutive
        lat/lon positions.
        """
        c = self.config

        if prev is None:
            return RuleResult(
                rule_id="R4", rule_name="Heading-Bearing Match",
                triggered=False, penalty=0.0,
                severity="none", dimension="trajectory", reason="",
            )

        # Skip check at low speeds (heading is unreliable when stationary)
        if record.speed < c.min_speed_for_heading_check_kmh:
            return RuleResult(
                rule_id="R4", rule_name="Heading-Bearing Match",
                triggered=False, penalty=0.0,
                severity="none", dimension="trajectory", reason="",
            )

        # Skip if positions are identical (can't compute bearing)
        if (record.latitude == prev.latitude and
                record.longitude == prev.longitude):
            return RuleResult(
                rule_id="R4", rule_name="Heading-Bearing Match",
                triggered=False, penalty=0.0,
                severity="none", dimension="trajectory", reason="",
            )

        actual_bearing = bearing(
            prev.latitude, prev.longitude,
            record.latitude, record.longitude,
        )
        reported_heading = record.heading

        # Angular difference (handle wraparound)
        delta = abs(reported_heading - actual_bearing)
        if delta > 180:
            delta = 360 - delta

        if delta > c.heading_bearing_critical_deg:
            return RuleResult(
                rule_id="R4", rule_name="Heading-Bearing Match",
                triggered=True, penalty=c.penalty_r4_heading,
                severity="critical", dimension="trajectory",
                reason=(f"R4: Heading {reported_heading:.0f}° vs actual "
                        f"bearing {actual_bearing:.0f}° "
                        f"(deviation: {delta:.0f}°)"),
            )
        elif delta > c.heading_bearing_warn_deg:
            ratio = ((delta - c.heading_bearing_warn_deg) /
                     (c.heading_bearing_critical_deg -
                      c.heading_bearing_warn_deg))
            penalty = c.penalty_r4_heading * 0.5 * ratio
            return RuleResult(
                rule_id="R4", rule_name="Heading-Bearing Match",
                triggered=True, penalty=penalty,
                severity="warn", dimension="trajectory",
                reason=(f"R4: Heading {reported_heading:.0f}° deviates "
                        f"{delta:.0f}° from travel direction "
                        f"{actual_bearing:.0f}°"),
            )

        return RuleResult(
            rule_id="R4", rule_name="Heading-Bearing Match",
            triggered=False, penalty=0.0,
            severity="none", dimension="trajectory", reason="",
        )

    def _rule_r5_hdop(self, record: TelemetryRecord) -> RuleResult:
        """R5: HDOP degradation indicates unreliable GPS fix."""
        c = self.config

        if record.hdop > c.hdop_critical:
            return RuleResult(
                rule_id="R5", rule_name="HDOP Quality",
                triggered=True, penalty=c.penalty_r5_hdop,
                severity="critical", dimension="signal",
                reason=(f"R5: HDOP {record.hdop:.1f} indicates very poor "
                        f"fix quality (limit: {c.hdop_critical})"),
            )
        elif record.hdop > c.hdop_warn:
            ratio = ((record.hdop - c.hdop_warn) /
                     (c.hdop_critical - c.hdop_warn))
            penalty = c.penalty_r5_hdop * 0.5 * ratio
            return RuleResult(
                rule_id="R5", rule_name="HDOP Quality",
                triggered=True, penalty=penalty,
                severity="warn", dimension="signal",
                reason=(f"R5: HDOP {record.hdop:.1f} is degraded "
                        f"(warn: {c.hdop_warn})"),
            )

        return RuleResult(
            rule_id="R5", rule_name="HDOP Quality",
            triggered=False, penalty=0.0,
            severity="none", dimension="signal", reason="",
        )

    def _rule_r6_satellites(self, record: TelemetryRecord) -> RuleResult:
        """R6: Satellite dropout — insufficient satellites for valid fix."""
        c = self.config

        if record.satellite_count < c.satellite_critical:
            return RuleResult(
                rule_id="R6", rule_name="Satellite Count",
                triggered=True, penalty=c.penalty_r6_satellite,
                severity="critical", dimension="signal",
                reason=(f"R6: Only {record.satellite_count} satellites "
                        f"(need ≥{c.satellite_critical} for 3D fix)"),
            )
        elif record.satellite_count < c.satellite_warn:
            # Proportional: 4 sats = less penalty than 5 sats
            ratio = ((c.satellite_warn - record.satellite_count) /
                     (c.satellite_warn - c.satellite_critical + 1))
            penalty = c.penalty_r6_satellite * 0.5 * min(ratio, 1.0)
            return RuleResult(
                rule_id="R6", rule_name="Satellite Count",
                triggered=True, penalty=penalty,
                severity="warn", dimension="signal",
                reason=(f"R6: Low satellite count: {record.satellite_count} "
                        f"(ideal: ≥{c.satellite_warn})"),
            )

        return RuleResult(
            rule_id="R6", rule_name="Satellite Count",
            triggered=False, penalty=0.0,
            severity="none", dimension="signal", reason="",
        )

    def _rule_r7_temporal(self, record: TelemetryRecord,
                         prev: TelemetryRecord | None) -> RuleResult:
        """
        R7: Temporal anomaly detection.

        Checks for:
        - Timestamp gaps (missing data / signal loss)
        - Timestamp regression (time going backwards = replay indicator)
        - Near-duplicate timestamps (suspicious duplicates)
        """
        c = self.config

        if prev is None:
            return RuleResult(
                rule_id="R7", rule_name="Temporal Consistency",
                triggered=False, penalty=0.0,
                severity="none", dimension="temporal", reason="",
            )

        dt = (record.timestamp - prev.timestamp).total_seconds()

        # Timestamp regression — time goes backwards
        if dt < 0:
            return RuleResult(
                rule_id="R7", rule_name="Temporal Consistency",
                triggered=True, penalty=c.penalty_r7_temporal,
                severity="critical", dimension="temporal",
                reason=(f"R7: Timestamp regression detected — current "
                        f"time is {abs(dt):.1f}s BEFORE previous record "
                        f"(replay attack indicator)"),
            )

        # Near-duplicate timestamp
        if dt < c.timestamp_min_delta_s:
            return RuleResult(
                rule_id="R7", rule_name="Temporal Consistency",
                triggered=True, penalty=c.penalty_r7_temporal * 0.5,
                severity="warn", dimension="temporal",
                reason=(f"R7: Near-duplicate timestamp — only {dt:.2f}s "
                        f"gap (minimum: {c.timestamp_min_delta_s}s)"),
            )

        # Large timestamp gap
        if dt > c.timestamp_gap_critical_s:
            return RuleResult(
                rule_id="R7", rule_name="Temporal Consistency",
                triggered=True, penalty=c.penalty_r7_temporal,
                severity="critical", dimension="temporal",
                reason=(f"R7: Large timestamp gap: {dt:.0f}s "
                        f"({dt/60:.1f} min) — possible signal loss or "
                        f"data tampering"),
            )
        elif dt > c.timestamp_gap_warn_s:
            ratio = ((dt - c.timestamp_gap_warn_s) /
                     (c.timestamp_gap_critical_s - c.timestamp_gap_warn_s))
            penalty = c.penalty_r7_temporal * 0.5 * ratio
            return RuleResult(
                rule_id="R7", rule_name="Temporal Consistency",
                triggered=True, penalty=penalty,
                severity="warn", dimension="temporal",
                reason=(f"R7: Timestamp gap: {dt:.0f}s ({dt/60:.1f} min) — "
                        f"exceeds expected interval"),
            )

        return RuleResult(
            rule_id="R7", rule_name="Temporal Consistency",
            triggered=False, penalty=0.0,
            severity="none", dimension="temporal", reason="",
        )

    # ──────────────────────────────────────────────────────────────
    # Score computation
    # ──────────────────────────────────────────────────────────────

    def _compute_sub_scores(self, results: list[RuleResult]) -> dict:
        """
        Compute per-dimension sub-scores (0-100).

        Each dimension starts at 100 and has penalties subtracted.
        """
        dimension_penalties = {
            "motion": 0.0,
            "trajectory": 0.0,
            "signal": 0.0,
            "temporal": 0.0,
        }
        dimension_max = {
            "motion": self.config.penalty_r1_speed + self.config.penalty_r2_accel,
            "trajectory": self.config.penalty_r3_pos_speed + self.config.penalty_r4_heading,
            "signal": self.config.penalty_r5_hdop + self.config.penalty_r6_satellite,
            "temporal": self.config.penalty_r7_temporal,
        }

        for r in results:
            if r.triggered and r.dimension in dimension_penalties:
                dimension_penalties[r.dimension] += r.penalty

        sub_scores = {}
        for dim in dimension_penalties:
            max_penalty = dimension_max[dim]
            if max_penalty > 0:
                penalty_ratio = min(dimension_penalties[dim] / max_penalty, 1.0)
                sub_scores[dim] = round(100.0 * (1.0 - penalty_ratio), 2)
            else:
                sub_scores[dim] = 100.0

        return sub_scores

    def _compute_composite_score(self, sub_scores: dict) -> float:
        """
        Weighted composite trust score from dimension sub-scores.

        Formula: Σ(weight_i × sub_score_i)
        """
        c = self.config
        score = (
            c.weight_motion * sub_scores.get("motion", 100.0) +
            c.weight_trajectory * sub_scores.get("trajectory", 100.0) +
            c.weight_signal * sub_scores.get("signal", 100.0) +
            c.weight_temporal * sub_scores.get("temporal", 100.0)
        )
        return max(0.0, min(100.0, score))

    def _determine_action(self, trust_score: float) -> Action:
        """Map trust score to tiered response action."""
        if trust_score <= self.config.threshold_escalate:
            return Action.ESCALATE
        elif trust_score <= self.config.threshold_flagged:
            return Action.FLAGGED
        return Action.NORMAL

    def _determine_confidence(self, record: TelemetryRecord,
                              prev: TelemetryRecord | None,
                              sequence_length: int,
                              rule_results: list[RuleResult]) -> Confidence:
        """
        Determine assessment confidence level.

        High: Good signal quality + enough data points.
        Medium: Degraded signal OR short sequence.
        Low: Both degraded signal AND short sequence.
        """
        c = self.config

        good_signal = (
            record.satellite_count >= c.confidence_satellite_min and
            record.hdop <= c.confidence_hdop_max
        )
        enough_data = sequence_length >= c.confidence_high_min_records

        if good_signal and enough_data:
            return Confidence.HIGH
        elif good_signal or enough_data:
            return Confidence.MEDIUM
        else:
            return Confidence.LOW

    # ──────────────────────────────────────────────────────────────
    # Batch / summary utilities
    # ──────────────────────────────────────────────────────────────

    def sequence_summary(self, assessments: list[TrustAssessment]) -> dict:
        """
        Compute summary statistics for a sequence of assessments.

        Useful for dashboard overview and report generation.
        """
        if not assessments:
            return {"count": 0}

        scores = [a.trust_score for a in assessments]
        actions = [a.action for a in assessments]

        all_reasons = []
        for a in assessments:
            all_reasons.extend(a.reasons)

        # Count unique triggered rules
        rule_counts = {}
        for reason in all_reasons:
            rule_id = reason.split(":")[0].strip() if ":" in reason else reason
            rule_counts[rule_id] = rule_counts.get(rule_id, 0) + 1

        return {
            "count": len(assessments),
            "device_id": assessments[0].device_id,
            "mean_score": round(sum(scores) / len(scores), 2),
            "min_score": round(min(scores), 2),
            "max_score": round(max(scores), 2),
            "normal_count": sum(1 for a in actions if a == Action.NORMAL),
            "flagged_count": sum(1 for a in actions if a == Action.FLAGGED),
            "escalate_count": sum(1 for a in actions if a == Action.ESCALATE),
            "total_flags": len(all_reasons),
            "rule_breakdown": rule_counts,
            "time_range": {
                "start": assessments[0].timestamp.isoformat(),
                "end": assessments[-1].timestamp.isoformat(),
            },
        }
