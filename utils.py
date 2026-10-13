"""
Shared utilities for the Brighton Bikeshare dashboard.

Single home for every piece of re-usable logic:
  * GBFS fetching + the full data pipeline (per-feed CSVs, geofencing JSON,
    and a timestamped DEMO_DATA_<stamp>.csv snapshot) -- formerly data.py
  * The ETL (extract / transform / load) + analysis shaping -- formerly app.py
  * A one-shot snapshot runner for the CLI / OS schedulers -- formerly collect.py

This module does NOT import Flask, so the pipeline and ETL can be driven from
the CLI (app.py --collect) as well as from the web app (app.py).
"""

import json
import os
import sys
from datetime import datetime, timezone
from os.path import abspath, dirname, join

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GBFS_BASE = "https://beryl-gbfs-production.web.app/v2_2/Brighton"
STATION_STATUS_URL = f"{GBFS_BASE}/station_status.json"
STATION_INFO_URL = f"{GBFS_BASE}/station_information.json"

HERE = dirname(abspath(__file__))
DATA_DIR = join(HERE, "data")
SNAPSHOTS_DIR = join(DATA_DIR, "snapshots")
HISTORY_CSV = join(DATA_DIR, "history.csv")

TIMEOUT_SECONDS = 20

# feed name -> JSON array key to export under data; None = whole data object
FEEDS = {
    "station_information": "stations",
    "station_status": "stations",
    "free_bike_status": "bikes",
    "vehicle_types": "vehicle_types",
    "system_pricing_plans": "plans",
    "system_regions": "regions",
    "gbfs_versions": "versions",
    "system_information": None,
}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_json(url: str) -> dict:
    resp = requests.get(url, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def feed_to_df(feed_name: str, arr_key, output: list[str] | None = None):
    """Pull one feed and flatten the relevant array into a DataFrame.

    ``output`` (optional): a list the human-readable progress message is
    appended to, so a caller can also surface it in a UI console.
    """
    url = f"{GBFS_BASE}/{feed_name}.json"
    msg = f"[fetch] {feed_name}.json ... "
    data = fetch_json(url)["data"]

    if arr_key is None:
        df = pd.json_normalize(data)  # whole object = single "record"
    else:
        df = pd.json_normalize(data.get(arr_key, []))

    msg += f"{len(df)} record(s)"
    print(msg)
    if output is not None:
        output.append(msg)
    return df if not df.empty else None


# ---------------------------------------------------------------------------
# Full data pipeline (formerly data.py)
# ---------------------------------------------------------------------------
def run_full_pipeline() -> str:
    """Fetch every GBFS feed, write per-feed CSVs + raw geofencing JSON, and
    build a timestamped DEMO snapshot. Returns the console output (also
    printed) so the dashboard's /run button can show it inline."""
    os.makedirs(DATA_DIR, exist_ok=True)
    lines: list[str] = []

    def say(msg: str) -> None:
        print(msg)
        lines.append(msg)

    for feed_name, arr_key in FEEDS.items():
        try:
            df = feed_to_df(feed_name, arr_key, output=lines)
            if df is not None:
                out = join(DATA_DIR, f"{feed_name}.csv")
                df.to_csv(out, index=False)
                say(f"[save] {feed_name}.csv -> {out}")
        except Exception as e:  # noqa: BLE001 - keep going, report per-feed
            say(f"[!] {feed_name}.json FAILED: {e}")

    # Structured feed: keep as raw JSON (GeoJSON doesn't flatten well).
    try:
        payload = fetch_json(f"{GBFS_BASE}/geofencing_zones.json")
        path = join(DATA_DIR, "geofencing_zones.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        say(f"[save] geofencing_zones.json ({len(payload.get('data', {}))} records)")
    except Exception as e:  # noqa: BLE001
        say(f"[!] geofencing_zones.json FAILED: {e}")

    # Combined demo snapshot: live availability + names/coords merged into one
    # analysis-ready file.
    try:
        demo_path, n_stations, n_cols = _write_demo_snapshot(output=lines)
        say(
            f"[save] {os.path.basename(demo_path)} "
            f"({n_stations} stations, {n_cols} cols)"
        )
    except Exception as e:  # noqa: BLE001
        say(f"[!] DEMO_DATA.csv FAILED: {e}")

    say(f"Done. CSVs written to: {DATA_DIR}")
    return "\n".join(lines)


def _write_demo_snapshot(output: list[str] | None = None) -> tuple[str, int, int]:
    """Fetch live status + station info, merge, and write a timestamped
    DEMO_DATA_<stamp>.csv. Returns (path, n_stations, n_cols)."""
    status = feed_to_df("station_status", "stations", output=output)
    info = feed_to_df("station_information", "stations", output=output)
    if status is None or info is None:
        raise RuntimeError("Could not fetch station status/information")

    # normalise station_id to str on BOTH feeds before merging (int-vs-str trap)
    keep_info = ["station_id", "name", "lat", "lon", "capacity"]
    info = info[info.columns.intersection(keep_info)].copy()
    status["station_id"] = status["station_id"].astype(str)
    info["station_id"] = info["station_id"].astype(str)
    demo = status.merge(info, on="station_id", how="left")

    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    demo_path = join(SNAPSHOTS_DIR, f"DEMO_DATA_{stamp}.csv")
    demo.to_csv(demo_path, index=False)
    return demo_path, len(demo), len(demo.columns)


def snapshot_current_data() -> str:
    """Fetch current live status + station info and write a fresh, timestamped
    DEMO_DATA_<stamp>.csv. Returns the console output (also printed)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    lines: list[str] = []

    def say(msg: str) -> None:
        print(msg)
        lines.append(msg)

    try:
        demo_path, n_stations, n_cols = _write_demo_snapshot(output=lines)
        say(
            f"[save] {os.path.basename(demo_path)} "
            f"({n_stations} stations, {n_cols} cols)"
        )
        say(f"Done. Current-data snapshot written to: {demo_path}")
    except Exception as e:  # noqa: BLE001
        say(f"[!] Snapshot FAILED: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ETL (extract / transform / load) -- formerly app.py
# ---------------------------------------------------------------------------
def extract() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pull live status + static station info from the GBFS feeds."""
    status_df = pd.DataFrame(fetch_json(STATION_STATUS_URL)["data"]["stations"])
    info_df = pd.DataFrame(fetch_json(STATION_INFO_URL)["data"]["stations"])
    return status_df, info_df


def transform(status_df: pd.DataFrame, info_df: pd.DataFrame) -> pd.DataFrame:
    """Merge the two feeds and derive analysis-friendly columns."""
    info_cols = ["station_id", "name", "lat", "lon", "capacity"]
    info = info_df[info_df.columns.intersection(info_cols)].copy()

    # station_id types differ across feeds (int vs str) - normalise before merge
    status_df["station_id"] = status_df["station_id"].astype(str)
    info["station_id"] = info["station_id"].astype(str)

    df = status_df.merge(info, on="station_id", how="left")

    for col in ["num_bikes_available", "num_docks_available", "capacity"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # GBFS 2.1+ renamed bikes->vehicles; normalise if both absent
    if "num_bikes_available" not in df.columns and "num_vehicles_available" in df.columns:
        df["num_bikes_available"] = df["num_vehicles_available"]

    # Derived: total available points and utilisation
    df["total_capacity"] = df["num_bikes_available"] + df["num_docks_available"]
    df["bike_share"] = df["total_capacity"].replace(0, 1)  # avoid div-by-zero
    df["utilisation_pct"] = (df["num_bikes_available"] / df["bike_share"] * 100).round(1)

    df["last_reported_readable"] = pd.to_datetime(
        df["last_reported"], unit="s", utc=True
    ).dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    return df


def load(df: pd.DataFrame) -> str:
    """Append one timestamped snapshot row per station to history.csv."""
    os.makedirs(DATA_DIR, exist_ok=True)
    snapshot_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot = df[["station_id", "num_bikes_available", "num_docks_available"]].copy()
    snapshot.insert(0, "snapshot_time", snapshot_time)
    snapshot.to_csv(
        HISTORY_CSV,
        mode="a",
        index=False,
        header=not os.path.exists(HISTORY_CSV),
    )
    return snapshot_time


def run_etl() -> tuple[pd.DataFrame | None, str | None, str | None]:
    """Run the full ETL pipeline. Returns (current_df, snapshot_time, error)."""
    try:
        status_df, info_df = extract()
        df = transform(status_df, info_df)
        snapshot_time = load(df)
        return df, snapshot_time, None
    except Exception as e:  # noqa: BLE001 - surface any feed/pipeline failure to the UI
        return None, None, str(e)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def _read_previous_snapshot() -> pd.DataFrame | None:
    """Load the second-most-recent snapshot from history for change detection."""
    if not os.path.exists(HISTORY_CSV):
        return None
    history = pd.read_csv(HISTORY_CSV)
    times = history["snapshot_time"].unique()
    if len(times) < 2:
        return None
    prev_time = sorted(times)[-2]
    prev = history[history["snapshot_time"] == prev_time].copy()
    prev["station_id"] = prev["station_id"].astype(str)
    return prev[["station_id", "num_bikes_available"]]


def _utilisation_histogram(series: pd.Series) -> dict:
    """Bucket utilisation % into 20pt bands, last slot is exactly 100%."""
    counts = []
    edges = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100), (100, 101)]
    for lo, hi in edges:
        n = int(((series >= lo) & (series < hi)).sum())
        counts.append(n if hi <= 100 else int((series == 100).sum()))
    labels = ["0%", "0-20%", "20-40%", "40-60%", "60-80%", "80-99%", "100%"]
    return {"labels": labels, "data": counts}


def analyse(df: pd.DataFrame) -> dict:
    """Turn the current dataframe into a dict of analysis results + chart data."""
    total_bikes = int(df["num_bikes_available"].sum())
    total_docks = int(df["num_docks_available"].sum())
    total_capacity = int(df["total_capacity"].sum())
    utilisation = round(total_bikes / total_capacity * 100, 1) if total_capacity else 0.0

    empty = df[df["num_bikes_available"] == 0]
    full = df[df["num_docks_available"] == 0]

    top_bikes = (
        df.sort_values("num_bikes_available", ascending=False)
        .head(5)[["name", "num_bikes_available"]]
        .to_dict(orient="records")
    )
    top_docks = (
        df.sort_values("num_docks_available", ascending=False)
        .head(5)[["name", "num_docks_available"]]
        .to_dict(orient="records")
    )

    rows = df[
        ["name", "station_id", "num_bikes_available", "num_docks_available",
         "utilisation_pct", "last_reported_readable"]
    ].sort_values("utilisation_pct", ascending=False).to_dict(orient="records")

    # Change vs the previous snapshot
    prev = _read_previous_snapshot()
    change = None
    if prev is not None:
        merged = df[["station_id", "num_bikes_available", "name"]].merge(
            prev, on="station_id", suffixes=("", "_prev"), how="left"
        )
        merged["delta"] = merged["num_bikes_available"] - merged[
            "num_bikes_available_prev"
        ].fillna(0)
        change = {
            "gained": merged.sort_values("delta", ascending=False)
            .head(3)[["name", "delta"]].to_dict(orient="records"),
            "lost": merged.sort_values("delta", ascending=True)
            .head(3)[["name", "delta"]].to_dict(orient="records"),
        }

    # ---- chart payloads (Chart.js consumes these as labelled series) ----
    def _top_n(column: str, n: int = 10) -> dict:
        top = df.sort_values(column, ascending=False).head(n)
        return {"labels": top["name"].tolist(), "data": top[column].astype(int).tolist()}

    chart = {
        "top_bikes": _top_n("num_bikes_available"),
        "top_docks": _top_n("num_docks_available"),
        "util_hist": _utilisation_histogram(df["utilisation_pct"]),
    }

    return {
        "total_bikes": total_bikes,
        "total_docks": total_docks,
        "total_capacity": total_capacity,
        "utilisation": utilisation,
        "n_stations": len(df),
        "n_empty": len(empty),
        "n_full": len(full),
        "top_bikes": top_bikes,
        "top_docks": top_docks,
        "rows": rows,
        "change": change,
        "chart": chart,
    }


# ---------------------------------------------------------------------------
# History helpers (used by the dashboard templates)
# ---------------------------------------------------------------------------
def read_time_series(limit: int = 30) -> list[dict]:
    """Total bikes + docks per snapshot, oldest first (for the trend chart)."""
    if not os.path.exists(HISTORY_CSV):
        return []
    try:
        history = pd.read_csv(HISTORY_CSV)
        if "snapshot_time" not in history.columns:
            return []
        agg = (
            history.groupby("snapshot_time", sort=True)
            .agg(total_bikes=("num_bikes_available", "sum"),
                 total_docks=("num_docks_available", "sum"))
            .reset_index()
        )
        return agg.tail(limit).to_dict(orient="records")
    except Exception:  # noqa: BLE001 - chart is best-effort
        return []


def count_snapshots() -> int:
    if not os.path.exists(HISTORY_CSV):
        return 0
    try:
        return len(pd.read_csv(HISTORY_CSV, usecols=["snapshot_time"])[
            "snapshot_time"].unique())
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# CLI / scheduler runner (formerly collect.py)
# ---------------------------------------------------------------------------
def run_snapshot(quiet: bool = False) -> int:
    """Run one ETL snapshot and append it to history.csv.

    Returns 0 on success, 1 if the ETL failed -- suitable for an OS scheduler.
    """
    df, snapshot_time, error = run_etl()
    if error is not None or df is None:
        print(f"ETL failed: {error or 'no dataframe returned'}", file=sys.stderr)
        return 1
    if not quiet:
        print(
            f"Snapshot {snapshot_time}: {len(df)} stations, "
            f"{int(df['num_bikes_available'].sum())} bikes, "
            f"{int(df['num_docks_available'].sum())} docks "
            "(appended to history.csv)"
        )
    return 0