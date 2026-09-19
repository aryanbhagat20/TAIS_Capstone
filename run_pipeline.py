"""
run_pipeline.py — TAIS End-to-End Pipeline
============================================

Demonstrates the full TAIS pipeline:
    1. Generate clean telemetry (simulator)
    2. Inject anomalies
    3. Run Trust-Scoring Engine
    4. Output results as CSV + JSON summary

This script serves dual purposes:
    - Proof that the entire system works end-to-end
    - Generates sample output for the Review 2 document

Usage:
    python run_pipeline.py
    python run_pipeline.py --output-dir data/processed
    python run_pipeline.py --scenario highway --anomaly speed_injection
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
sys.path.insert(0, os.path.dirname(__file__))

from src.schema import TelemetryRecord, TrustAssessment
from src.injector.anomaly_injector import AnomalyInjector, AnomalyType, AnomalyLabel
from src.engine.trust_scoring_engine import TrustScoringEngine, ScoringConfig


# ----------------------------------------------------------------------
# Synthetic route generator (replaces the skeleton simulator)
# ----------------------------------------------------------------------

def generate_synthetic_route(
    device_id: str = "VIT_VELLORE_001",
    scenario: str = "highway",
    duration_minutes: int = 15,
    sample_rate_seconds: int = 10,
    seed: int = 42,
    start_lat: float = 12.9692,   # VIT Vellore campus
    start_lon: float = 79.1559,
) -> list[TelemetryRecord]:
    """
    Generate a realistic synthetic route for pipeline demonstration.

    Three scenarios matching the original project proposal:
        - highway: NH46 Chennai road, 60-100 km/h, good signal
        - city: Vellore city, 10-40 km/h, frequent stops, moderate signal
        - degraded: Tunnel/canyon, high HDOP, low satellites
    """
    import random
    rng = random.Random(seed)

    n_records = (duration_minutes * 60) // sample_rate_seconds
    base_time = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)

    # Scenario profiles
    profiles = {
        "highway": {
            "speed_range": (60, 100), "heading_jitter": 3,
            "hdop_range": (0.6, 1.2), "satellite_range": (10, 14),
        },
        "city": {
            "speed_range": (0, 40), "heading_jitter": 15,
            "hdop_range": (1.0, 2.5), "satellite_range": (7, 12),
        },
        "degraded": {
            "speed_range": (30, 70), "heading_jitter": 5,
            "hdop_range": (3.0, 8.0), "satellite_range": (3, 6),
        },
    }
    profile = profiles.get(scenario, profiles["highway"])

    records = []
    lat, lon = start_lat, start_lon
    heading = rng.uniform(0, 360)
    speed = rng.uniform(*profile["speed_range"])
    mileage = 0.0

    for i in range(n_records):
        # Evolve speed with gentle changes
        speed_delta = rng.uniform(-5, 5)
        speed = max(0, min(
            profile["speed_range"][1] + 10,
            speed + speed_delta
        ))

        # City scenario: occasional stops
        if scenario == "city" and rng.random() < 0.1:
            speed = 0.0

        # Evolve heading
        heading = (heading + rng.uniform(
            -profile["heading_jitter"], profile["heading_jitter"]
        )) % 360

        # Update position based on speed and heading
        import math
        speed_ms = speed / 3.6
        dist_m = speed_ms * sample_rate_seconds
        mileage += dist_m / 1000.0

        # Dead reckoning position update
        dlat = dist_m * math.cos(math.radians(heading)) / 111_320
        dlon = dist_m * math.sin(math.radians(heading)) / (
            111_320 * math.cos(math.radians(lat))
        )
        lat += dlat
        lon += dlon

        # Sample signal quality
        hdop = round(rng.uniform(*profile["hdop_range"]), 1)
        sats = rng.randint(*profile["satellite_range"])

        # Harsh event flags (rare)
        accel_ms2 = abs(speed_delta / 3.6 / sample_rate_seconds)
        harsh_accel = accel_ms2 > 3.0 and speed_delta > 0
        harsh_brake = accel_ms2 > 3.5 and speed_delta < 0

        records.append(TelemetryRecord(
            device_id=device_id,
            timestamp=base_time + timedelta(seconds=i * sample_rate_seconds),
            latitude=round(lat, 6),
            longitude=round(lon, 6),
            altitude=rng.uniform(200, 250),  # Vellore elevation ~220m
            speed=round(speed, 1),
            heading=round(heading, 1),
            hdop=hdop,
            pdop=round(hdop * 1.2, 1),
            satellite_count=sats,
            harsh_acceleration=harsh_accel,
            harsh_braking=harsh_brake,
            mileage=round(mileage, 3),
            battery_status="OK",
        ))

    return records


# ----------------------------------------------------------------------
# Pipeline orchestration
# ----------------------------------------------------------------------

def run_pipeline(
    scenario: str = "highway",
    anomaly_type: str | None = None,
    duration_minutes: int = 15,
    output_dir: str = "data/processed",
    seed: int = 42,
) -> dict:
    """
    Execute the full TAIS pipeline and return summary results.

    Returns:
        dict with pipeline results including trust score summary.
    """
    print("=" * 70)
    print("  TAIS — Telemetry Assessment and Integrity System")
    print("  End-to-End Pipeline Demonstration")
    print("=" * 70)

    # -- Stage 1: Generate clean telemetry --
    print(f"\n[1/4] Generating {scenario} telemetry "
          f"({duration_minutes} min, 10s intervals)...")
    clean_records = generate_synthetic_route(
        scenario=scenario, duration_minutes=duration_minutes, seed=seed,
    )
    print(f"      Generated {len(clean_records)} clean records")
    print(f"      Device: {clean_records[0].device_id}")
    print(f"      Start: ({clean_records[0].latitude:.4f}, "
          f"{clean_records[0].longitude:.4f})")
    print(f"      End:   ({clean_records[-1].latitude:.4f}, "
          f"{clean_records[-1].longitude:.4f})")

    # -- Stage 2: Inject anomalies --
    injector = AnomalyInjector(seed=seed)
    labels = []

    if anomaly_type and anomaly_type != "none":
        atype = AnomalyType(anomaly_type)
        print(f"\n[2/4] Injecting anomaly: {atype.value}...")
        records, labels = injector.inject(clean_records, atype)
        print(f"      Injected {len(labels)} anomalous records")
        print(f"      Window: indices {labels[0].record_index} "
              f"-> {labels[-1].record_index}")
    else:
        # Run all 6 types and pick one randomly for the demo
        print("\n[2/4] Injecting all 6 anomaly types for comparison...")
        all_results = injector.inject_all_types(clean_records)
        records = clean_records  # We'll score clean first

    # -- Stage 3: Trust-Scoring Engine --
    engine = TrustScoringEngine()

    if anomaly_type and anomaly_type != "none":
        print(f"\n[3/4] Running Trust-Scoring Engine on {anomaly_type} data...")
        assessments = engine.assess_sequence(records)
        summary = engine.sequence_summary(assessments)
    else:
        # Score clean data + all anomaly types
        print("\n[3/4] Running Trust-Scoring Engine...")
        print("      Scoring clean data...")
        clean_assessments = engine.assess_sequence(clean_records)
        clean_summary = engine.sequence_summary(clean_assessments)
        print(f"      Clean -> Mean: {clean_summary['mean_score']:.1f}, "
              f"All Normal: {clean_summary['normal_count']}/{clean_summary['count']}")

        all_summaries = {"clean": clean_summary}
        all_assessments = {"clean": clean_assessments}

        for atype, (anom_records, anom_labels) in all_results.items():
            anom_assessments = engine.assess_sequence(anom_records)
            anom_summary = engine.sequence_summary(anom_assessments)
            all_summaries[atype.value] = anom_summary
            all_assessments[atype.value] = anom_assessments
            print(f"      {atype.value:20s} -> Mean: {anom_summary['mean_score']:5.1f}, "
                  f"Flagged: {anom_summary['flagged_count']}, "
                  f"Escalate: {anom_summary['escalate_count']}")

        # Use clean + all for output
        assessments = clean_assessments
        summary = clean_summary

    # -- Stage 4: Export results --
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n[4/4] Exporting results to {output_dir}/...")

    # Export assessments CSV
    csv_path = os.path.join(output_dir, "trust_assessments.csv")
    _export_assessments_csv(assessments, csv_path)
    print(f"      [OK] {csv_path} ({len(assessments)} rows)")

    # Export input telemetry CSV
    telemetry_csv = os.path.join(output_dir, "input_telemetry.csv")
    _export_telemetry_csv(
        records if (anomaly_type and anomaly_type != "none") else clean_records,
        telemetry_csv,
    )
    print(f"      [OK] {telemetry_csv}")

    # Export summary JSON
    if anomaly_type and anomaly_type != "none":
        json_summary = {
            "pipeline_run": datetime.now(timezone.utc).isoformat(),
            "scenario": scenario,
            "anomaly_type": anomaly_type,
            "anomaly_labels": [
                {
                    "index": l.record_index,
                    "type": l.anomaly_type.value,
                    "description": l.description,
                }
                for l in labels
            ],
            "summary": summary,
        }
    else:
        json_summary = {
            "pipeline_run": datetime.now(timezone.utc).isoformat(),
            "scenario": scenario,
            "comparison": {k: v for k, v in all_summaries.items()},
        }

    json_path = os.path.join(output_dir, "pipeline_summary.json")
    with open(json_path, "w") as f:
        json.dump(json_summary, f, indent=2, default=str)
    print(f"      [OK] {json_path}")

    # -- Print results summary --
    print("\n" + "=" * 70)
    print("  PIPELINE RESULTS")
    print("=" * 70)

    if anomaly_type and anomaly_type != "none":
        print(f"\n  Scenario:     {scenario}")
        print(f"  Anomaly:      {anomaly_type}")
        print(f"  Records:      {summary['count']}")
        print(f"  Mean Score:   {summary['mean_score']:.2f}")
        print(f"  Min Score:    {summary['min_score']:.2f}")
        print(f"  Max Score:    {summary['max_score']:.2f}")
        print(f"  Normal:       {summary['normal_count']}")
        print(f"  Flagged:      {summary['flagged_count']}")
        print(f"  Escalate:     {summary['escalate_count']}")
        print(f"  Total Flags:  {summary['total_flags']}")
        if summary.get('rule_breakdown'):
            print(f"\n  Rule Breakdown:")
            for rule, count in sorted(summary['rule_breakdown'].items()):
                print(f"    {rule}: {count} triggers")
    else:
        print(f"\n  Scenario: {scenario}")
        print(f"  {'Type':<22} {'Mean':>6} {'Min':>6} {'Normal':>7} "
              f"{'Flagged':>8} {'Escalate':>9}")
        print(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*7} {'-'*8} {'-'*9}")
        for name, s in all_summaries.items():
            print(f"  {name:<22} {s['mean_score']:>6.1f} {s['min_score']:>6.1f} "
                  f"{s['normal_count']:>7} {s['flagged_count']:>8} "
                  f"{s['escalate_count']:>9}")

    print(f"\n  Output directory: {os.path.abspath(output_dir)}")
    print("=" * 70)

    return json_summary


def _export_assessments_csv(assessments: list[TrustAssessment], path: str):
    """Export trust assessments to CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "device_id", "timestamp", "trust_score", "confidence",
            "action", "reasons", "motion_score", "trajectory_score",
            "signal_score", "temporal_score",
        ])
        for a in assessments:
            writer.writerow([
                a.device_id,
                a.timestamp.isoformat(),
                a.trust_score,
                a.confidence.value,
                a.action.value,
                "; ".join(a.reasons) if a.reasons else "",
                a.sub_scores.get("motion", ""),
                a.sub_scores.get("trajectory", ""),
                a.sub_scores.get("signal", ""),
                a.sub_scores.get("temporal", ""),
            ])


def _export_telemetry_csv(records: list[TelemetryRecord], path: str):
    """Export telemetry records to CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(TelemetryRecord.field_names())
        for r in records:
            d = r.to_dict()
            writer.writerow([d[k] for k in TelemetryRecord.field_names()])


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="TAIS End-to-End Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pipeline.py
  python run_pipeline.py --scenario city --anomaly position_jump
  python run_pipeline.py --scenario highway --anomaly speed_injection --duration 30
  python run_pipeline.py --all-anomalies
        """,
    )
    parser.add_argument(
        "--scenario", choices=["highway", "city", "degraded"],
        default="highway", help="Driving scenario (default: highway)",
    )
    parser.add_argument(
        "--anomaly", choices=[a.value for a in AnomalyType] + ["none"],
        default=None, help="Specific anomaly to inject (default: all types)",
    )
    parser.add_argument(
        "--duration", type=int, default=15,
        help="Route duration in minutes (default: 15)",
    )
    parser.add_argument(
        "--output-dir", default="data/processed",
        help="Output directory (default: data/processed)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )

    args = parser.parse_args()
    run_pipeline(
        scenario=args.scenario,
        anomaly_type=args.anomaly,
        duration_minutes=args.duration,
        output_dir=args.output_dir,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
