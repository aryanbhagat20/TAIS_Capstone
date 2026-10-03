"""
evaluate.py -- TAIS Evaluation Module
=======================================

Comprehensive evaluation of the Trust-Scoring Engine against known
anomaly injections. Computes standard classification metrics:

    - Confusion Matrix (TP, FP, TN, FN)
    - Precision, Recall, F1-Score
    - False Positive Rate (FPR)
    - Detection Latency (how fast anomalies are caught)
    - ROC Curve data (varying threshold)
    - Per-anomaly-type breakdown
    - Per-trip breakdown

Usage:
    python evaluate.py                    # Full evaluation
    python evaluate.py --trip trip_01_campus
    python evaluate.py --anomaly speed_injection
    python evaluate.py --output-dir data/evaluation

Output:
    data/evaluation/
        evaluation_summary.json
        confusion_matrix.csv
        per_anomaly_results.csv
        per_trip_results.csv
        roc_curve_data.csv
        detection_latency.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(__file__))

from src.schema import TelemetryRecord, TrustAssessment, Action
from src.injector.anomaly_injector import AnomalyInjector, AnomalyType
from src.engine.trust_scoring_engine import TrustScoringEngine, ScoringConfig
from src.data_loader.own_data_loader import OwnDataLoader
from src.data_loader.tdrive_loader import TDriveLoader


# ======================================================================
# Data structures
# ======================================================================

@dataclass
class ConfusionCounts:
    """Binary classification confusion matrix counts."""
    tp: int = 0  # Anomaly injected AND engine flagged/escalated
    fp: int = 0  # NO anomaly BUT engine flagged/escalated
    tn: int = 0  # NO anomaly AND engine said Normal
    fn: int = 0  # Anomaly injected BUT engine said Normal

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1_score(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.total if self.total > 0 else 0.0

    @property
    def fpr(self) -> float:
        """False Positive Rate = FP / (FP + TN)"""
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) > 0 else 0.0

    @property
    def tpr(self) -> float:
        """True Positive Rate = TP / (TP + FN) = Recall"""
        return self.recall

    def to_dict(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "accuracy": round(self.accuracy, 4),
            "fpr": round(self.fpr, 4),
            "tpr": round(self.tpr, 4),
        }


@dataclass
class DetectionLatency:
    """Measures how quickly anomalies are detected."""
    anomaly_start_index: int = 0
    first_detection_index: int | None = None
    records_to_detect: int | None = None
    detected: bool = False


# ======================================================================
# Trip discovery (reused from run_pipeline.py)
# ======================================================================

OWN_DATA_DIR = Path("data/raw/own_collection")
TDRIVE_DIR = Path("data/raw/tdrive")


def discover_trips() -> dict:
    trips = {}
    if OWN_DATA_DIR.exists():
        for csv_file in sorted(OWN_DATA_DIR.glob("trip_*.csv")):
            name = csv_file.stem
            trips[name] = {"source": "own", "label": name, "path": str(csv_file)}
    if TDRIVE_DIR.exists():
        for txt_file in sorted(TDRIVE_DIR.glob("*.txt")):
            taxi_id = txt_file.stem
            name = f"tdrive_{taxi_id}"
            trips[name] = {"source": "tdrive", "label": f"Taxi #{taxi_id}",
                           "path": str(txt_file)}
    return trips


def load_trip(trip_name: str, trips: dict) -> list[TelemetryRecord]:
    info = trips[trip_name]
    if info["source"] == "own":
        loader = OwnDataLoader()
        device_id = f"ARYAN_{trip_name.split('_')[2].upper()}"
        return loader.load_trip(info["path"], device_id=device_id)
    else:
        loader = TDriveLoader(str(TDRIVE_DIR))
        taxi_id = int(trip_name.replace("tdrive_", ""))
        return loader.load_taxi(taxi_id=taxi_id)


# ======================================================================
# Core evaluation logic
# ======================================================================

def evaluate_single(
    records: list[TelemetryRecord],
    anomaly_type: AnomalyType,
    threshold: float = 70.0,
    seed: int = 42,
) -> tuple[ConfusionCounts, DetectionLatency, list[dict]]:
    """
    Evaluate engine detection for one trip + one anomaly type.

    Args:
        records: Clean telemetry records
        anomaly_type: Type of anomaly to inject
        threshold: Score threshold below which = "detected" (default: 70 = Flagged)
        seed: Random seed for injection

    Returns:
        (confusion_counts, detection_latency, per_record_details)
    """
    injector = AnomalyInjector(seed=seed)
    engine = TrustScoringEngine()

    # Inject anomaly
    injected_records, labels = injector.inject(records, anomaly_type)
    injected_indices = {l.record_index for l in labels}

    # Score
    assessments = engine.assess_sequence(injected_records)

    # Classify each record
    counts = ConfusionCounts()
    latency = DetectionLatency()
    per_record = []

    if labels:
        latency.anomaly_start_index = labels[0].record_index

    for i, a in enumerate(assessments):
        is_anomaly = i in injected_indices
        is_detected = a.trust_score < threshold  # Below threshold = detected

        if is_anomaly and is_detected:
            counts.tp += 1
            if not latency.detected:
                latency.detected = True
                latency.first_detection_index = i
                latency.records_to_detect = i - latency.anomaly_start_index
        elif is_anomaly and not is_detected:
            counts.fn += 1
        elif not is_anomaly and is_detected:
            counts.fp += 1
        else:
            counts.tn += 1

        per_record.append({
            "index": i,
            "is_anomaly": is_anomaly,
            "trust_score": a.trust_score,
            "action": a.action.value,
            "is_detected": is_detected,
            "classification": (
                "TP" if is_anomaly and is_detected else
                "FN" if is_anomaly and not is_detected else
                "FP" if not is_anomaly and is_detected else "TN"
            ),
        })

    return counts, latency, per_record


def evaluate_roc(
    records: list[TelemetryRecord],
    anomaly_type: AnomalyType,
    seed: int = 42,
    thresholds: list[float] | None = None,
) -> list[dict]:
    """
    Generate ROC curve data by varying the detection threshold.

    Returns list of {threshold, fpr, tpr, precision, recall, f1}.
    """
    if thresholds is None:
        thresholds = list(range(0, 105, 5))  # 0, 5, 10, ..., 100

    roc_data = []
    for thresh in thresholds:
        counts, _, _ = evaluate_single(records, anomaly_type,
                                        threshold=thresh, seed=seed)
        roc_data.append({
            "threshold": thresh,
            "fpr": round(counts.fpr, 4),
            "tpr": round(counts.tpr, 4),
            "precision": round(counts.precision, 4),
            "recall": round(counts.recall, 4),
            "f1_score": round(counts.f1_score, 4),
        })

    return roc_data


# ======================================================================
# Full evaluation pipeline
# ======================================================================

def run_evaluation(
    trip_filter: str | None = None,
    anomaly_filter: str | None = None,
    output_dir: str = "data/evaluation",
    seed: int = 42,
) -> dict:
    """Run full evaluation across all trips and anomaly types."""

    trips = discover_trips()
    if not trips:
        print("[ERROR] No trip data found!")
        return {}

    anomaly_types = list(AnomalyType)
    if anomaly_filter:
        anomaly_types = [AnomalyType(anomaly_filter)]

    trip_names = list(trips.keys())
    if trip_filter:
        trip_names = [trip_filter]

    print("=" * 70)
    print("  TAIS -- Evaluation Module")
    print("  Precision / Recall / F1 / ROC Analysis")
    print("=" * 70)
    print(f"\n  Trips: {len(trip_names)}")
    print(f"  Anomaly types: {len(anomaly_types)}")
    print(f"  Total experiments: {len(trip_names) * len(anomaly_types)}")
    print()

    # Results storage
    all_per_anomaly = {}     # anomaly_type -> aggregated ConfusionCounts
    all_per_trip = {}        # trip_name -> aggregated ConfusionCounts
    all_details = []         # per-experiment details
    all_latencies = []       # detection latency records
    all_roc = {}             # anomaly_type -> ROC data
    grand_total = ConfusionCounts()

    # Also evaluate clean data (FPR baseline)
    clean_fp_total = 0
    clean_total = 0

    for trip_name in trip_names:
        if trip_name not in trips:
            print(f"  [SKIP] {trip_name} not found")
            continue

        print(f"  Loading {trip_name}...", end=" ", flush=True)
        records = load_trip(trip_name, trips)
        if len(records) < 10:
            print(f"too few records ({len(records)}), skipping")
            continue
        print(f"{len(records)} records")

        # Clean data FPR baseline
        engine = TrustScoringEngine()
        clean_assessments = engine.assess_sequence(records)
        clean_fp = sum(1 for a in clean_assessments if a.trust_score < 70)
        clean_fp_total += clean_fp
        clean_total += len(clean_assessments)

        if trip_name not in all_per_trip:
            all_per_trip[trip_name] = ConfusionCounts()

        for atype in anomaly_types:
            counts, latency, per_record = evaluate_single(
                records, atype, threshold=70.0, seed=seed
            )

            # Aggregate by anomaly type
            if atype.value not in all_per_anomaly:
                all_per_anomaly[atype.value] = ConfusionCounts()
            agg = all_per_anomaly[atype.value]
            agg.tp += counts.tp
            agg.fp += counts.fp
            agg.tn += counts.tn
            agg.fn += counts.fn

            # Aggregate by trip
            trip_agg = all_per_trip[trip_name]
            trip_agg.tp += counts.tp
            trip_agg.fp += counts.fp
            trip_agg.tn += counts.tn
            trip_agg.fn += counts.fn

            # Grand total
            grand_total.tp += counts.tp
            grand_total.fp += counts.fp
            grand_total.tn += counts.tn
            grand_total.fn += counts.fn

            # Detail record
            all_details.append({
                "trip": trip_name,
                "anomaly_type": atype.value,
                "tp": counts.tp, "fp": counts.fp,
                "tn": counts.tn, "fn": counts.fn,
                "precision": round(counts.precision, 4),
                "recall": round(counts.recall, 4),
                "f1_score": round(counts.f1_score, 4),
                "fpr": round(counts.fpr, 4),
                "detected": latency.detected,
                "latency_records": latency.records_to_detect,
            })

            all_latencies.append({
                "trip": trip_name,
                "anomaly_type": atype.value,
                "anomaly_start": latency.anomaly_start_index,
                "first_detection": latency.first_detection_index,
                "records_to_detect": latency.records_to_detect,
                "detected": latency.detected,
            })

            status = "DETECTED" if latency.detected else "MISSED"
            print(f"    {atype.value:20s} P={counts.precision:.2f} "
                  f"R={counts.recall:.2f} F1={counts.f1_score:.2f} "
                  f"[{status}]")

        # ROC for first trip only (representative)
        if trip_name == trip_names[0]:
            for atype in anomaly_types:
                roc = evaluate_roc(records, atype, seed=seed)
                all_roc[atype.value] = roc

    # ---- Export results ----
    os.makedirs(output_dir, exist_ok=True)

    # 1. Per-anomaly results CSV
    anomaly_csv = os.path.join(output_dir, "per_anomaly_results.csv")
    with open(anomaly_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "anomaly_type", "tp", "fp", "tn", "fn",
            "precision", "recall", "f1_score", "fpr", "tpr", "accuracy",
        ])
        writer.writeheader()
        for atype_val, counts in sorted(all_per_anomaly.items()):
            row = {"anomaly_type": atype_val}
            row.update(counts.to_dict())
            writer.writerow(row)

    # 2. Per-trip results CSV
    trip_csv = os.path.join(output_dir, "per_trip_results.csv")
    with open(trip_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "trip", "tp", "fp", "tn", "fn",
            "precision", "recall", "f1_score", "fpr", "tpr", "accuracy",
        ])
        writer.writeheader()
        for trip_name, counts in sorted(all_per_trip.items()):
            row = {"trip": trip_name}
            row.update(counts.to_dict())
            writer.writerow(row)

    # 3. Detailed per-experiment CSV
    detail_csv = os.path.join(output_dir, "experiment_details.csv")
    with open(detail_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "trip", "anomaly_type", "tp", "fp", "tn", "fn",
            "precision", "recall", "f1_score", "fpr",
            "detected", "latency_records",
        ])
        writer.writeheader()
        writer.writerows(all_details)

    # 4. Detection latency CSV
    latency_csv = os.path.join(output_dir, "detection_latency.csv")
    with open(latency_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "trip", "anomaly_type", "anomaly_start",
            "first_detection", "records_to_detect", "detected",
        ])
        writer.writeheader()
        writer.writerows(all_latencies)

    # 5. ROC curve data CSV
    roc_csv = os.path.join(output_dir, "roc_curve_data.csv")
    with open(roc_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "anomaly_type", "threshold", "fpr", "tpr",
            "precision", "recall", "f1_score",
        ])
        writer.writeheader()
        for atype_val, roc_data in all_roc.items():
            for point in roc_data:
                row = {"anomaly_type": atype_val}
                row.update(point)
                writer.writerow(row)

    # 6. Summary JSON
    summary = {
        "evaluation_run": datetime.now(timezone.utc).isoformat(),
        "total_trips": len(trip_names),
        "total_anomaly_types": len(anomaly_types),
        "total_experiments": len(all_details),
        "threshold": 70.0,
        "grand_total": grand_total.to_dict(),
        "clean_data_fpr": round(clean_fp_total / clean_total, 4) if clean_total > 0 else 0,
        "clean_data_fp_records": clean_fp_total,
        "clean_data_total_records": clean_total,
        "per_anomaly": {k: v.to_dict() for k, v in sorted(all_per_anomaly.items())},
        "per_trip": {k: v.to_dict() for k, v in sorted(all_per_trip.items())},
        "detection_rates": {
            atype: sum(1 for d in all_latencies
                       if d["anomaly_type"] == atype and d["detected"])
            / max(1, sum(1 for d in all_latencies if d["anomaly_type"] == atype))
            for atype in [a.value for a in anomaly_types]
        },
        "avg_detection_latency": {
            atype: round(
                sum(d["records_to_detect"] for d in all_latencies
                    if d["anomaly_type"] == atype and d["detected"]
                    and d["records_to_detect"] is not None)
                / max(1, sum(1 for d in all_latencies
                             if d["anomaly_type"] == atype and d["detected"])),
                1,
            )
            for atype in [a.value for a in anomaly_types]
        },
    }

    json_path = os.path.join(output_dir, "evaluation_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    # ---- Print results ----
    print(f"\n{'='*70}")
    print(f"  EVALUATION RESULTS")
    print(f"{'='*70}")

    print(f"\n  OVERALL (threshold = 70.0):")
    print(f"    Precision:  {grand_total.precision:.4f}")
    print(f"    Recall:     {grand_total.recall:.4f}")
    print(f"    F1-Score:   {grand_total.f1_score:.4f}")
    print(f"    Accuracy:   {grand_total.accuracy:.4f}")
    print(f"    FPR:        {grand_total.fpr:.4f}")
    print(f"    Clean FPR:  {summary['clean_data_fpr']:.4f} "
          f"({clean_fp_total}/{clean_total} records)")

    print(f"\n  PER ANOMALY TYPE:")
    print(f"  {'Type':<22} {'Prec':>6} {'Rec':>6} {'F1':>6} {'Det%':>6} {'Latency':>8}")
    print(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*8}")
    for atype_val, counts in sorted(all_per_anomaly.items()):
        det_rate = summary["detection_rates"].get(atype_val, 0)
        avg_lat = summary["avg_detection_latency"].get(atype_val, "-")
        print(f"  {atype_val:<22} {counts.precision:>6.3f} {counts.recall:>6.3f} "
              f"{counts.f1_score:>6.3f} {det_rate:>5.0%} {avg_lat:>8}")

    print(f"\n  Output: {os.path.abspath(output_dir)}")
    print(f"  Files: evaluation_summary.json, per_anomaly_results.csv,")
    print(f"         per_trip_results.csv, roc_curve_data.csv,")
    print(f"         detection_latency.csv, experiment_details.csv")
    print("=" * 70)

    return summary


# ======================================================================
# CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="TAIS Evaluation Module - Precision/Recall/F1/ROC",
    )
    parser.add_argument("--trip", default=None, help="Specific trip to evaluate")
    parser.add_argument("--anomaly", default=None,
                        choices=[a.value for a in AnomalyType],
                        help="Specific anomaly type")
    parser.add_argument("--output-dir", default="data/evaluation",
                        help="Output directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()
    run_evaluation(
        trip_filter=args.trip,
        anomaly_filter=args.anomaly,
        output_dir=args.output_dir,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
