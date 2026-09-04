"""
tdrive_loader.py — Load T-Drive taxi trajectory dataset.
=========================================================

T-Drive is a public GPS trajectory dataset from Microsoft Research
containing traces of 10,357 taxis in Beijing over one week (Feb 2008).
Each taxi has a separate text file with format:
    taxi_id, datetime, longitude, latitude

Since T-Drive only provides 4 fields, this loader derives the remaining
TelemetryRecord fields:
    - speed: Haversine distance / time delta
    - heading: Bearing between consecutive points
    - hdop/pdop/satellite_count: Sampled from realistic distributions
    - mileage: Cumulative distance

Download T-Drive from:
    https://www.kaggle.com/datasets/arashnic/t-drive-taxi-trajectories

Place extracted files in: data/raw/tdrive/

Usage:
    loader = TDriveLoader()
    records = loader.load_taxi("data/raw/tdrive/1.txt")
    sample = loader.load_sample(n_taxis=10)
"""

import csv
import os
import random
from datetime import datetime, timezone
from pathlib import Path

from src.schema import TelemetryRecord, PositionValidity, DeviceStatus
from src.data_loader.field_derivation import (
    haversine_distance, derive_speed, derive_heading,
    derive_acceleration, is_harsh_acceleration, is_harsh_braking,
    is_harsh_cornering, cumulative_mileage,
)


# Realistic HDOP distribution for urban GPS (empirical approximation)
# Lower HDOP = better accuracy. Urban Beijing ≈ similar to urban India.
_HDOP_RANGE = (0.8, 3.5)
_SAT_COUNT_RANGE = (5, 14)


class TDriveLoader:
    """
    Load T-Drive taxi GPS data and convert to TelemetryRecord streams.

    T-Drive file format (no header, comma-separated):
        taxi_id, datetime_str, longitude, latitude

    Example line:
        1,2008-02-02 15:36:08,116.51172,39.92123
    """

    def __init__(self, data_dir: str = "data/raw/tdrive",
                 device_id_prefix: str = "TDRIVE"):
        self.data_dir = Path(data_dir)
        self.device_id_prefix = device_id_prefix

    def load_taxi(self, file_path: str | None = None,
                  taxi_id: int | None = None) -> list[TelemetryRecord]:
        """
        Load trajectory data for a single taxi.

        Args:
            file_path: Direct path to a taxi file. If None, uses taxi_id.
            taxi_id: Taxi number (e.g., 1 → "data/raw/tdrive/1.txt").

        Returns:
            Chronologically sorted list of TelemetryRecord instances.
        """
        if file_path is None:
            if taxi_id is None:
                raise ValueError("Provide either file_path or taxi_id")
            file_path = str(self.data_dir / f"{taxi_id}.txt")

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"T-Drive file not found: {path}")

        raw_rows = self._parse_tdrive_file(path)
        if not raw_rows:
            return []

        device_id = f"{self.device_id_prefix}_{raw_rows[0]['taxi_id']}"
        records = self._map_to_records(raw_rows, device_id)
        records = self._enrich_derived_fields(records)
        return records

    def load_sample(self, n_taxis: int = 10,
                    random_seed: int = 42) -> dict[str, list[TelemetryRecord]]:
        """
        Load a random sample of n taxis from the T-Drive directory.

        Returns:
            Dict mapping device_id → list of TelemetryRecord.
        """
        if not self.data_dir.exists():
            raise FileNotFoundError(
                f"T-Drive directory not found: {self.data_dir}\n"
                f"Download from: https://www.kaggle.com/datasets/"
                f"arashnic/t-drive-taxi-trajectories"
            )

        all_files = sorted(self.data_dir.glob("*.txt"))
        if not all_files:
            raise FileNotFoundError(
                f"No .txt files found in {self.data_dir}"
            )

        rng = random.Random(random_seed)
        selected = rng.sample(all_files, min(n_taxis, len(all_files)))

        result = {}
        for f in selected:
            try:
                records = self.load_taxi(file_path=str(f))
                if records:
                    result[records[0].device_id] = records
            except Exception:
                continue  # Skip corrupt files

        return result

    def list_available_taxis(self) -> list[int]:
        """List all taxi IDs available in the data directory."""
        if not self.data_dir.exists():
            return []
        taxi_ids = []
        for f in self.data_dir.glob("*.txt"):
            try:
                taxi_ids.append(int(f.stem))
            except ValueError:
                continue
        return sorted(taxi_ids)

    def _parse_tdrive_file(self, path: Path) -> list[dict]:
        """
        Parse a T-Drive text file.

        Format: taxi_id,datetime,longitude,latitude
        """
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) < 4:
                    continue
                try:
                    rows.append({
                        "taxi_id": parts[0].strip(),
                        "datetime": parts[1].strip(),
                        "longitude": float(parts[2].strip()),
                        "latitude": float(parts[3].strip()),
                    })
                except (ValueError, IndexError):
                    continue
        return rows

    def _map_to_records(self, rows: list[dict],
                        device_id: str) -> list[TelemetryRecord]:
        """
        Map T-Drive rows to TelemetryRecord with realistic signal defaults.

        Speed and heading are derived from consecutive points in the
        enrichment step. Here we set initial values and generate
        realistic HDOP / satellite count values.
        """
        records = []
        rng = random.Random(hash(device_id))  # Reproducible per taxi

        for row in rows:
            timestamp = self._parse_timestamp(row["datetime"])
            if timestamp is None:
                continue

            lat = row["latitude"]
            lon = row["longitude"]

            # Sanity check: skip clearly invalid coordinates
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue

            # Generate realistic signal quality values
            hdop = round(rng.uniform(*_HDOP_RANGE), 1)
            pdop = round(hdop * rng.uniform(1.1, 1.5), 1)
            sat_count = rng.randint(*_SAT_COUNT_RANGE)

            record = TelemetryRecord(
                device_id=device_id,
                timestamp=timestamp,
                latitude=lat,
                longitude=lon,
                altitude=0.0,       # T-Drive doesn't include altitude
                speed=0.0,          # Derived in enrichment step
                heading=0.0,        # Derived in enrichment step
                hdop=hdop,
                pdop=pdop,
                satellite_count=sat_count,
                position_validity=PositionValidity.VALID,
                device_status=DeviceStatus.OK,
            )
            records.append(record)

        records.sort(key=lambda r: r.timestamp)
        return records

    def _enrich_derived_fields(self,
                               records: list[TelemetryRecord]
                               ) -> list[TelemetryRecord]:
        """
        Derive speed, heading, mileage, and harsh-event flags from
        consecutive GPS points.
        """
        if len(records) < 2:
            return records

        # Derive speed and heading from consecutive points
        for i in range(1, len(records)):
            prev = records[i - 1]
            curr = records[i]

            dt = (curr.timestamp - prev.timestamp).total_seconds()

            curr.speed = derive_speed(
                prev.latitude, prev.longitude, prev.timestamp,
                curr.latitude, curr.longitude, curr.timestamp,
            )
            curr.heading = derive_heading(
                prev.latitude, prev.longitude,
                curr.latitude, curr.longitude,
            )

            # Cap unrealistic speeds (GPS noise can cause spikes)
            if curr.speed > 200:  # > 200 km/h almost certainly GPS noise
                curr.speed = prev.speed  # Carry forward previous speed

            # Harsh-event flags
            if dt > 0:
                accel = derive_acceleration(prev.speed, curr.speed, dt)
                curr.harsh_acceleration = is_harsh_acceleration(accel)
                curr.harsh_braking = is_harsh_braking(accel)
                curr.harsh_cornering = is_harsh_cornering(
                    prev.heading, curr.heading, dt
                )

        # Cumulative mileage
        distances = []
        for i in range(1, len(records)):
            d = haversine_distance(
                records[i - 1].latitude, records[i - 1].longitude,
                records[i].latitude, records[i].longitude,
            )
            distances.append(d)

        mileages = cumulative_mileage(distances)
        for i, rec in enumerate(records):
            rec.mileage = mileages[i]

        return records

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime | None:
        """Parse T-Drive timestamp format: '2008-02-02 15:36:08'."""
        try:
            dt = datetime.strptime(ts_str.strip(), "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
