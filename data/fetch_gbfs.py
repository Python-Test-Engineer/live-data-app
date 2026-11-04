#!/usr/bin/env python3
"""Fetch the Brighton Beryl GBFS feeds and build the DINA starter datasets.

Outputs (all in this folder):
  - one CSV per GBFS feed
  - station_status_vehicle_types.csv (long form of the nested vehicle counts)
  - system_pricing_plan_rates.csv and system_pricing_plan_fees.csv
  - data.csv: one combined, station-level snapshot for analysis

Run from the repository root:
    uv run data/fetch_gbfs.py

The script deliberately uses only requests + pandas so it is easy to explain
live. It has no dependency on the rest of the application.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

GBFS_ROOT = "https://gbfs.beryl.cc/v2_2/Brighton/gbfs.json"
TIMEOUT_SECONDS = 30
USER_AGENT = "DINA-demo/0.1 (Brighton Data Intelligence Network)"


# ---------------------------------------------------------------------------
# Fetching helpers
# ---------------------------------------------------------------------------

def fetch_json(url: str) -> dict[str, Any]:
    """Fetch one URL and return decoded JSON, failing loudly on HTTP errors."""
    response = requests.get(
        url,
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


def iso_utc(epoch: int | float | None) -> str:
    if epoch is None or pd.isna(epoch):
        return ""
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def iso_local(epoch: int | float | None, tz: ZoneInfo) -> str:
    if epoch is None or pd.isna(epoch):
        return ""
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).astimezone(tz).isoformat()


def write_csv(rows: list[dict[str, Any]], path: Path) -> int:
    """Write a list of dictionaries as a CSV. Returns the row count."""
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False, encoding="utf-8")
    return len(frame)


def dump_nested(value: Any) -> str:
    """Keep nested GBFS structures available as compact JSON in a CSV cell."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def flatten_rental_uris(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        f"rental_uri_{platform}": str(uri)
        for platform, uri in value.items()
        if isinstance(uri, str)
    }


# ---------------------------------------------------------------------------
# Feed-specific flattening
# ---------------------------------------------------------------------------

def station_information_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for station in payload["data"]["stations"]:
        row = {
            "station_id": str(station.get("station_id", "")),
            "name": station.get("name", ""),
            "lat": station.get("lat"),
            "lon": station.get("lon"),
            "capacity": station.get("capacity"),
        }
        row.update(flatten_rental_uris(station.get("rental_uris")))
        rows.append(row)
    return rows


def station_status_rows(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    vehicle_rows: list[dict[str, Any]] = []
    for station in payload["data"]["stations"]:
        station_id = str(station.get("station_id", ""))
        vehicle_types = station.get("vehicle_types_available") or []
        rows.append(
            {
                "station_id": station_id,
                "num_bikes_available": station.get("num_bikes_available"),
                "num_docks_available": station.get("num_docks_available"),
                "is_installed": station.get("is_installed"),
                "is_renting": station.get("is_renting"),
                "is_returning": station.get("is_returning"),
                "last_reported": station.get("last_reported"),
                "vehicle_types_available": dump_nested(vehicle_types),
            }
        )
        for item in vehicle_types:
            vehicle_rows.append(
                {
                    "station_id": station_id,
                    "vehicle_type_id": item.get("vehicle_type_id", ""),
                    "count": item.get("count"),
                    "last_reported": station.get("last_reported"),
                }
            )
    return rows, vehicle_rows


def free_bike_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bike in payload["data"]["bikes"]:
        rows.append(
            {
                "bike_id": bike.get("bike_id", ""),
                "station_id": str(bike.get("station_id", "")),
                "vehicle_type_id": bike.get("vehicle_type_id", ""),
                "lat": bike.get("lat"),
                "lon": bike.get("lon"),
                "is_reserved": bike.get("is_reserved"),
                "is_disabled": bike.get("is_disabled"),
                "current_range_meters": bike.get("current_range_meters"),
            }
        )
    return rows


def system_information_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload["data"]
    row = {
        key: value
        for key, value in data.items()
        if not isinstance(value, (dict, list))
    }
    rental_apps = data.get("rental_apps") or {}
    for platform in ("android", "ios"):
        app = rental_apps.get(platform) or {}
        row[f"rental_app_{platform}_store_uri"] = app.get("store_uri", "")
        row[f"rental_app_{platform}_discovery_uri"] = app.get("discovery_uri", "")
    return [row]


def pricing_plan_rows(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    plan_rows: list[dict[str, Any]] = []
    rate_rows: list[dict[str, Any]] = []
    fee_rows: list[dict[str, Any]] = []
    for plan in payload["data"]["plans"]:
        plan_id = plan.get("plan_id", "")
        plan_name = plan.get("name", "")
        plan_rows.append(
            {
                "plan_id": plan_id,
                "name": plan_name,
                "type": plan.get("type", ""),
                "description": plan.get("description", ""),
                "currency": plan.get("currency", ""),
                "price": plan.get("price"),
                "is_taxable": plan.get("is_taxable"),
                "validity_interval": plan.get("validity_interval"),
                "per_min_pricing": dump_nested(plan.get("per_min_pricing") or []),
                "additional_fees": dump_nested(plan.get("additional_fees") or []),
            }
        )
        for rate in plan.get("per_min_pricing") or []:
            rate_rows.append(
                {
                    "plan_id": plan_id,
                    "plan_name": plan_name,
                    "plan_type": plan.get("type", ""),
                    "vehicle_type_id": rate.get("vehicle_type_id", ""),
                    "start": rate.get("start"),
                    "rate": rate.get("rate"),
                    "interval": rate.get("interval"),
                }
            )
        for fee in plan.get("additional_fees") or []:
            fee_rows.append(
                {
                    "plan_id": plan_id,
                    "plan_name": plan_name,
                    "plan_type": plan.get("type", ""),
                    "vehicle_type_id": fee.get("vehicle_type_id", ""),
                    "fee": fee.get("fee", ""),
                    "price": fee.get("price"),
                }
            )
    return plan_rows, rate_rows, fee_rows


# ---------------------------------------------------------------------------
# Geofence lookup (small pure-Python point-in-polygon implementation)
# ---------------------------------------------------------------------------

def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        crosses = (yi > y) != (yj > y)
        if crosses and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def point_in_polygon(x: float, y: float, polygon: list[list[list[float]]]) -> bool:
    if not polygon or not point_in_ring(x, y, polygon[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in polygon[1:])


def point_in_geometry(x: float, y: float, geometry: dict[str, Any]) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        return point_in_polygon(x, y, coordinates)
    if geometry_type == "MultiPolygon":
        return any(point_in_polygon(x, y, polygon) for polygon in coordinates)
    return False


def ring_area_sq_m(ring: list[list[float]]) -> float:
    if len(ring) < 3:
        return 0.0
    mean_lat = sum(point[1] for point in ring) / len(ring)
    x_scale = 111_320.0 * math.cos(math.radians(mean_lat))
    y_scale = 110_540.0
    area = 0.0
    for current, following in zip(ring, ring[1:] + ring[:1]):
        x1, y1 = current[0] * x_scale, current[1] * y_scale
        x2, y2 = following[0] * x_scale, following[1] * y_scale
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def geometry_area_sq_m(geometry: dict[str, Any]) -> float:
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        return ring_area_sq_m(coordinates[0]) if coordinates else 0.0
    if geometry.get("type") == "MultiPolygon":
        return sum(ring_area_sq_m(polygon[0]) for polygon in coordinates if polygon)
    return 0.0


def zone_lookup(
    features: list[dict[str, Any]],
) -> tuple[list[tuple[str, dict[str, Any], float]], list[dict[str, Any]]]:
    """Return (name, geometry, area) sorted smallest-first, and CSV rows."""
    zones: list[tuple[str, dict[str, Any], float]] = []
    rows: list[dict[str, Any]] = []
    for feature in features:
        geometry = feature.get("geometry") or {}
        name = (feature.get("properties") or {}).get("name", "")
        area = geometry_area_sq_m(geometry)
        zones.append((name, geometry, area))
        rows.append(
            {
                "zone_name": name,
                "geometry_type": geometry.get("type", ""),
                "area_sq_km": round(area / 1_000_000.0, 6),
                "geometry_json": dump_nested(geometry),
                "properties_json": dump_nested(feature.get("properties") or {}),
            }
        )
    zones.sort(key=lambda item: item[2])
    return zones, rows


def assign_zones(
    lat: float | None,
    lon: float | None,
    zones: list[tuple[str, dict[str, Any], float]],
) -> tuple[str, str]:
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return "", ""
    x, y = float(lon), float(lat)
    matches = [
        name
        for name, geometry, _area in zones
        if point_in_geometry(x, y, geometry)
    ]
    if not matches:
        return "", ""
    return matches[0], ";".join(matches)


# ---------------------------------------------------------------------------
# Combined station snapshot
# ---------------------------------------------------------------------------

def vehicle_count_columns(
    vehicle_rows: list[dict[str, Any]],
    vehicle_types: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Classify station vehicle counts into stable analysis columns."""
    type_meta = {item.get("vehicle_type_id"): item for item in vehicle_types}
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "bikes_classic": 0,
            "bikes_ebike": 0,
            "bikes_escooter": 0,
            "bikes_cargo": 0,
            "bikes_other": 0,
        }
    )
    for row in vehicle_rows:
        station_id = row["station_id"]
        type_id = row["vehicle_type_id"]
        count = int(row.get("count") or 0)
        meta = type_meta.get(type_id, {})
        form = (meta.get("form_factor") or "").lower()
        propulsion = (meta.get("propulsion_type") or "").lower()
        if form == "cargo_bicycle":
            column = "bikes_cargo"
        elif form == "scooter" or type_id == "scooter":
            column = "bikes_escooter"
        elif propulsion == "electric_assist" or type_id in {"bbe", "ebike"}:
            column = "bikes_ebike"
        elif form == "bicycle" or propulsion == "human" or type_id in {"beryl_bike", "bike"}:
            column = "bikes_classic"
        else:
            column = "bikes_other"
        counts[station_id][column] += count
    return counts


def build_combined(
    *,
    snapshot: datetime,
    system_info: dict[str, Any],
    station_info_rows: list[dict[str, Any]],
    station_status_rows_: list[dict[str, Any]],
    station_vehicle_rows: list[dict[str, Any]],
    free_bike_rows_: list[dict[str, Any]],
    vehicle_types: list[dict[str, Any]],
    zones: list[tuple[str, dict[str, Any], float]],
    station_feed_last_updated: int | float | None,
    tz: ZoneInfo,
) -> pd.DataFrame:
    station_info = pd.DataFrame(station_info_rows)
    station_status = pd.DataFrame(station_status_rows_)

    if station_info.empty:
        station_info = pd.DataFrame(columns=["station_id", "name", "lat", "lon", "capacity"])
    if station_status.empty:
        station_status = pd.DataFrame(
            columns=[
                "station_id",
                "num_bikes_available",
                "num_docks_available",
                "is_installed",
                "is_renting",
                "is_returning",
                "last_reported",
                "vehicle_types_available",
            ]
        )

    # Keep the nested vehicle JSON on the combined row too, for traceability.
    combined = station_info.merge(station_status, on="station_id", how="outer")

    vehicle_counts = vehicle_count_columns(station_vehicle_rows, vehicle_types)
    for column in (
        "bikes_classic",
        "bikes_ebike",
        "bikes_escooter",
        "bikes_cargo",
        "bikes_other",
    ):
        combined[column] = combined["station_id"].map(
            lambda station_id, col=column: vehicle_counts.get(station_id, {}).get(col, 0)
        ).fillna(0).astype(int)

    # Aggregate the free-bike feed to the station it names.
    if free_bike_rows_:
        bikes = pd.DataFrame(free_bike_rows_)
        bikes["station_id"] = bikes["station_id"].fillna("").astype(str)
        bike_agg = (
            bikes.groupby("station_id", dropna=False)
            .agg(
                free_bikes_in_feed=("bike_id", "count"),
                free_bikes_reserved=("is_reserved", "sum"),
                free_bikes_disabled=("is_disabled", "sum"),
            )
            .reset_index()
        )
        combined = combined.merge(bike_agg, on="station_id", how="left")
    for column in ("free_bikes_in_feed", "free_bikes_reserved", "free_bikes_disabled"):
        if column not in combined:
            combined[column] = 0
        combined[column] = combined[column].fillna(0).astype(int)

    # Geofence assignment: primary zone is the smallest containing polygon.
    zone_values = combined.apply(
        lambda row: assign_zones(row.get("lat"), row.get("lon"), zones), axis=1
    )
    combined["zone_name"] = [value[0] for value in zone_values]
    combined["zone_names"] = [value[1] for value in zone_values]

    # Derived measures used later by the analyst stages.
    combined["total_docks_reported"] = (
        combined["num_bikes_available"].fillna(0) + combined["num_docks_available"].fillna(0)
    ).astype(int)
    combined["utilisation_pct"] = [
        round(100.0 * bikes / capacity, 1) if capacity not in (None, 0) and not pd.isna(capacity) else None
        for bikes, capacity in zip(
            combined["num_bikes_available"].fillna(0), combined["capacity"]
        )
    ]
    combined["is_empty"] = combined["num_bikes_available"].fillna(0) == 0
    combined["is_full"] = combined["num_docks_available"].fillna(0) == 0
    combined["is_available"] = (
        combined["is_installed"].fillna(False).astype(bool)
        & combined["is_renting"].fillna(False).astype(bool)
    )
    combined["last_reported_utc"] = combined["last_reported"].map(iso_utc)
    combined["last_reported_local"] = combined["last_reported"].map(lambda value: iso_local(value, tz))
    combined["reported_age_seconds"] = [
        int(snapshot.timestamp() - float(value)) if value not in (None, "") and not pd.isna(value) else None
        for value in combined["last_reported"]
    ]

    # Snapshot/system context, repeated on every row so each snapshot is self-contained.
    combined.insert(0, "snapshot_utc", snapshot.isoformat())
    combined.insert(1, "snapshot_local", snapshot.astimezone(tz).isoformat())
    combined.insert(2, "system_id", system_info.get("system_id", ""))
    combined.insert(3, "system_name", system_info.get("name", ""))
    combined.insert(4, "system_timezone", system_info.get("timezone", ""))
    combined.insert(5, "station_feed_last_updated", station_feed_last_updated)
    combined.insert(6, "station_feed_last_updated_utc", iso_utc(station_feed_last_updated))
    combined.insert(
        7,
        "station_feed_age_seconds",
        int(snapshot.timestamp() - float(station_feed_last_updated))
        if station_feed_last_updated is not None
        else None,
    )

    combined = combined.rename(
        columns={
            "name": "station_name",
            "capacity": "capacity",
            "vehicle_types_available": "vehicle_types_available_json",
        }
    )
    combined = combined.sort_values("station_id", kind="stable").reset_index(drop=True)

    preferred_order = [
        "snapshot_utc",
        "snapshot_local",
        "system_id",
        "system_name",
        "system_timezone",
        "station_feed_last_updated",
        "station_feed_last_updated_utc",
        "station_feed_age_seconds",
        "station_id",
        "station_name",
        "lat",
        "lon",
        "zone_name",
        "zone_names",
        "capacity",
        "num_bikes_available",
        "num_docks_available",
        "total_docks_reported",
        "utilisation_pct",
        "is_empty",
        "is_full",
        "is_installed",
        "is_renting",
        "is_returning",
        "is_available",
        "bikes_classic",
        "bikes_ebike",
        "bikes_escooter",
        "bikes_cargo",
        "bikes_other",
        "free_bikes_in_feed",
        "free_bikes_reserved",
        "free_bikes_disabled",
        "last_reported",
        "last_reported_utc",
        "last_reported_local",
        "reported_age_seconds",
        "vehicle_types_available_json",
        "rental_uri_android",
        "rental_uri_ios",
    ]
    remaining = [column for column in combined.columns if column not in preferred_order]
    return combined[[column for column in preferred_order if column in combined.columns] + remaining]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root-url",
        default=GBFS_ROOT,
        help="GBFS discovery URL (default: Brighton Beryl v2.2)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Output folder (default: the folder containing this script)",
    )
    args = parser.parse_args()

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshot = datetime.now(timezone.utc)

    print(f"Discovering feeds from {args.root_url}")
    root_payload = fetch_json(args.root_url)
    language = "en" if "en" in root_payload.get("data", {}) else next(iter(root_payload["data"]))
    feeds = root_payload["data"][language]["feeds"]

    print(f"Fetching {len(feeds)} feeds ...")
    payloads: dict[str, dict[str, Any]] = {}
    for feed in feeds:
        name = feed["name"]
        url = feed["url"]
        payloads[name] = fetch_json(url)
        print(f"  {name:<24} {len(payloads[name].get('data', {}))} data keys")

    # Discovery feed
    feed_rows = [
        {
            "feed_name": feed["name"],
            "feed_url": feed["url"],
            "feed_last_updated": payloads.get(feed["name"], {}).get("last_updated"),
            "feed_ttl": payloads.get(feed["name"], {}).get("ttl"),
            "feed_version": payloads.get(feed["name"], {}).get("version"),
        }
        for feed in feeds
    ]
    write_csv(feed_rows, out / "gbfs_feeds.csv")

    # Static reference feeds
    system_info = payloads["system_information"]["data"]
    tz = ZoneInfo(system_info.get("timezone", "Europe/London"))
    write_csv(system_information_rows(payloads["system_information"]), out / "system_information.csv")

    station_info_rows = station_information_rows(payloads["station_information"])
    write_csv(station_info_rows, out / "station_information.csv")

    status_rows, status_vehicle_rows = station_status_rows(payloads["station_status"])
    write_csv(status_rows, out / "station_status.csv")
    write_csv(status_vehicle_rows, out / "station_status_vehicle_types.csv")

    write_csv(free_bike_rows(payloads["free_bike_status"]), out / "free_bike_status.csv")

    vehicle_types = payloads["vehicle_types"]["data"]["vehicle_types"]
    write_csv(vehicle_types, out / "vehicle_types.csv")
    write_csv(payloads["system_regions"]["data"]["regions"], out / "system_regions.csv")
    write_csv(payloads["gbfs_versions"]["data"]["versions"], out / "gbfs_versions.csv")

    plan_rows, rate_rows, fee_rows = pricing_plan_rows(payloads["system_pricing_plans"])
    write_csv(plan_rows, out / "system_pricing_plans.csv")
    write_csv(rate_rows, out / "system_pricing_plan_rates.csv")
    write_csv(fee_rows, out / "system_pricing_plan_fees.csv")

    # Geofencing: both raw zone CSV and point-in-polygon lookup for data.csv.
    geofence_features = payloads["geofencing_zones"]["data"]["geofencing_zones"].get("features", [])
    zones, zone_rows = zone_lookup(geofence_features)
    write_csv(zone_rows, out / "geofencing_zones.csv")

    combined = build_combined(
        snapshot=snapshot,
        system_info=system_info,
        station_info_rows=station_info_rows,
        station_status_rows_=status_rows,
        station_vehicle_rows=status_vehicle_rows,
        free_bike_rows_=free_bike_rows(payloads["free_bike_status"]),
        vehicle_types=vehicle_types,
        zones=zones,
        station_feed_last_updated=payloads["station_status"].get("last_updated"),
        tz=tz,
    )
    # One file per run gives us a time series without overwriting history.
    stamp = snapshot.strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = out / f"data_{stamp}.csv"
    collision = 1
    while snapshot_path.exists():
        snapshot_path = out / f"data_{stamp}_{collision:02d}.csv"
        collision += 1
    combined.to_csv(snapshot_path, index=False, encoding="utf-8")

    # Keep a stable latest-snapshot path for quick inspection and existing demos.
    combined.to_csv(out / "data.csv", index=False, encoding="utf-8")

    print(f"\nWrote {len(combined)} station rows to {snapshot_path}")
    print(f"Latest snapshot also copied to {out / 'data.csv'}")
    print(f"All feed CSVs are in {out}")


if __name__ == "__main__":
    main()
