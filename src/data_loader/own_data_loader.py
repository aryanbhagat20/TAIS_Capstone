"""
own_data_loader.py — Load self-collected GPSLogger CSV data.
============================================================

Reads CSV files exported from the GPSLogger Android app (by mendhak)
and converts each row into a TelemetryRecord. GPSLogger's CSV format
provides most AIS-140 fields directly (lat, lon, speed, bearing, hdop,
satellites), so this loader requires minimal derivation.

Expected GPSLogger CSV columns (order may vary — matched by header name):
    lat, lon, elevation, speed, accuracy, bearing, satellites,
    provider, hdop, vdop, pdop, time

Usage:
    loader = OwnDataLoader()
    records = loader.load_trip("data/raw/own_collection/trip_01_campus.csv")
"""

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

from src.schema import TelemetryRecord, PositionValidity, DeviceStatus
from src.data_loader.field_derivation import (
    derive_speed, derive_heading, derive_acceleration,
    is_harsh_acceleration, is_harsh_braking, is_harsh_cornering,
    haversine_distance, cumulative_mileage,
)


# GPSLogger exports speed in m/s; AIS-140 uses km/h
_MS_TO_KMH = 3.6

# If GPS accuracy (metres) exceeds this, mark position as invalid
_ACCURACY_INVALID_THRESHOLD = 50.0


class OwnDataLoader:
    """
    Load GPS data collected from GPSLogger Android app.

    Each CSV file represents one trip. The loader:
      1. Parses the raw CSV rows.
      2. Maps directly-available fields (lat, lon, hdop, etc.).
      3. Derives missing fields (mileage, harsh-event flags).
      4. Assigns a device_id based on the filename (or a custom ID).
    """

    def __init__(self, device_id_prefix: str = "OWN"):
        self.device_id_prefix = device_id_prefix

    def load_trip(self, csv_path: str,
                  device_id: str | None = None) -> list[TelemetryRecord]:
        """
        Load a single trip CSV file into TelemetryRecord list.

        Args:
            csv_path: Path to GPSLogger CSV file.
            device_id: Optional device ID override. If None, derived
                       from filename (e.g., "OWN_trip_01_campus").

        Returns:
            Chronologically sorted list of TelemetryRecord instances.
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"GPS data file not found: {csv_path}")

        if device_id is None:
            device_id = f"{self.device_id_prefix}_{csv_path.stem}"

        raw_rows = self._parse_csv(csv_path)
        if not raw_rows:
            return []

        records = self._map_to_records(raw_rows, device_id)
        records = self._enrich_derived_fields(records)
        return records

    def load_all_trips(self, directory: str = "data/raw/own_collection"
                       ) -> dict[str, list[TelemetryRecord]]:
        """
        Load all CSV files from the own_collection directory.

        Returns:
            Dict mapping device_id → list of TelemetryRecord.
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {dir_path}")

        result = {}
        for csv_file in sorted(dir_path.glob("*.csv")):
            device_id = f"{self.device_id_prefix}_{csv_file.stem}"
            records = self.load_trip(str(csv_file), device_id)
            if records:
                result[device_id] = records

        return result

    def _parse_csv(self, csv_path: Path) -> list[dict]:
        """Parse CSV with header detection, returning list of row dicts."""
        rows = []
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows

    def _map_to_records(self, rows: list[dict],
                        device_id: str) -> list[TelemetryRecord]:
        """
        Map raw CSV rows to TelemetryRecord instances.

        Handles GPSLogger's column naming conventions and unit conversions.
        Skips rows with missing or unparseable coordinates.
        """
        records = []

        for row in rows:
            try:
                lat = float(row.get("lat", row.get("latitude", "")))
                lon = float(row.get("lon", row.get("longitude", "")))
            except (ValueError, TypeError):
                continue  # Skip rows with bad coordinates

            # Parse timestamp — GPSLogger uses ISO 8601 format
            timestamp = self._parse_timestamp(
                row.get("time", row.get("timestamp", ""))
            )
            if timestamp is None:
                continue

            # Speed: GPSLogger reports m/s, convert to km/h
            raw_speed = self._safe_float(row.get("speed", "0"))
            speed_kmh = raw_speed * _MS_TO_KMH if raw_speed >= 0 else 0.0

            # Direct field mappings
            record = TelemetryRecord(
                device_id=device_id,
                timestamp=timestamp,
                latitude=lat,
                longitude=lon,
                altitude=self._safe_float(row.get("elevation",
                                                   row.get("altitude", "0"))),
                speed=speed_kmh,
                heading=self._safe_float(row.get("bearing",
                                                  row.get("heading", "0"))),
                hdop=self._safe_float(row.get("hdop", "1.0"), default=1.0),
                pdop=self._safe_float(row.get("pdop", "1.0"), default=1.0),
                satellite_count=self._safe_int(
                    row.get("satellites", row.get("sat", "0"))
                ),
                position_validity=(
                    PositionValidity.VALID
                    if self._safe_float(row.get("accuracy", "5")) <
                       _ACCURACY_INVALID_THRESHOLD
                    else PositionValidity.INVALID
                ),
                device_status=DeviceStatus.OK,
            )
            records.append(record)

        # Sort by timestamp
        records.sort(key=lambda r: r.timestamp)
        return records

    def _enrich_derived_fields(self,
                               records: list[TelemetryRecord]
                               ) -> list[TelemetryRecord]:
        """
        Compute fields that GPSLogger doesn't provide:
        - mileage (cumulative odometer)
        - harsh_acceleration / harsh_braking / harsh_cornering flags
        """
        if len(records) < 2:
            return records

        # Compute per-segment distances for mileage
        distances = []
        for i in range(1, len(records)):
            d = haversine_distance(
                records[i - 1].latitude, records[i - 1].longitude,
                records[i].latitude, records[i].longitude,
            )
            distances.append(d)

        mileages = cumulative_mileage(distances)

        # Enrich each record
        for i, rec in enumerate(records):
            rec.mileage = mileages[i]

            if i == 0:
                continue

            prev = records[i - 1]
            dt = (rec.timestamp - prev.timestamp).total_seconds()
            if dt <= 0:
                continue

            accel = derive_acceleration(prev.speed, rec.speed, dt)
            rec.harsh_acceleration = is_harsh_acceleration(accel)
            rec.harsh_braking = is_harsh_braking(accel)
            rec.harsh_cornering = is_harsh_cornering(
                prev.heading, rec.heading, dt
            )

        return records

    @staticmethod
    def _parse_timestamp(ts_str: str) -> datetime | None:
        """Parse GPSLogger timestamp formats."""
        if not ts_str:
            return None

        # GPSLogger ISO 8601: "2026-09-04T10:30:45.123Z"
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(ts_str.strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    @staticmethod
    def _safe_float(val: str, default: float = 0.0) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_int(val: str, default: int = 0) -> int:
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default
