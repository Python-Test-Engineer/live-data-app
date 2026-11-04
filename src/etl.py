"""Extract, transform, validate the combined Brighton GBFS snapshot.

Input is the station-level CSV written by ``data/fetch_gbfs.py`` (one row per
station, one file per snapshot). The transform is deliberately conservative:
it keeps the source columns, adds derived analysis fields, and records every
quality issue instead of silently dropping rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from .utils import jsonable
except ImportError:  # direct script import
    from utils import jsonable

REQUIRED_COLUMNS = [
    "snapshot_utc",
    "system_id",
    "system_name",
    "station_id",
    "station_name",
    "lat",
    "lon",
    "capacity",
    "num_bikes_available",
    "num_docks_available",
    "total_docks_reported",
    "utilisation_pct",
    "is_available",
    "bikes_classic",
    "bikes_ebike",
]

NUMERIC_COLUMNS = [
    "station_feed_age_seconds",
    "station_id",
    "lat",
    "lon",
    "capacity",
    "num_bikes_available",
    "num_docks_available",
    "total_docks_reported",
    "utilisation_pct",
    "bikes_classic",
    "bikes_ebike",
    "bikes_escooter",
    "bikes_cargo",
    "bikes_other",
    "free_bikes_in_feed",
    "free_bikes_reserved",
    "free_bikes_disabled",
    "reported_age_seconds",
]

BOOL_COLUMNS = [
    "is_empty",
    "is_full",
    "is_installed",
    "is_renting",
    "is_returning",
    "is_available",
]

DATETIME_COLUMNS = [
    "snapshot_utc",
    "snapshot_local",
    "station_feed_last_updated_utc",
    "last_reported_utc",
    "last_reported_local",
]

FEED_STALE_SECONDS = 600


def extract(path: Path) -> pd.DataFrame:
    """Read the combined snapshot CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Input snapshot not found: {path}")
    frame = pd.read_csv(path)
    if frame.empty:
        raise ValueError(f"Input snapshot has no rows: {path}")
    return frame


def _coerce_bool(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series
    if series.dtype == object:
        mapped = series.astype(str).str.strip().str.lower().map(
            {"true": True, "t": True, "yes": True, "1": True,
             "false": False, "f": False, "no": False, "0": False}
        )
        return mapped.fillna(False).astype(bool)
    return series.fillna(False).astype(bool)


def transform(raw: pd.DataFrame) -> pd.DataFrame:
    """Clean types, fill labels, and add derived station fields."""
    frame = raw.copy()

    # Trim string columns without destroying the original nested JSON columns.
    for column in frame.select_dtypes(include=["object"]).columns:
        frame[column] = frame[column].map(lambda value: value.strip() if isinstance(value, str) else value)

    for column in DATETIME_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)

    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    for column in BOOL_COLUMNS:
        if column in frame.columns:
            frame[column] = _coerce_bool(frame[column])

    if "zone_name" in frame.columns:
        frame["zone_name"] = frame["zone_name"].fillna("Unzoned").replace("", "Unzoned")
    if "station_name" in frame.columns:
        frame["station_name"] = frame["station_name"].fillna("Unknown station")

    # Recompute utilisation so a bad source value cannot poison the analysis.
    safe_capacity = frame["capacity"].where(frame["capacity"] > 0)
    frame["utilisation_pct_calc"] = (frame["num_bikes_available"] / safe_capacity * 100).round(2)
    frame["utilisation_delta"] = (frame["utilisation_pct"] - frame["utilisation_pct_calc"]).abs().round(2)

    frame["capacity_delta"] = frame["total_docks_reported"] - frame["capacity"]
    frame["is_capacity_mismatch"] = frame["capacity_delta"].fillna(0).ne(0)
    frame["is_over_capacity"] = frame["num_bikes_available"] > frame["capacity"]
    frame["is_utilisation_over_100"] = frame["utilisation_pct_calc"] > 100
    frame["availability_gap"] = frame["num_bikes_available"] - frame["num_docks_available"]
    frame["age_minutes"] = (frame["station_feed_age_seconds"] / 60).round(1)

    def classify(row: pd.Series) -> str:
        if not bool(row.get("is_available", True)):
            return "offline"
        if pd.isna(row.get("capacity")) or row.get("capacity", 0) <= 0:
            return "unknown"
        if row.get("num_bikes_available", 0) == 0:
            return "empty"
        if row.get("num_docks_available", 0) == 0:
            return "full"
        utilisation = row.get("utilisation_pct_calc", 0) or 0
        if utilisation < 25:
            return "low"
        if utilisation > 75:
            return "busy"
        return "balanced"

    frame["station_status"] = frame.apply(classify, axis=1)
    return frame


def _check(name: str, status: str, count: int, detail: str) -> dict[str, Any]:
    return {"name": name, "status": status, "count": int(count), "detail": detail}


def validate(raw: pd.DataFrame, clean: pd.DataFrame) -> dict[str, Any]:
    """Run schema, integrity, and freshness checks. Never raises on bad data."""
    checks: list[dict[str, Any]] = []

    missing = [column for column in REQUIRED_COLUMNS if column not in raw.columns]
    checks.append(_check(
        "required_columns",
        "fail" if missing else "pass",
        len(missing),
        f"Missing: {', '.join(missing)}" if missing else "All required columns present",
    ))

    duplicate_ids = int(clean["station_id"].duplicated().sum()) if "station_id" in clean else 0
    checks.append(_check(
        "unique_station_ids",
        "warn" if duplicate_ids else "pass",
        duplicate_ids,
        f"{duplicate_ids} duplicate station_id rows" if duplicate_ids else "station_id is unique",
    ))

    duplicate_names = int(clean["station_name"].duplicated().sum()) if "station_name" in clean else 0
    checks.append(_check(
        "unique_station_names",
        "warn" if duplicate_names else "pass",
        duplicate_names,
        f"{duplicate_names} repeated station names" if duplicate_names else "station names are unique",
    ))

    null_cells = int(clean.isna().sum().sum())
    checks.append(_check(
        "null_cells",
        "warn" if null_cells else "pass",
        null_cells,
        f"{null_cells} null cells after transformation" if null_cells else "No null cells after transformation",
    ))

    bad_capacity = int((clean["capacity"].fillna(0) <= 0).sum()) if "capacity" in clean else 0
    checks.append(_check(
        "positive_capacity",
        "fail" if bad_capacity else "pass",
        bad_capacity,
        f"{bad_capacity} stations have capacity <= 0" if bad_capacity else "All capacities are positive",
    ))

    negative = 0
    for column in ["num_bikes_available", "num_docks_available", "bikes_classic", "bikes_ebike"]:
        if column in clean:
            negative += int((clean[column].fillna(0) < 0).sum())
    checks.append(_check(
        "non_negative_counts",
        "fail" if negative else "pass",
        negative,
        f"{negative} negative count values" if negative else "Bike and dock counts are non-negative",
    ))

    bad_coords = 0
    if {"lat", "lon"}.issubset(clean.columns):
        bad_coords = int((
            ~clean["lat"].between(49.5, 51.5)
            | ~clean["lon"].between(-1.0, 0.5)
        ).sum())
    checks.append(_check(
        "plausible_coordinates",
        "warn" if bad_coords else "pass",
        bad_coords,
        f"{bad_coords} stations outside the Brighton bounding box" if bad_coords else "Coordinates look plausible",
    ))

    mismatches = int(clean.get("is_capacity_mismatch", pd.Series(dtype=bool)).sum())
    checks.append(_check(
        "capacity_matches_reported_docks",
        "warn" if mismatches else "pass",
        mismatches,
        f"{mismatches} stations where capacity != total_docks_reported" if mismatches else "Capacity matches reported docks",
    ))

    over_100 = int(clean.get("is_utilisation_over_100", pd.Series(dtype=bool)).sum())
    checks.append(_check(
        "utilisation_within_capacity",
        "warn" if over_100 else "pass",
        over_100,
        f"{over_100} stations report more bikes than capacity" if over_100 else "Utilisation <= 100%",
    ))

    offline = int((~clean["is_available"]).sum()) if "is_available" in clean else 0
    checks.append(_check(
        "stations_available",
        "warn" if offline else "pass",
        offline,
        f"{offline} stations are not available" if offline else "All stations available",
    ))

    max_age = int(clean["station_feed_age_seconds"].max()) if "station_feed_age_seconds" in clean else 0
    checks.append(_check(
        "feed_freshness",
        "warn" if max_age > FEED_STALE_SECONDS else "pass",
        max_age,
        f"Oldest feed age is {max_age}s (threshold {FEED_STALE_SECONDS}s)",
    ))

    issues = [check for check in checks if check["status"] != "pass"]

    snapshot = clean["snapshot_utc"].dropna().max() if "snapshot_utc" in clean else None
    report = {
        "source_rows": int(len(raw)),
        "clean_rows": int(len(clean)),
        "columns": int(len(clean.columns)),
        "snapshot_utc": snapshot.isoformat() if pd.notna(snapshot) else None,
        "system": str(clean["system_name"].dropna().iloc[0]) if "system_name" in clean and not clean["system_name"].dropna().empty else None,
        "feed_age_seconds": max_age,
        "null_cells": null_cells,
        "duplicate_station_ids": duplicate_ids,
        "checks": checks,
        "issues": issues,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    return jsonable(report)


def run_etl(path: str | Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extract + transform + validate one snapshot."""
    source = Path(path).expanduser().resolve()
    raw = extract(source)
    missing = [column for column in REQUIRED_COLUMNS if column not in raw.columns]
    if missing:
        # Still produce a report explaining the failure.
        report = {
            "source_rows": int(len(raw)),
            "clean_rows": 0,
            "columns": int(len(raw.columns)),
            "checks": [_check("required_columns", "fail", len(missing), f"Missing: {', '.join(missing)}")],
            "issues": [_check("required_columns", "fail", len(missing), f"Missing: {', '.join(missing)}")],
            "generated_utc": datetime.now(timezone.utc).isoformat(),
        }
        raise ValueError(f"Input is missing required columns: {', '.join(missing)}\n{report}")

    clean = transform(raw)
    report = validate(raw, clean)
    report["source"] = str(source)
    report["source_file"] = source.name
    return clean, report
