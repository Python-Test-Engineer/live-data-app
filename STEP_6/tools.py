"""Tools for STEP 6 — Hand it to the room: extend, then close.

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


def build_panel(data_dir: str | None = None) -> dict:
    """Show the deduplicated time series: cadence, gaps and state counts per moment."""
    panel = _load_panel(data_dir)
    raw = _load_raw(data_dir)
    choices = _snapshot_choices(raw)
    return _envelope(
        panel,
        "build_panel",
        {
            "timeline": _timeline(panel),
            "n_files": int(raw["source_file"].nunique()),
            "n_unique_snapshots": int(len(choices)),
            "deduplicated": int(raw["source_file"].nunique() - len(choices)),
            "state_definition": {
                "EMPTY": "bikes == 0",
                "LOW": "bikes <= 2",
                "FULL": "docks <= 4 and occupancy >= 0.75",
                "OK": "otherwise",
            },
        },
        f"{len(choices)} deduped snapshots, {len(_window(panel)['gaps'])} gap(s) > 30 min",
    )


def net_flow(start: str | None = None, end: str | None = None, top_n: int = 8, data_dir: str | None = None) -> dict:
    """Signed bike change per station: drains (negative) vs sinks (positive)."""
    panel = _load_panel(data_dir)
    rows = _flow_rows(panel, start, end)
    top_n = max(1, min(int(top_n), 30))
    drains = rows.head(top_n)
    sinks = rows.tail(top_n).iloc[::-1]
    changed = rows[rows["delta"] != 0]
    return _envelope(
        panel,
        "net_flow",
        {
            "basis": "first vs last snapshot in the window; rate uses elapsed hours",
            "n_stations": int(len(rows)),
            "n_changed": int(len(changed)),
            "top_drains": drains.to_dict(orient="records"),
            "top_sinks": sinks.to_dict(orient="records"),
            "stations": rows.to_dict(orient="records"),
        },
        (
            f"fastest drain {drains.iloc[0]['name']} {drains.iloc[0]['rate_per_hour']:+.2f}/h; "
            f"fastest sink {sinks.iloc[0]['name']} {sinks.iloc[0]['rate_per_hour']:+.2f}/h"
        ),
    )


def state_transitions(data_dir: str | None = None) -> dict:
    """Observed EMPTY / LOW / OK / FULL transitions, plus per-station failure risk."""
    panel = _load_panel(data_dir)
    states = panel.pivot(index="station_id", columns="snapshot_ts", values="state").sort_index(axis=1)
    counts = {a: {b: 0 for b in STATE_ORDER} for a in STATE_ORDER}
    per_station = []
    for station_id, series in states.iterrows():
        values = list(series)
        failures = 0
        transitions = 0
        for before, after in zip(values, values[1:]):
            if pd.isna(before) or pd.isna(after):
                continue
            counts[str(before)][str(after)] += 1
            transitions += 1
            if after in ("EMPTY", "FULL") and before != after:
                failures += 1
        final = values[-1] if values else None
        per_station.append(
            {
                "station_id": int(station_id),
                "transitions": transitions,
                "failures": failures,
                "p_fail_next": round(failures / transitions, 3) if transitions else 0.0,
                "final_state": final,
            }
        )
    rows = {a: sum(counts[a].values()) for a in STATE_ORDER}
    matrix = {
        a: {
            b: counts[a][b] for b in STATE_ORDER
        }
        for a in STATE_ORDER
    }
    probabilities = {
        a: {
            b: (counts[a][b] / rows[a] if rows[a] else 0.0) for b in STATE_ORDER
        }
        for a in STATE_ORDER
    }
    final_counts = {s: int((panel[panel["snapshot_ts"] == panel["snapshot_ts"].max()]["state"] == s).sum()) for s in STATE_ORDER}
    top = sorted(per_station, key=lambda r: (r["p_fail_next"], r["failures"]), reverse=True)[:10]
    return _envelope(
        panel,
        "state_transitions",
        {
            "counts": matrix,
            "row_probabilities": probabilities,
            "final_state_counts": final_counts,
            "top_failure_risk": top,
        },
        f"{sum(rows.values())} transitions; final states {final_counts}",
    )


def failure_risk(horizon_min: int = 60, top_n: int = 10, data_dir: str | None = None) -> dict:
    """Rank stations by how soon a rider's experience fails, with a reason per station."""
    panel = _load_panel(data_dir)
    flow = _flow_rows(panel).set_index("station_id")
    last = _last(panel).set_index("station_id")
    horizon = max(5, int(horizon_min))
    rows = []
    for station_id, station in last.iterrows():
        rate = float(flow.loc[station_id, "rate_per_hour"]) if station_id in flow.index else 0.0
        bikes = int(station["num_bikes_available"])
        docks = int(station["num_docks_available"])
        state = str(station["state"])
        minutes_to_empty = bikes / max(-rate, 1e-9) * 60 if rate < 0 else float("inf")
        minutes_to_full = docks / max(rate, 1e-9) * 60 if rate > 0 else float("inf")

        if state == "EMPTY":
            score, mode = 0.95, "EMPTY_NOW"
            reason = "no bikes at the last observation; rider already locked out"
        elif state == "FULL":
            score, mode = 0.85, "FULL_NOW"
            reason = "at or over the free-dock floor; rider may not be able to return"
        elif bikes <= 2:
            if rate < 0:
                score, mode = 0.87, "EMPTY_SOON"
            else:
                score, mode = 0.55, "LOW"
            reason = f"{bikes} bike(s) left and change {rate:+.2f}/h"
        elif rate < 0 and minutes_to_empty <= horizon:
            score = 0.4 + 0.4 * (1 - minutes_to_empty / horizon)
            mode = "EMPTY_SOON"
            reason = f"draining {rate:+.2f}/h; about {minutes_to_empty:.0f} min to empty"
        elif rate > 0 and minutes_to_full <= horizon:
            score = 0.35 + 0.35 * (1 - minutes_to_full / horizon)
            mode = "FULL_SOON"
            reason = f"filling {rate:+.2f}/h; about {minutes_to_full:.0f} min to the dock floor"
        else:
            score, mode = 0.10, "OK"
            reason = f"{bikes} bikes, {docks} docks, change {rate:+.2f}/h"

        rows.append(
            {
                "station_id": int(station_id),
                "name": str(station["name"]),
                "bikes": bikes,
                "docks": docks,
                "state": state,
                "rate_per_hour": round(rate, 2),
                "minutes_to_empty": None if math.isinf(minutes_to_empty) else round(minutes_to_empty),
                "minutes_to_full": None if math.isinf(minutes_to_full) else round(minutes_to_full),
                "risk_score": round(min(score, 1.0), 3),
                "failure_mode": mode,
                "reason": reason,
            }
        )
    rows.sort(key=lambda r: (r["risk_score"], -r["bikes"]), reverse=True)
    top = rows[: max(1, min(int(top_n), 30))]
    state_counts = last["state"].value_counts().to_dict()
    return _envelope(
        panel,
        "failure_risk",
        {
            "horizon_min": horizon,
            "state_counts": {s: int(state_counts.get(s, 0)) for s in STATE_ORDER},
            "top_risk": top,
            "failed_now": [r for r in rows if r["failure_mode"] in ("EMPTY_NOW", "FULL_NOW")],
            "about_to_fail": sorted(
                [
                    r for r in rows
                    if r["failure_mode"] in ("EMPTY_SOON", "FULL_SOON")
                    and r.get("minutes_to_empty") is not None
                    and r["minutes_to_empty"] <= horizon
                ],
                key=lambda r: r["minutes_to_empty"],
            )[:10],
            "assumptions": [
                "linear extrapolation of the observed 2.75-hour rate",
                "no rebalancing during the window",
                "FULL uses the docks<=4 floor, not docks==0",
            ],
        },
        f"{len(top)} ranked; top {top[0]['name']} ({top[0]['failure_mode']}, {top[0]['risk_score']})",
    )


def rebalance_plan(max_moves: int = 20, data_dir: str | None = None) -> dict:
    """Match surplus stations to deficit stations, nearest first, and cost the moves."""
    panel = _load_panel(data_dir)
    last = _last(panel).copy()
    last["surplus"] = 0
    last["deficit"] = 0
    for index, station in last.iterrows():
        bikes = int(station["num_bikes_available"])
        docks = int(station["num_docks_available"])
        occupancy = float(station["occupancy"]) if pd.notna(station["occupancy"]) else 0.0
        capacity = int(station["capacity"])
        if bikes == 0:
            last.at[index, "deficit"] = 3
        elif bikes <= 2:
            last.at[index, "deficit"] = 2
        if docks <= 4 and occupancy >= 0.60 and bikes >= 6:
            last.at[index, "surplus"] = bikes - 4
        elif bikes > capacity:
            last.at[index, "surplus"] = bikes - int(capacity * 0.5)

    sources = last[last["surplus"] > 0].copy().sort_values("surplus", ascending=False)
    deficits = last[last["deficit"] > 0].copy().sort_values(["deficit", "state"], ascending=[False, True])
    remaining = {int(row.station_id): int(row.surplus) for row in sources.itertuples()}
    moves = []
    total_bikes = 0
    for target in deficits.itertuples():
        need = int(target.deficit)
        candidates = []
        for source in sources.itertuples():
            if remaining.get(int(source.station_id), 0) <= 0:
                continue
            km = _haversine_km(source.lat, source.lon, target.lat, target.lon)
            candidates.append((km, source))
        candidates.sort(key=lambda pair: pair[0])
        for km, source in candidates:
            if need <= 0 or total_bikes >= max_moves:
                break
            available = remaining.get(int(source.station_id), 0)
            if available <= 0:
                continue
            take = min(need, available, max_moves - total_bikes)
            if take <= 0:
                continue
            moves.append(
                {
                    "from_id": int(source.station_id),
                    "from_name": str(source.name),
                    "to_id": int(target.station_id),
                    "to_name": str(target.name),
                    "bikes": int(take),
                    "km": round(km, 2),
                }
            )
            remaining[int(source.station_id)] = available - take
            need -= take
            total_bikes += take
            if total_bikes >= max_moves:
                break
    helped = sorted({m["to_id"] for m in moves})
    return _envelope(
        panel,
        "rebalance_plan",
        {
            "moves": moves,
            "total_bikes": int(total_bikes),
            "total_km": round(sum(m["km"] for m in moves), 2),
            "deficits_total": int((last["deficit"] > 0).sum()),
            "deficits_helped": len(helped),
            "stations_helped": helped,
            "sources_used": len({m["from_id"] for m in moves}),
            "unmet_bikes": int(max(0, last["deficit"].sum() - total_bikes)),
            "assumptions": [
                "nearest-source greedy matching, not an optimal transport solve",
                "straight-line distance; no van capacity, traffic or shift constraints",
                "target: 3 bikes for an empty station, 2 for a low station",
            ],
        },
        f"{total_bikes} bikes in {len(moves)} moves, {len(helped)} deficit stations helped",
    )


def rank_actions(top_n: int = 5, data_dir: str | None = None) -> dict:
    """Turn findings into owner-shaped actions, ranked by impact and confidence."""
    audit = audit_snapshots(data_dir)["data"]
    risk = failure_risk(data_dir=data_dir)["data"]
    plan = rebalance_plan(data_dir=data_dir)["data"]
    metrics = audit["metrics"]

    actions = [
        {
            "id": "ACT1",
            "owner": "data / product",
            "action": "Replace the docks == 0 definition of FULL with docks <= 4 AND occupancy >= 0.75.",
            "where": "all stations",
            "when": "before the next rider-facing release",
            "expected_impact": "removes a full-station alert that can never fire",
            "confidence": "high",
            "falsifier": "a future snapshot with num_docks_available == 0",
            "limits": "occupancy still relies on a soft capacity field",
        },
        {
            "id": "ACT2",
            "owner": "operations",
            "action": (
                f"Move {plan['total_bikes']} bikes in {len(plan['moves'])} moves from "
                f"{plan['sources_used']} surplus stations to {plan['deficits_helped']} deficit stations."
            ),
            "where": ", ".join(f"{m['from_name']} -> {m['to_name']}" for m in plan["moves"][:3]),
            "when": "before the next weekday 07:00 peak",
            "expected_impact": f"at least one bike restored to {plan['deficits_helped']} stations; {plan['total_km']} km",
            "confidence": "medium",
            "falsifier": "those stations still report EMPTY two hours after the move",
            "limits": "greedy nearest-source plan; no van capacity or traffic model",
        },
        {
            "id": "ACT3",
            "owner": "maintenance",
            "action": (
                f"Dispatch technicians to the {metrics['not_renting_stations']} stations that are not "
                "renting in every snapshot."
            ),
            "where": ", ".join(f"{row['name']} ({row['station_id']})" for row in metrics["not_renting"]),
            "when": "today",
            "expected_impact": f"{metrics['not_renting_stations']} stations returned to service",
            "confidence": "high",
            "falsifier": "the station starts renting before the visit",
            "limits": "no outage duration or lost-trip estimate yet",
        },
        {
            "id": "ACT4",
            "owner": "network planning",
            "action": (
                f"Review the {metrics['static_stations']} stations whose bike count never changes; "
                "split idle from frozen using last_reported."
            ),
            "where": "network-wide",
            "when": "this month",
            "expected_impact": "avoids rebalancing stock that is not moving",
            "confidence": "low",
            "falsifier": "all static stations show fresh last_reported timestamps",
            "limits": "only 2.75 hours of observation",
        },
        {
            "id": "ACT5",
            "owner": "rider product",
            "action": (
                f"Show 'likely to be empty or full' flags for the {len(risk['top_risk'])} highest-risk "
                "stations, with a confidence label."
            ),
            "where": ", ".join(r["name"] for r in risk["top_risk"][:5]),
            "when": "next sprint",
            "expected_impact": "fewer wasted walks to a station that is already failing",
            "confidence": "medium",
            "falsifier": "flags are wrong more often than the 5-minute persistence baseline",
            "limits": "risk is extrapolated from 2.75 hours; no forecast is claimed",
        },
    ]
    weight = {"high": 1.0, "medium": 0.65, "low": 0.3}
    for action in actions:
        action["priority_score"] = round(weight[action["confidence"]], 2)
    actions.sort(key=lambda a: a["priority_score"], reverse=True)
    return _envelope(
        _load_panel(data_dir),
        "rank_actions",
        {"actions": actions[: max(1, min(int(top_n), len(actions)))], "all_actions": actions},
        f"{len(actions)} actions; top: {actions[0]['id']} {actions[0]['owner']}",
    )


def forecast_gate(horizon_min: int = 60, data_dir: str | None = None) -> dict:
    """Check whether a forecast is supportable. Refuse when it is not."""
    panel = _load_panel(data_dir)
    stamps = sorted(panel["snapshot_ts"].unique())
    duration = (stamps[-1] - stamps[0]).total_seconds() / 3600
    n_snapshots = len(stamps)
    pivot = panel.pivot(index="station_id", columns="snapshot_ts", values="num_bikes_available").sort_index(axis=1)

    persistence_errors = []
    mean_errors = []
    for index in range(1, pivot.shape[1]):
        actual = pivot.iloc[:, index]
        persistence_errors.extend((actual - pivot.iloc[:, index - 1]).abs().tolist())
        mean_errors.extend((actual - pivot.iloc[:, :index].mean(axis=1)).abs().tolist())
    persistence_mae = float(np.mean(persistence_errors)) if persistence_errors else None
    mean_mae = float(np.mean(mean_errors)) if mean_errors else None

    unique_days = len({pd.Timestamp(ts).date() for ts in stamps})
    sufficient = duration >= 48 and n_snapshots >= 50 and unique_days >= 2
    if not sufficient:
        status = "insufficient_data"
        reason = (
            f"only {duration:.1f} h across {n_snapshots} deduplicated snapshots on {unique_days} day(s); "
            f"a {int(horizon_min)}-minute forecast needs at least 48 h and 50 snapshots to validate"
        )
    elif persistence_mae is not None and mean_mae is not None and persistence_mae <= mean_mae:
        status = "baseline_only"
        reason = "persistence beats the historical mean, but no challenger has demonstrated skill yet"
    else:
        status = "no_skill"
        reason = "persistence does not beat the historical mean on the held-out steps"

    return _envelope(
        panel,
        "forecast_gate",
        {
            "status": status,
            "reason": reason,
            "horizon_min": int(horizon_min),
            "data_sufficiency": {
                "duration_hours": round(duration, 2),
                "n_snapshots": n_snapshots,
                "unique_days": unique_days,
                "required_hours": 48,
                "required_snapshots": 50,
                "sufficient": sufficient,
            },
            "baselines": {
                "persistence_mae_bikes": round(persistence_mae, 3) if persistence_mae is not None else None,
                "historical_mean_mae_bikes": round(mean_mae, 3) if mean_mae is not None else None,
                "n_held_out_steps": len(persistence_errors),
                "note": "persistence is 'next = now'; it is the bar any forecast must beat",
            },
            "would_need": [
                "at least 48 continuous hours of deduplicated 5-minute snapshots",
                "at least 50 snapshots for a 60-minute backtest",
                "seven days for a weekday x hour profile",
                "weather and event flags recorded at collection time, not backfilled",
            ],
            "fallback": "report failure_risk at the current drain rate, not a forecast",
        },
        f"{status}: {reason}",
    )


def validate_claim(claim: str, evidence_ids: list[str], ledger=None) -> dict:
    """Check that every number in a claim exists in the cited evidence."""
    if ledger is None:
        raise ValueError("validate_claim needs the harness evidence ledger")
    missing = [eid for eid in evidence_ids if eid not in ledger.items]
    numbers = ledger.numbers(evidence_ids)
    text = ledger.text(evidence_ids)
    tokens = re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?%?", claim)

    checked = []
    for token in tokens:
        is_percent = token.endswith("%")
        value = float(token.rstrip("%")) / (100 if is_percent else 1)
        supported = any(abs(value - candidate) <= max(0.011, abs(value) * 0.011) for candidate in numbers)
        if not supported and token.rstrip("%") in text:
            supported = True
        if not supported and value == 0:
            supported = True
        checked.append({"token": token, "value": round(value, 4), "supported": supported})

    unsupported = [item["token"] for item in checked if not item["supported"]]
    valid = not missing and not unsupported
    explanation = (
        "all numbers trace to the cited evidence"
        if valid
        else "unsupported: " + ", ".join(unsupported) if unsupported else "unknown evidence id: " + ", ".join(missing)
    )
    return {
        "tool": "validate_claim",
        "data": {
            "claim": claim,
            "evidence_ids": evidence_ids,
            "valid": valid,
            "checked": checked,
            "unsupported_numbers": unsupported,
            "missing_evidence": missing,
            "explanation": explanation,
        },
        "caveats": [
            "the check is numeric traceability, not factual truth; a number can be cited and still be misused"
        ],
        "summary": ("PASS" if valid else "REJECT") + f": {explanation}",
    }


def write_report(title: str, claims: list[dict], filename: str = "INSIGHTS.md", ledger=None) -> dict:
    """Validate claims and write a traceable Markdown report beside this stage."""
    if ledger is None:
        raise ValueError("write_report needs the harness evidence ledger")
    accepted = []
    rejected = []
    for claim in claims:
        check = validate_claim(str(claim.get("text", "")), list(claim.get("evidence_ids", [])), ledger)["data"]
        record = {**claim, "validation": check}
        (accepted if check["valid"] else rejected).append(record)

    lines = [
        f"# {title}",
        "",
        "_Generated by the data intelligence agent. Every number below is produced by a Python tool "
        "and carries an evidence id._",
        "",
        "## Findings",
        "",
    ]
    for index, claim in enumerate(accepted, start=1):
        action = claim.get("action") or {}
        lines += [
            f"### {index}. {claim.get('text', '')}",
            "",
            f"- **Owner / action:** {action.get('owner', 'n/a')} — {action.get('what', 'n/a')}",
            f"- **When:** {action.get('when', 'n/a')}",
            f"- **Expected impact:** {claim.get('impact', 'n/a')}",
            f"- **Confidence:** {claim.get('confidence', 'n/a')}",
            f"- **Evidence:** {', '.join(claim.get('evidence_ids', []))}",
            f"- **Limits:** {'; '.join(claim.get('limits', [])) or 'none stated'}",
            f"- **Falsifier:** {claim.get('falsifier', 'n/a')}",
            "",
        ]
    if rejected:
        lines += ["## Rejected claims", ""]
        for claim in rejected:
            check = claim["validation"]
            lines += [
                f"- **{claim.get('text', '')}** — {check['explanation']} "
                f"(evidence: {', '.join(claim.get('evidence_ids', []))})",
            ]
        lines += [""]
    lines += ["## Evidence ledger", "", "| id | tool | summary |", "|---|---|---|"]
    for row in ledger.summaries():
        lines.append(f"| {row['evidence_id']} | {row['tool']} | {row['summary']} |")
    lines += ["", "## Limits of this report", ""]
    for caveat in sorted({c for claim in accepted for c in claim.get("limits", [])}):
        lines.append(f"- {caveat}")
    if not accepted:
        lines.append("- no claims passed validation")

    target = Path(__file__).resolve().parent / "reports" / Path(filename).name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "tool": "write_report",
        "data": {
            "path": str(target),
            "written": len(accepted),
            "rejected": [
                {
                    "text": claim.get("text", ""),
                    "explanation": claim["validation"]["explanation"],
                    "evidence_ids": claim.get("evidence_ids", []),
                }
                for claim in rejected
            ],
        },
        "caveats": ["a report is only as good as the evidence ids it cites"],
        "summary": f"{len(accepted)} claim(s) written, {len(rejected)} rejected -> {target}",
    }


def fleet_mix(data_dir: str | None = None) -> dict:
    """Vehicle-type mix overall, by latitude band, and what is left at one-bike stations."""
    panel = _load_panel(data_dir)
    overall: dict[str, int] = {}
    for types in panel["vehicle_types"]:
        for key, value in types.items():
            overall[key] = overall.get(key, 0) + int(value)
    total = sum(overall.values()) or 1
    shares = {key: round(value / total, 4) for key, value in overall.items()}

    frame = panel[["station_id", "name", "lat", "vehicle_types", "num_bikes_available"]].copy()
    frame["lat_band"] = pd.qcut(
        frame["lat"].rank(method="first"), 3, labels=["south", "mid", "north"]
    )
    band_rows = []
    for band, group in frame.groupby("lat_band", observed=True):
        counts: dict[str, int] = {}
        for types in group["vehicle_types"]:
            for key, value in types.items():
                counts[key] = counts.get(key, 0) + int(value)
        band_total = sum(counts.values()) or 1
        band_rows.append(
            {
                "band": str(band),
                "observations": int(len(group)),
                "share": {key: round(value / band_total, 4) for key, value in counts.items()},
            }
        )

    station_counts: dict[int, dict[str, int]] = {}
    station_names: dict[int, str] = {}
    station_lat: dict[int, float] = {}
    for row in panel.itertuples():
        station_counts.setdefault(int(row.station_id), {})
        station_names[int(row.station_id)] = str(row.name)
        station_lat[int(row.station_id)] = float(row.lat)
        for key, value in row.vehicle_types.items():
            station_counts[int(row.station_id)][key] = station_counts[int(row.station_id)].get(key, 0) + int(value)

    dominant = {"bbe": 0, "beryl_bike": 0, "scooter": 0}
    station_mix = []
    for station_id, counts in station_counts.items():
        if not counts:
            continue
        winner = max(counts, key=counts.get)
        dominant[winner] = dominant.get(winner, 0) + 1
        total_station = sum(counts.values()) or 1
        station_mix.append(
            {
                "station_id": station_id,
                "name": station_names[station_id],
                "lat": station_lat[station_id],
                "dominant": winner,
                "ebb_share": round(counts.get("bbe", 0) / total_station, 3),
                "scooter_share": round(counts.get("scooter", 0) / total_station, 3),
                "observations": total_station,
            }
        )
    top_ebike = sorted(
        [row for row in station_mix if row["observations"] >= 5],
        key=lambda row: row["ebb_share"],
        reverse=True,
    )[:10]

    one_bike = panel[panel["num_bikes_available"] == 1]
    last_left: dict[str, int] = {}
    for types in one_bike["vehicle_types"]:
        for key, value in types.items():
            last_left[key] = last_left.get(key, 0) + int(value)

    return _envelope(
        panel,
        "fleet_mix",
        {
            "overall_counts": overall,
            "overall_shares": shares,
            "by_lat_band": band_rows,
            "dominant_type_stations": dominant,
            "one_bike_observations": int(len(one_bike)),
            "last_one_left": last_left,
            "top_ebike_share": top_ebike,
        },
        f"{total} observed vehicles; e-bike share {shares.get('bbe', 0):.1%}",
    )


TOOLS = {
    "list_snapshots": list_snapshots,
    "read_snapshot": read_snapshot,
    "profile_columns": profile_columns,
    "audit_snapshots": audit_snapshots,
    "build_panel": build_panel,
    "net_flow": net_flow,
    "state_transitions": state_transitions,
    "failure_risk": failure_risk,
    "rebalance_plan": rebalance_plan,
    "rank_actions": rank_actions,
    "forecast_gate": forecast_gate,
    "validate_claim": validate_claim,
    "write_report": write_report,
    "fleet_mix": fleet_mix,
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
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'build_panel',
               'description': 'Build the deduplicated station-by-time panel and show cadence, gaps '
                              'and state counts per moment.',
               'parameters': {'type': 'object',
                              'properties': {},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'net_flow',
               'description': 'Signed bike change per station between the first and last snapshot '
                              'in a window: drains vs sinks.',
               'parameters': {'type': 'object',
                              'properties': {'start': {'type': 'string',
                                                       'description': 'ISO timestamp; omit for the '
                                                                      'start of the data.'},
                                             'end': {'type': 'string',
                                                     'description': 'ISO timestamp; omit for the '
                                                                    'end of the data.'},
                                             'top_n': {'type': 'integer',
                                                       'description': 'How many drains and sinks '
                                                                      'to return.',
                                                       'minimum': 1,
                                                       'maximum': 30}},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'state_transitions',
               'description': 'Observed EMPTY/LOW/OK/FULL transition matrix and per-station '
                              'failure probabilities.',
               'parameters': {'type': 'object',
                              'properties': {},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'failure_risk',
               'description': 'Rank stations by how soon a rider is locked out or cannot dock, '
                              'with a reason and extrapolated minutes.',
               'parameters': {'type': 'object',
                              'properties': {'horizon_min': {'type': 'integer',
                                                             'description': 'Risk horizon in '
                                                                            'minutes.',
                                                             'minimum': 5,
                                                             'maximum': 240},
                                             'top_n': {'type': 'integer',
                                                       'description': 'How many stations to '
                                                                      'return.',
                                                       'minimum': 1,
                                                       'maximum': 30}},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'rebalance_plan',
               'description': 'Match surplus stations to deficit stations, nearest first, and cost '
                              'the moves in bikes and km.',
               'parameters': {'type': 'object',
                              'properties': {'max_moves': {'type': 'integer',
                                                           'description': 'Maximum bikes to move.',
                                                           'minimum': 1,
                                                           'maximum': 100}},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'rank_actions',
               'description': 'Turn findings into owner-shaped actions ranked by impact and '
                              'confidence.',
               'parameters': {'type': 'object',
                              'properties': {'top_n': {'type': 'integer',
                                                       'description': 'How many actions to return.',
                                                       'minimum': 1,
                                                       'maximum': 10}},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'forecast_gate',
               'description': 'Check whether a forecast is supportable. Returns insufficient_data '
                              '/ baseline_only / no_skill and why.',
               'parameters': {'type': 'object',
                              'properties': {'horizon_min': {'type': 'integer',
                                                             'description': 'Forecast horizon in '
                                                                            'minutes.',
                                                             'minimum': 5,
                                                             'maximum': 240}},
                              'required': [],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'validate_claim',
               'description': 'Check that every number in a claim appears in the cited evidence '
                              'ids. Returns PASS or REJECT.',
               'parameters': {'type': 'object',
                              'properties': {'claim': {'type': 'string',
                                                       'description': 'The sentence to check.'},
                                             'evidence_ids': {'type': 'array',
                                                              'items': {'type': 'string'},
                                                              'description': 'Evidence ids '
                                                                             'returned by earlier '
                                                                             'tool calls.'}},
                              'required': ['claim', 'evidence_ids'],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'write_report',
               'description': 'Validate claims and write a traceable Markdown report into this '
                              "stage's reports/ folder.",
               'parameters': {'type': 'object',
                              'properties': {'title': {'type': 'string'},
                                             'claims': {'type': 'array',
                                                        'items': {'type': 'object',
                                                                  'properties': {'text': {'type': 'string'},
                                                                                 'evidence_ids': {'type': 'array',
                                                                                                  'items': {'type': 'string'}},
                                                                                 'action': {'type': 'object'},
                                                                                 'impact': {'type': 'string'},
                                                                                 'confidence': {'type': 'string'},
                                                                                 'limits': {'type': 'array',
                                                                                            'items': {'type': 'string'}},
                                                                                 'falsifier': {'type': 'string'}},
                                                                  'required': ['text',
                                                                               'evidence_ids']}},
                                             'filename': {'type': 'string',
                                                          'description': 'Report file name, e.g. '
                                                                         'INSIGHTS.md.'}},
                              'required': ['title', 'claims'],
                              'additionalProperties': False}}},
 {'type': 'function',
  'function': {'name': 'fleet_mix',
               'description': 'Vehicle-type mix overall, by latitude band, and which type is left '
                              'at one-bike stations.',
               'parameters': {'type': 'object',
                              'properties': {},
                              'required': [],
                              'additionalProperties': False}}}]
