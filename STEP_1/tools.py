"""Tools for STEP 1 — The smallest agent: audit before analysis.

The language model never computes a number. Every function here returns a
structured payload with its own window, caveats and summary. The harness adds
an evidence id.

Data: `../data/snapshots/DEMO_DATA_*.csv` by default (repo-relative).
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "data" / "snapshots"
STATE_ORDER = ["EMPTY", "LOW", "OK", "FULL"]


# ---------------------------------------------------------------------------
# loading + cleaning
# ---------------------------------------------------------------------------


def _data_dir(data_dir: str | Path | None = None) -> Path:
    if data_dir:
        return Path(data_dir)
    env = os.environ.get("BIKESHARE_DATA")
    return Path(env) if env else DEFAULT_DATA


def _stamp_utc(filename: str) -> datetime | None:
    match = re.search(r"(\d{8})_(\d{6})", filename)
    if not match:
        return None
    local = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
    local = local.replace(tzinfo=ZoneInfo("Europe/London"))
    return local.astimezone(timezone.utc)


def _parse_vehicle_types(value: object) -> dict[str, int]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        items = ast.literal_eval(value)
        return {str(item["vehicle_type_id"]): int(item["count"]) for item in items}
    except (ValueError, SyntaxError, KeyError, TypeError):
        return {}


def _classify(frame: pd.DataFrame) -> pd.DataFrame:
    """A defensible state definition, given the docks=4 reporting floor.

    EMPTY : no bikes
    LOW   : 1-2 bikes
    FULL  : <=4 free docks (the floor) AND >=75% of observed bays occupied
    OK    : everything else

    'num_docks_available == 0' is never observed, so it cannot define FULL.
    """
    bays = frame["num_bikes_available"] + frame["num_docks_available"]
    frame["bays"] = bays
    frame["occupancy"] = np.where(bays > 0, frame["num_bikes_available"] / bays, np.nan)
    frame["fill_ratio"] = np.where(
        frame["capacity"] > 0, frame["num_bikes_available"] / frame["capacity"], np.nan
    )
    frame["capacity_residual"] = bays - frame["capacity"]
    frame["state"] = np.select(
        [
            frame["num_bikes_available"] == 0,
            (frame["num_docks_available"] <= 4) & (frame["occupancy"] >= 0.75),
            frame["num_bikes_available"] <= 2,
        ],
        ["EMPTY", "FULL", "LOW"],
        default="OK",
    )
    return frame


def _read_one(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["source_file"] = path.name
    frame["snapshot_ts"] = pd.to_datetime(frame["last_reported"], unit="s", utc=True)
    collected = _stamp_utc(path.name)
    frame["collected_utc"] = collected
    if collected is not None:
        frame["lag_min"] = (collected - frame["snapshot_ts"]).dt.total_seconds() / 60
    else:
        frame["lag_min"] = np.nan
    frame["vehicle_types"] = frame["vehicle_types_available"].map(_parse_vehicle_types)
    return _classify(frame)


@lru_cache(maxsize=8)
def _load_raw_cached(directory: str) -> pd.DataFrame:
    paths = sorted(Path(directory).glob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"no snapshot CSV files in {directory}")
    frames = [_read_one(path) for path in paths]
    raw = pd.concat(frames, ignore_index=True)
    raw["resid_abs"] = raw["capacity_residual"].abs()
    return raw


def _load_raw(data_dir: str | Path | None = None) -> pd.DataFrame:
    return _load_raw_cached(str(_data_dir(data_dir).resolve()))


def _snapshot_choices(raw: pd.DataFrame) -> pd.DataFrame:
    """Pick one file per observation time, then keep its rows.

    Two of the bundled files are byte-identical observations collected 16 s
    apart. Keeping both would double-count that moment and silently double the
    apparent fleet. The choice rule also protects against a worse duplicate:
    most rows, then the lowest median capacity residual, then the last name.
    """
    rows: list[dict] = []
    for ts, group in raw.groupby("snapshot_ts", sort=True):
        stats = (
            group.groupby("source_file")
            .agg(
                rows=("station_id", "size"),
                resid=("resid_abs", "median"),
                lag=("lag_min", "median"),
            )
            .reset_index()
            .sort_values(["rows", "resid", "source_file"], ascending=[False, True, False])
        )
        chosen = str(stats.iloc[0]["source_file"])
        rows.append(
            {
                "snapshot_ts": ts,
                "source_file": chosen,
                "files": sorted(stats["source_file"].tolist()),
                "duplicate_files": len(stats) > 1,
            }
        )
    return pd.DataFrame(rows)


@lru_cache(maxsize=8)
def _load_panel_cached(directory: str) -> pd.DataFrame:
    raw = _load_raw(directory)
    choices = _snapshot_choices(raw)
    keep = set(zip(choices["snapshot_ts"], choices["source_file"]))
    panel = raw[
        raw.apply(lambda r: (r["snapshot_ts"], r["source_file"]) in keep, axis=1)
    ].copy()
    panel = panel.drop_duplicates(["snapshot_ts", "station_id"])
    return panel.sort_values(["snapshot_ts", "station_id"]).reset_index(drop=True)


def _load_panel(data_dir: str | Path | None = None) -> pd.DataFrame:
    return _load_panel_cached(str(_data_dir(data_dir).resolve()))


# ---------------------------------------------------------------------------
# shared shapes
# ---------------------------------------------------------------------------


def _iso(value: object) -> str:
    return pd.Timestamp(value).isoformat()


def _timeline(panel: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    previous: pd.Timestamp | None = None
    for ts, group in panel.groupby("snapshot_ts", sort=True):
        gap = None if previous is None else (ts - previous).total_seconds() / 60
        rows.append(
            {
                "snapshot_ts": _iso(ts),
                "n_stations": int(len(group)),
                "bikes": int(group["num_bikes_available"].sum()),
                "docks": int(group["num_docks_available"].sum()),
                "capacity": int(group["capacity"].sum()),
                "empty": int((group["state"] == "EMPTY").sum()),
                "low": int((group["state"] == "LOW").sum()),
                "full": int((group["state"] == "FULL").sum()),
                "not_renting": int((~group["is_renting"]).sum()),
                "gap_from_previous_min": None if gap is None else round(gap, 1),
            }
        )
        previous = ts
    return rows


def _window(panel: pd.DataFrame) -> dict:
    stamps = sorted(panel["snapshot_ts"].unique())
    gaps = []
    for before, after in zip(stamps, stamps[1:]):
        minutes = (after - before).total_seconds() / 60
        if minutes > 30:
            gaps.append(
                {
                    "after": _iso(before),
                    "before": _iso(after),
                    "minutes": round(minutes, 1),
                }
            )
    deltas = [
        (b - a).total_seconds() / 60 for a, b in zip(stamps, stamps[1:])
    ]
    return {
        "start": _iso(stamps[0]),
        "end": _iso(stamps[-1]),
        "n_snapshots": len(stamps),
        "n_stations": int(panel["station_id"].nunique()),
        "duration_hours": round((stamps[-1] - stamps[0]).total_seconds() / 3600, 2),
        "cadence_min_median": round(float(np.median(deltas)), 1) if deltas else None,
        "gaps": gaps,
    }


def _caveats(panel: pd.DataFrame) -> list[str]:
    stamps = sorted(panel["snapshot_ts"].unique())
    duration = (stamps[-1] - stamps[0]).total_seconds() / 3600
    docks4 = (panel["num_docks_available"] == 4).mean()
    resid = panel["capacity_residual"]
    lag = panel["lag_min"].dropna()
    gaps = _window(panel)["gaps"]
    caveats = [
        f"irregular cadence: {len(stamps)} snapshots over {duration:.1f} h"
        + (f", {len(gaps)} gap(s) longer than 30 min" if gaps else ""),
        f"num_docks_available has a reporting floor at 4 ({docks4:.0%} of rows); "
        "docks == 0 is never observed",
        f"capacity is soft: bikes + docks - capacity ranges "
        f"{int(resid.min())}..{int(resid.max())}",
        "single day and single weekday: no weekend or seasonal coverage",
    ]
    if len(lag):
        caveats.append(
            f"feed lag {lag.min():.1f}-{lag.max():.1f} min between collection and last_reported"
        )
    return caveats


def _envelope(panel: pd.DataFrame, tool: str, data: dict, summary: str) -> dict:
    return {
        "tool": tool,
        "as_of": _iso(panel["snapshot_ts"].max()),
        "window": _window(panel),
        "data": data,
        "caveats": _caveats(panel),
        "summary": summary,
    }


def _last(panel: pd.DataFrame) -> pd.DataFrame:
    latest = panel["snapshot_ts"].max()
    return panel[panel["snapshot_ts"] == latest].copy()


def _flow_rows(panel: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    frame = panel
    if start is not None:
        frame = frame[frame["snapshot_ts"] >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        frame = frame[frame["snapshot_ts"] <= pd.Timestamp(end, tz="UTC")]
    pivot = frame.pivot(index="station_id", columns="snapshot_ts", values="num_bikes_available")
    if pivot.shape[1] < 2:
        raise ValueError("net_flow needs at least two snapshots in the window")
    pivot = pivot.sort_index(axis=1)
    first = pivot.iloc[:, 0]
    last = pivot.iloc[:, -1]
    hours = (pivot.columns[-1] - pivot.columns[0]).total_seconds() / 3600
    changes = pivot.diff(axis=1).abs().sum(axis=1)
    names = (
        frame.drop_duplicates("station_id")
        .set_index("station_id")
        .reindex(pivot.index)
    )
    rows = pd.DataFrame(
        {
            "station_id": pivot.index,
            "name": names["name"].astype(str).values,
            "first_bikes": first.astype(int).values,
            "last_bikes": last.astype(int).values,
            "delta": (last - first).astype(int).values,
            "churn": changes.astype(int).values,
        }
    )
    rows["rate_per_hour"] = (rows["delta"] / hours).round(3)
    return rows.sort_values("rate_per_hour")


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def list_snapshots(data_dir: str | None = None) -> dict:
    """List every snapshot file, its observation time, duplicate status and health."""
    raw = _load_raw(data_dir)
    choices = _snapshot_choices(raw)
    chosen = {
        (row.snapshot_ts, row.source_file): row
        for row in choices.itertuples(index=False)
    }
    files = []
    for (source_file), group in raw.groupby("source_file", sort=True):
        ts = group["snapshot_ts"].iloc[0]
        choice = chosen.get((ts, source_file))
        files.append(
            {
                "source_file": source_file,
                "snapshot_ts": _iso(ts),
                "collected_utc": _iso(group["collected_utc"].iloc[0]),
                "lag_min": round(float(group["lag_min"].median()), 1),
                "rows": int(len(group)),
                "bikes": int(group["num_bikes_available"].sum()),
                "docks": int(group["num_docks_available"].sum()),
                "capacity": int(group["capacity"].sum()),
                "empty": int((group["state"] == "EMPTY").sum()),
                "full": int((group["state"] == "FULL").sum()),
                "not_renting": int((~group["is_renting"]).sum()),
                "residual_range": [
                    int(group["capacity_residual"].min()),
                    int(group["capacity_residual"].max()),
                ],
                "chosen": bool(choice is not None),
                "duplicate_observation": bool(choice.duplicate_files) if choice is not None else False,
            }
        )
    panel = _load_panel(data_dir)
    return _envelope(
        panel,
        "list_snapshots",
        {"files": files, "n_files": len(files), "n_unique_observations": int(len(choices))},
        f"{len(files)} files, {len(choices)} unique observation times",
    )


def read_snapshot(source_file: str | None = None, rows: int = 5, data_dir: str | None = None) -> dict:
    """Read one raw snapshot and return its schema, a sample and basic counts."""
    panel = _load_panel(data_dir)
    if source_file:
        frame = panel[panel["source_file"] == source_file]
        if frame.empty:
            raise ValueError(f"{source_file!r} is not a chosen snapshot file")
    else:
        frame = _last(panel)
        source_file = str(frame["source_file"].iloc[0])
    sample = frame[
        [
            "station_id",
            "name",
            "num_bikes_available",
            "num_docks_available",
            "capacity",
            "is_renting",
            "last_reported",
            "state",
        ]
    ].head(max(1, min(rows, 20)))
    return _envelope(
        panel,
        "read_snapshot",
        {
            "source_file": source_file,
            "n_stations": int(len(frame)),
            "columns": list(frame.columns),
            "sample": sample.to_dict(orient="records"),
            "bikes": int(frame["num_bikes_available"].sum()),
            "docks": int(frame["num_docks_available"].sum()),
            "empty": int((frame["state"] == "EMPTY").sum()),
            "full": int((frame["state"] == "FULL").sum()),
        },
        f"{source_file}: {len(frame)} stations, {int(frame['num_bikes_available'].sum())} bikes",
    )


def profile_columns(data_dir: str | None = None) -> dict:
    """Column-by-column profile: dtype, nulls, range and top values."""
    panel = _load_panel(data_dir)
    columns = []
    for name in panel.columns:
        series = panel[name]
        try:
            unique = int(series.nunique(dropna=True))
        except TypeError:
            # vehicle_types is a column of dicts: hash its string form instead
            unique = int(series.astype(str).nunique(dropna=True))
        item = {
            "column": name,
            "dtype": str(series.dtype),
            "nulls": int(series.isna().sum()),
            "unique": unique,
        }
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            item.update(
                {
                    "min": float(series.min()),
                    "max": float(series.max()),
                    "median": float(series.median()),
                }
            )
        else:
            counts = series.astype(str).value_counts().head(5)
            item["top_values"] = {str(k): int(v) for k, v in counts.items()}
        columns.append(item)
    return _envelope(
        panel,
        "profile_columns",
        {"columns": columns, "n_rows": int(len(panel)), "n_columns": int(panel.shape[1])},
        f"{panel.shape[1]} columns, {len(panel)} rows",
    )


def audit_snapshots(data_dir: str | None = None) -> dict:
    """Audit the snapshots before analysing them. Returns findings, not charts."""
    raw = _load_raw(data_dir)
    panel = _load_panel(data_dir)
    choices = _snapshot_choices(raw)
    last = _last(panel)
    stamps = sorted(panel["snapshot_ts"].unique())
    duration = (stamps[-1] - stamps[0]).total_seconds() / 3600
    docks4_share = float((panel["num_docks_available"] == 4).mean())
    docks4_stations = int(
        (
            panel.groupby("station_id")["num_docks_available"]
            .agg(lambda s: s.min() == 4 and s.max() == 4)
            .sum()
        )
    )
    docks0 = int((panel["num_docks_available"] == 0).sum())
    resid = panel["capacity_residual"]
    bikes_gt_cap = int((panel["num_bikes_available"] > panel["capacity"]).sum())
    lag = panel["lag_min"].dropna()
    static = panel.groupby("station_id")["num_bikes_available"].nunique()
    static_count = int((static == 1).sum())
    not_renting = (
        panel[~panel["is_renting"]]
        .groupby(["station_id", "name"])
        .size()
        .reset_index(name="snapshots")
        .sort_values("snapshots", ascending=False)
    )
    duplicate_rows = choices[choices["duplicate_files"]]
    gaps = _window(panel)["gaps"]

    findings: list[dict] = []

    findings.append(
        {
            "id": "A1",
            "severity": "high",
            "finding": (
                f"num_docks_available is exactly 4 in {docks4_share:.1%} of rows and "
                f"{docks4_stations} of {int(panel['station_id'].nunique())} stations never report "
                f"anything else; docks == 0 occurs {docks0} times."
            ),
            "consequence": (
                "A 'full station' alert written as docks == 0 would never fire. The field looks "
                "like a reporting floor, not a dock count."
            ),
            "fix": (
                "Define FULL as docks <= 4 AND observed occupancy >= 75%. Report the floor to the "
                "feed provider."
            ),
        }
    )
    findings.append(
        {
            "id": "A2",
            "severity": "high",
            "finding": (
                f"bikes + docks - capacity ranges {int(resid.min())}..{int(resid.max())}; "
                f"{bikes_gt_cap} rows have more bikes than capacity."
            ),
            "consequence": (
                "Capacity is soft (virtual/overflow bays). fill_ratio = bikes/capacity can exceed "
                "1.0, so it cannot be compared across stations without a caveat."
            ),
            "fix": "Use occupancy = bikes / (bikes + docks) and keep capacity only as a reference.",
        }
    )
    if len(duplicate_rows):
        examples = [
            f"{row.source_file} / {', '.join(row.files)}"
            for row in duplicate_rows.itertuples(index=False)
        ]
        findings.append(
            {
                "id": "A3",
                "severity": "medium",
                "finding": (
                    f"{len(duplicate_rows)} observation time(s) appear in more than one file; "
                    f"the files are identical. Example: {examples[0]}."
                ),
                "consequence": (
                    "Keeping both doubles the fleet and the empty count at that moment and "
                    "distorts any rate calculated from row counts."
                ),
                "fix": "Deduplicate on last_reported (the observation time), not the file name.",
            }
        )
    if len(lag):
        findings.append(
            {
                "id": "A4",
                "severity": "medium",
                "finding": (
                    f"The gap between collection time (file stamp) and last_reported is "
                    f"{lag.min():.1f}-{lag.max():.1f} min (median {lag.median():.1f})."
                ),
                "consequence": (
                    "The feed is not real-time. A rider-facing 'available now' claim is already "
                    "several minutes stale."
                ),
                "fix": "Show the lag; never mix file-stamp time with last_reported in the same series.",
            }
        )
    findings.append(
        {
            "id": "A5",
            "severity": "high" if len(not_renting) else "low",
            "finding": (
                f"{len(not_renting)} station(s) report is_renting == False in every snapshot: "
                + ", ".join(f"{row.name} ({row.station_id})" for row in not_renting.itertuples())
                if len(not_renting)
                else "No station is persistently not renting."
            ),
            "consequence": "Those stations cannot serve a trip for the whole window; they are outages, not demand signals.",
            "fix": "Dispatch maintenance separately from rebalancing; do not count them as empty demand.",
        }
    )
    findings.append(
        {
            "id": "A6",
            "severity": "medium",
            "finding": (
                f"{static_count} of {int(panel['station_id'].nunique())} stations never change bike "
                f"count; {len(gaps)} collection gap(s) longer than 30 min."
            ),
            "consequence": (
                "Some static stations are genuinely quiet; others may be frozen sensors. A gap "
                "makes 'what happened at 07:48' unanswerable."
            ),
            "fix": "Split static stations into idle vs stale using last_reported; mark gaps as no-data.",
        }
    )
    findings.append(
        {
            "id": "A7",
            "severity": "info",
            "finding": (
                f"The deduplicated panel has {len(stamps)} snapshots over {duration:.1f} h on a "
                f"single day; empties moved {int((panel[panel['snapshot_ts']==stamps[0]]['state']=='EMPTY').sum())}"
                f" -> {int((last['state']=='EMPTY').sum())}, fulls "
                f"{int((panel[panel['snapshot_ts']==stamps[0]]['state']=='FULL').sum())}"
                f" -> {int((last['state']=='FULL').sum())}."
            ),
            "consequence": (
                "Enough for change detection and flow; not enough for a daily profile, seasonality "
                "or a trustworthy 60-minute forecast."
            ),
            "fix": "Keep the 5-minute collector running; gate forecasting on elapsed time and snapshots.",
        }
    )

    metrics = {
        "n_files": int(raw["source_file"].nunique()),
        "n_unique_snapshots": len(stamps),
        "n_stations": int(panel["station_id"].nunique()),
        "n_rows": int(len(panel)),
        "duration_hours": round(duration, 2),
        "docks4_share": round(docks4_share, 4),
        "docks4_stations": docks4_stations,
        "docks0_rows": docks0,
        "capacity_residual_min": int(resid.min()),
        "capacity_residual_max": int(resid.max()),
        "bikes_over_capacity_rows": bikes_gt_cap,
        "lag_min": round(float(lag.min()), 1) if len(lag) else None,
        "lag_median_min": round(float(lag.median()), 1) if len(lag) else None,
        "lag_max_min": round(float(lag.max()), 1) if len(lag) else None,
        "static_stations": static_count,
        "not_renting_stations": int(len(not_renting)),
        "not_renting": not_renting.to_dict(orient="records"),
        "duplicate_observations": int(len(duplicate_rows)),
        "gaps": gaps,
        "last_bikes": int(last["num_bikes_available"].sum()),
        "last_docks": int(last["num_docks_available"].sum()),
        "last_capacity": int(last["capacity"].sum()),
        "last_empty": int((last["state"] == "EMPTY").sum()),
        "last_low": int((last["state"] == "LOW").sum()),
        "last_full": int((last["state"] == "FULL").sum()),
    }
    return _envelope(
        panel,
        "audit_snapshots",
        {
            "findings": findings,
            "metrics": metrics,
            "recommended_definitions": {
                "time": "last_reported (UTC epoch), not the file stamp",
                "EMPTY": "num_bikes_available == 0",
                "FULL": "num_docks_available <= 4 AND occupancy >= 0.75",
                "occupancy": "bikes / (bikes + docks); do not trust capacity alone",
                "dedupe": "one row per (last_reported, station_id)",
            },
        },
        f"{len(findings)} findings, {sum(f['severity']=='high' for f in findings)} high severity",
    )


TOOLS = {
    "list_snapshots": list_snapshots,
    "read_snapshot": read_snapshot,
    "profile_columns": profile_columns,
    "audit_snapshots": audit_snapshots,
}

SPECS = [{'type': 'function',
  'function': {'name': 'list_snapshots',
               'description': 'List every snapshot file with its observation time, feed lag, '
                              'counts and duplicate status.',
               'parameters': {'type': 'object',
                              'properties': {},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'read_snapshot',
               'description': 'Read one snapshot: schema, sample rows and key counts.',
               'parameters': {'type': 'object',
                              'properties': {'source_file': {'type': 'string',
                                                             'description': 'File name; omit for '
                                                                            'the latest snapshot.'},
                                             'rows': {'type': 'integer',
                                                      'description': 'Sample rows (1-20).',
                                                      'minimum': 1,
                                                      'maximum': 20}},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'profile_columns',
               'description': 'Profile every column: type, nulls, numeric range or top values.',
               'parameters': {'type': 'object',
                              'properties': {},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'audit_snapshots',
               'description': 'Audit data quality before analysis: docks floor, soft capacity, '
                              'duplicates, feed lag, outages, gaps.',
               'parameters': {'type': 'object',
                              'properties': {},
                              'required': [],
                              'additionalProperties': False}}}]
