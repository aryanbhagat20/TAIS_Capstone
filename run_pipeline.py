"""
run_pipeline.py -- TAIS End-to-End Pipeline v2.0
==================================================

Full TAIS pipeline using REAL collected GPS data (hybrid mode):
    1. Load real telemetry (own collection + T-Drive)
    2. Inject anomalies for testing
    3. Run Trust-Scoring Engine
    4. Export results as CSV + JSON summary

Supports:
    - Own GPS data (GPSLogger CSV from data/raw/own_collection/)
    - T-Drive taxi data (from data/raw/tdrive/)
    - Synthetic data as fallback (if no real data available)

Usage:
    python run_pipeline.py                         # All real trips
    python run_pipeline.py --trip trip_01_campus    # Specific trip
    python run_pipeline.py --trip trip_01_campus --anomaly speed_injection
    python run_pipeline.py --mode synthetic --scenario highway  # Legacy mode
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
from src.data_loader.own_data_loader import OwnDataLoader
from src.data_loader.tdrive_loader import TDriveLoader


# Directories
OWN_DATA_DIR = Path("data/raw/own_collection")
TDRIVE_DIR = Path("data/raw/tdrive")

# Trip metadata
TRIP_CATALOG = {
    "trip_01_campus":    {"source": "own", "label": "Campus Walk (VIT)"},
    "trip_02_city":      {"source": "own", "label": "City Drive (Vellore)"},
    "trip_03_highway":   {"source": "own", "label": "Highway Drive"},
    "trip_05_stationary": {"source": "own", "label": "Stationary (Parked)"},
}


def discover_trips():
    """Discover all available real data trips."""
    trips = {}

    # Own collection
    if OWN_DATA_DIR.exists():
        for csv_file in sorted(OWN_DATA_DIR.glob("trip_*.csv")):
            name = csv_file.stem
            label = TRIP_CATALOG.get(name, {}).get("label", name)
            trips[name] = {"source": "own", "label": label, "path": str(csv_file)}

    # T-Drive
    if TDRIVE_DIR.exists():
        for txt_file in sorted(TDRIVE_DIR.glob("*.txt")):
            taxi_id = txt_file.stem
            name = f"tdrive_{taxi_id}"
            trips[name] = {
                "source": "tdrive",
                "label": f"Beijing Taxi #{taxi_id}",
                "path": str(txt_file),
            }

    return trips


def load_real_trip(trip_name, trips_catalog):
    """Load a single trip by name."""
    info = trips_catalog[trip_name]

    if info["source"] == "own":
        loader = OwnDataLoader()
        device_id = f"ARYAN_{trip_name.split('_')[2].upper()}"
        return loader.load_trip(info["path"], device_id=device_id)
    else:
        loader = TDriveLoader(str(TDRIVE_DIR))
        taxi_id = int(trip_name.replace("tdrive_", ""))
        return loader.load_taxi(taxi_id=taxi_id)


# ----------------------------------------------------------------------
# Synthetic route generator (fallback only)
# ----------------------------------------------------------------------

def generate_synthetic_route(
    device_id: str = "VIT_VELLORE_001",
    scenario: str = "highway",
    duration_minutes: int = 15,
    sample_rate_seconds: int = 10,
    seed: int = 42,
    start_lat: float = 12.9692,
    start_lon: float = 79.1559,
) -> list[TelemetryRecord]:
    """Generate a synthetic route (fallback when no real data exists)."""
    import random
    rng = random.Random(seed)

    n_records = (duration_minutes * 60) // sample_rate_seconds
    base_time = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)

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
    p = profiles[scenario]

    import math
    records = []
    lat, lon = start_lat, start_lon
    heading = rng.uniform(0, 360)
    speed = rng.uniform(*p["speed_range"])

    for i in range(n_records):
        from src.schema import PositionValidity, DeviceStatus
        speed += rng.uniform(-5, 5)
        speed = max(0, min(speed, p["speed_range"][1] * 1.1))
        heading = (heading + rng.uniform(-p["heading_jitter"],
                                          p["heading_jitter"])) % 360
        dist_km = (speed / 3600) * sample_rate_seconds
        lat += dist_km * math.cos(math.radians(heading)) / 111.32
        lon += dist_km * math.sin(math.radians(heading)) / (
            111.32 * math.cos(math.radians(lat)))
        ts = base_time + timedelta(seconds=i * sample_rate_seconds)

        records.append(TelemetryRecord(
            device_id=device_id, timestamp=ts,
            latitude=round(lat, 8), longitude=round(lon, 8),
            altitude=rng.uniform(210, 230),
            speed=round(speed, 2), heading=round(heading, 2),
            hdop=round(rng.uniform(*p["hdop_range"]), 1),
            pdop=round(rng.uniform(p["hdop_range"][0] + 0.5,
                                    p["hdop_range"][1] + 1.0), 1),
            satellite_count=rng.randint(*p["satellite_range"]),
            position_validity=PositionValidity.VALID,
            device_status=DeviceStatus.OK,
        ))
    return records


# ----------------------------------------------------------------------
# Pipeline orchestration
# ----------------------------------------------------------------------

def run_pipeline_real(
    trip_name: str | None = None,
    anomaly_type: str | None = None,
    output_dir: str = "data/processed",
    seed: int = 42,
) -> dict:
    """Execute the TAIS pipeline on REAL data."""

    trips = discover_trips()
    if not trips:
        print("[WARN] No real data found. Falling back to synthetic mode.")
        return run_pipeline_synthetic(
            scenario="highway", anomaly_type=anomaly_type,
            output_dir=output_dir, seed=seed,
        )

    print("=" * 70)
    print("  TAIS -- Telemetry Assessment and Integrity System")
    print("  Pipeline v2.0 (Real Data Mode)")
    print("=" * 70)

    # If no specific trip, run all trips
    trip_names = [trip_name] if trip_name else list(trips.keys())

    all_results = {}

    for tname in trip_names:
        if tname not in trips:
            print(f"\n[WARN] Trip '{tname}' not found, skipping")
            continue

        info = trips[tname]
        print(f"\n{'='*70}")
        print(f"  Trip: {info['label']} ({info['source'].upper()})")
        print(f"{'='*70}")

        # Stage 1: Load
        print(f"\n[1/4] Loading real telemetry from {info['source']}...")
        records = load_real_trip(tname, trips)
        print(f"      Loaded {len(records)} records")

        if not records:
            print("      [SKIP] No records loaded")
            continue

        duration_s = (records[-1].timestamp - records[0].timestamp).total_seconds()
        print(f"      Duration: {duration_s/60:.1f} min")
        print(f"      Start: ({records[0].latitude:.4f}, {records[0].longitude:.4f})")
        print(f"      Max speed: {max(r.speed for r in records):.1f} km/h")

        # Stage 2: Inject (optional)
        injector = AnomalyInjector(seed=seed)
        labels = []

        if anomaly_type and anomaly_type != "none":
            atype = AnomalyType(anomaly_type)
            print(f"\n[2/4] Injecting anomaly: {atype.value}...")
            records, labels = injector.inject(records, atype)
            print(f"      Injected {len(labels)} anomalous records")
        else:
            print(f"\n[2/4] No anomaly injection (clean data analysis)")

        # Stage 3: Score
        engine = TrustScoringEngine()
        print(f"\n[3/4] Running Trust-Scoring Engine...")
        assessments = engine.assess_sequence(records)
        summary = engine.sequence_summary(assessments)

        print(f"      Mean Score:  {summary['mean_score']:.1f}")
        print(f"      Min Score:   {summary['min_score']:.1f}")
        print(f"      Normal:      {summary['normal_count']}/{summary['count']}")
        print(f"      Flagged:     {summary['flagged_count']}")
        print(f"      Escalated:   {summary['escalate_count']}")

        if summary.get('rule_breakdown'):
            print(f"      Rules:       ", end="")
            rules = [f"{k}:{v}" for k, v in sorted(summary['rule_breakdown'].items())]
            print(", ".join(rules))

        # Stage 4: Export
        trip_output = os.path.join(output_dir, tname)
        os.makedirs(trip_output, exist_ok=True)
        print(f"\n[4/4] Exporting to {trip_output}/")

        csv_path = os.path.join(trip_output, "trust_assessments.csv")
        _export_assessments_csv(assessments, csv_path)
        print(f"      [OK] trust_assessments.csv ({len(assessments)} rows)")

        telemetry_csv = os.path.join(trip_output, "input_telemetry.csv")
        _export_telemetry_csv(records, telemetry_csv)
        print(f"      [OK] input_telemetry.csv")

        json_summary = {
            "pipeline_version": "2.0",
            "pipeline_run": datetime.now(timezone.utc).isoformat(),
            "trip": tname,
            "data_source": info["source"],
            "label": info["label"],
            "records": len(records),
            "duration_minutes": round(duration_s / 60, 1),
            "anomaly_injected": anomaly_type if anomaly_type else "none",
            "anomaly_labels": [
                {"index": l.record_index, "type": l.anomaly_type.value,
                 "description": l.description}
                for l in labels
            ] if labels else [],
            "summary": summary,
        }

        json_path = os.path.join(trip_output, "pipeline_summary.json")
        with open(json_path, "w") as f:
            json.dump(json_summary, f, indent=2, default=str)
        print(f"      [OK] pipeline_summary.json")

        all_results[tname] = json_summary

    # Final combined report
    print(f"\n{'='*70}")
    print(f"  PIPELINE RESULTS SUMMARY")
    print(f"{'='*70}")
    print(f"\n  {'Trip':<25} {'Source':<8} {'Records':>8} {'Mean':>6} {'Min':>6} {'Normal':>7} {'Flag':>5} {'Esc':>4}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*6} {'-'*6} {'-'*7} {'-'*5} {'-'*4}")

    total_records = 0
    for tname, result in all_results.items():
        s = result["summary"]
        src = result["data_source"]
        total_records += result["records"]
        print(f"  {result['label']:<25} {src:<8} {result['records']:>8} "
              f"{s['mean_score']:>6.1f} {s['min_score']:>6.1f} "
              f"{s['normal_count']:>7} {s['flagged_count']:>5} "
              f"{s['escalate_count']:>4}")

    print(f"\n  Total records processed: {total_records}")
    print(f"  Output: {os.path.abspath(output_dir)}")
    print("=" * 70)

    return all_results


def run_pipeline_synthetic(
    scenario: str = "highway",
    anomaly_type: str | None = None,
    duration_minutes: int = 15,
    output_dir: str = "data/processed",
    seed: int = 42,
) -> dict:
    """Execute pipeline with synthetic data (legacy/fallback mode)."""

    print("=" * 70)
    print("  TAIS -- Synthetic Data Pipeline (Fallback)")
    print("=" * 70)

    print(f"\n[1/4] Generating {scenario} telemetry ({duration_minutes} min)...")
    clean_records = generate_synthetic_route(
        scenario=scenario, duration_minutes=duration_minutes, seed=seed,
    )
    print(f"      Generated {len(clean_records)} synthetic records")

    injector = AnomalyInjector(seed=seed)
    labels = []

    if anomaly_type and anomaly_type != "none":
        atype = AnomalyType(anomaly_type)
        print(f"\n[2/4] Injecting anomaly: {atype.value}...")
        records, labels = injector.inject(clean_records, atype)
        print(f"      Injected {len(labels)} anomalous records")
    else:
        records = clean_records
        print(f"\n[2/4] No anomaly injection")

    engine = TrustScoringEngine()
    print(f"\n[3/4] Running Trust-Scoring Engine...")
    assessments = engine.assess_sequence(records)
    summary = engine.sequence_summary(assessments)

    print(f"      Mean: {summary['mean_score']:.1f}, "
          f"Normal: {summary['normal_count']}, "
          f"Flagged: {summary['flagged_count']}, "
          f"Escalate: {summary['escalate_count']}")

    os.makedirs(output_dir, exist_ok=True)
    print(f"\n[4/4] Exporting to {output_dir}/")

    csv_path = os.path.join(output_dir, "trust_assessments.csv")
    _export_assessments_csv(assessments, csv_path)

    telemetry_csv = os.path.join(output_dir, "input_telemetry.csv")
    _export_telemetry_csv(records, telemetry_csv)

    json_summary = {
        "pipeline_version": "2.0",
        "pipeline_run": datetime.now(timezone.utc).isoformat(),
        "mode": "synthetic",
        "scenario": scenario,
        "summary": summary,
    }
    json_path = os.path.join(output_dir, "pipeline_summary.json")
    with open(json_path, "w") as f:
        json.dump(json_summary, f, indent=2, default=str)

    print("=" * 70)
    return json_summary


def _export_assessments_csv(assessments: list[TrustAssessment], path: str):
    """Export trust assessments to CSV."""
    with open(path, "w", newline="", encoding="utf-8") as f:
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
    with open(path, "w", newline="", encoding="utf-8") as f:
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
        description="TAIS End-to-End Pipeline v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_pipeline.py                                    # All real trips
  python run_pipeline.py --trip trip_01_campus              # Specific trip
  python run_pipeline.py --trip trip_02_city --anomaly speed_injection
  python run_pipeline.py --mode synthetic --scenario highway
  python run_pipeline.py --list-trips                       # Show available trips
        """,
    )
    parser.add_argument(
        "--mode", choices=["real", "synthetic"], default="real",
        help="Data mode: real (default) or synthetic fallback",
    )
    parser.add_argument(
        "--trip", default=None,
        help="Specific trip to analyze (e.g., trip_01_campus, tdrive_1)",
    )
    parser.add_argument(
        "--anomaly", choices=[a.value for a in AnomalyType] + ["none"],
        default=None, help="Anomaly to inject (default: none)",
    )
    parser.add_argument(
        "--scenario", choices=["highway", "city", "degraded"],
        default="highway", help="Synthetic scenario (only for --mode synthetic)",
    )
    parser.add_argument(
        "--duration", type=int, default=15,
        help="Synthetic duration in minutes (default: 15)",
    )
    parser.add_argument(
        "--output-dir", default="data/processed",
        help="Output directory (default: data/processed)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed (default: 42)",
    )
    parser.add_argument(
        "--list-trips", action="store_true",
        help="List all available trips and exit",
    )

    args = parser.parse_args()

    if args.list_trips:
        trips = discover_trips()
        print(f"\nAvailable trips ({len(trips)}):")
        print(f"  {'Name':<25} {'Source':<8} {'Label'}")
        print(f"  {'-'*25} {'-'*8} {'-'*30}")
        for name, info in trips.items():
            print(f"  {name:<25} {info['source']:<8} {info['label']}")
        return

    if args.mode == "synthetic":
        run_pipeline_synthetic(
            scenario=args.scenario,
            anomaly_type=args.anomaly,
            duration_minutes=args.duration,
            output_dir=args.output_dir,
            seed=args.seed,
        )
    else:
        run_pipeline_real(
            trip_name=args.trip,
            anomaly_type=args.anomaly,
            output_dir=args.output_dir,
            seed=args.seed,
        )


if __name__ == "__main__":
    main()
