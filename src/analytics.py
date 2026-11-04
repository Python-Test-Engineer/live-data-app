"""Analytics for the Brighton Bikeshare snapshot.

Every function returns plain Python values so the output can be written to JSON
and handed to the ``make-html-dashboard`` builder. The dashboard payload maps
these results onto the skill's data contract; the full analytics result is also
saved for future charts or notebooks.
"""

from __future__ import annotations

from html import escape
from typing import Any

import numpy as np
import pandas as pd

try:
    from .utils import jsonable
except ImportError:  # direct script import
    from utils import jsonable

PALETTE = ["#d97757", "#6f9a6a", "#b9862f", "#8c877c", "#c9633f", "#5f8f8a", "#a06a9a"]


def _round(value: Any, digits: int = 1) -> float:
    number = float(value)
    if np.isnan(number) or np.isinf(number):
        return 0.0
    return round(number, digits)


def _share(part: float, whole: float) -> float:
    return _round((float(part) / float(whole) * 100) if whole else 0.0, 1)


def kpi_cards(df: pd.DataFrame, report: dict[str, Any]) -> list[dict[str, Any]]:
    stations = len(df)
    bikes = int(df["num_bikes_available"].sum())
    docks = int(df["num_docks_available"].sum())
    capacity = int(df["capacity"].sum())
    empty = int(df["is_empty"].sum())
    offline = int((~df["is_available"]).sum())
    ebikes = int(df["bikes_ebike"].sum())
    utilisation = _share(bikes, capacity)
    return [
        {
            "label": "Total stations",
            "value": f"{stations:,}",
            "unit": "",
            "tone": "default",
            "hint": f"{int(df['is_renting'].sum()):,} renting · {offline} unavailable",
        },
        {
            "label": "Bikes available",
            "value": f"{bikes:,}",
            "unit": "",
            "tone": "good" if bikes else "warn",
            "hint": f"{ebikes:,} e-bikes · {_share(ebikes, bikes)}% of fleet",
        },
        {
            "label": "Free docks",
            "value": f"{docks:,}",
            "unit": "",
            "tone": "default",
            "hint": f"{capacity:,} total capacity",
        },
        {
            "label": "Utilisation",
            "value": f"{utilisation:.1f}",
            "unit": "%",
            "tone": "warn" if utilisation > 75 else "default",
            "hint": f"{bikes:,} bikes / {capacity:,} capacity",
        },
        {
            "label": "Empty stations",
            "value": f"{empty:,}",
            "unit": "",
            "tone": "warn" if empty else "good",
            "hint": f"{_share(empty, stations)}% of stations have no bikes",
        },
        {
            "label": "Quality warnings",
            "value": f"{len(report.get('issues', [])):,}",
            "unit": "",
            "tone": "bad" if report.get("issues") else "good",
            "hint": "Checks needing review; see Data quality",
        },
    ]


def station_profile(df: pd.DataFrame) -> dict[str, Any]:
    """Availability profile, sorted low-to-high utilisation."""
    ordered = df.sort_values(["utilisation_pct_calc", "num_bikes_available"], ascending=[True, True])
    labels = [str(index) for index in range(1, len(ordered) + 1)]
    return {
        "title": "Station availability profile",
        "sub": f"{len(ordered)} stations · sorted by utilisation",
        "labels": labels,
        "series": [
            {
                "name": "Bikes",
                "color": PALETTE[0],
                "area": True,
                "values": [int(value) for value in ordered["num_bikes_available"].fillna(0)],
            },
            {
                "name": "Free docks",
                "color": PALETTE[1],
                "area": False,
                "values": [int(value) for value in ordered["num_docks_available"].fillna(0)],
            },
        ],
    }


def vehicle_mix(df: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        ("Classic", "bikes_classic", PALETTE[0]),
        ("E-bike", "bikes_ebike", PALETTE[1]),
        ("E-scooter", "bikes_escooter", PALETTE[2]),
        ("Cargo", "bikes_cargo", PALETTE[3]),
        ("Other", "bikes_other", PALETTE[4]),
    ]
    items = []
    for label, column, color in columns:
        value = int(df[column].sum()) if column in df else 0
        if value > 0:
            items.append({"label": label, "value": value, "color": color})
    if not items:
        items = [{"label": "No bikes", "value": 1, "color": "#8c877c"}]
    return items


def zone_summary(df: pd.DataFrame) -> list[dict[str, Any]]:
    grouped = (
        df.groupby("zone_name", dropna=False)
        .agg(
            stations=("station_id", "count"),
            capacity=("capacity", "sum"),
            bikes=("num_bikes_available", "sum"),
            docks=("num_docks_available", "sum"),
            empty=("is_empty", "sum"),
            offline=("is_available", lambda series: int((~series.astype(bool)).sum())),
        )
        .reset_index()
    )
    grouped["utilisation_pct"] = np.where(
        grouped["capacity"] > 0,
        grouped["bikes"] / grouped["capacity"] * 100,
        0.0,
    )
    grouped = grouped.sort_values(["bikes", "stations"], ascending=False)
    rows = []
    for index, row in grouped.iterrows():
        rows.append({
            "label": str(row["zone_name"]),
            "stations": int(row["stations"]),
            "capacity": int(row["capacity"]),
            "bikes": int(row["bikes"]),
            "docks": int(row["docks"]),
            "empty": int(row["empty"]),
            "offline": int(row["offline"]),
            "utilisation_pct": _round(row["utilisation_pct"]),
            "color": PALETTE[index % len(PALETTE)],
        })
    return rows


def utilisation_bands(df: pd.DataFrame) -> list[dict[str, Any]]:
    util = df["utilisation_pct_calc"].fillna(0)
    bands = [
        ("0%", util <= 0),
        ("1–25%", (util > 0) & (util <= 25)),
        ("26–50%", (util > 25) & (util <= 50)),
        ("51–75%", (util > 50) & (util <= 75)),
        ("76–100%", (util > 75) & (util <= 100)),
        (">100%", util > 100),
    ]
    return [{"label": label, "count": int(mask.sum())} for label, mask in bands]


def status_counts(df: pd.DataFrame) -> list[dict[str, Any]]:
    counts = df["station_status"].value_counts()
    return [{"label": str(label), "count": int(count)} for label, count in counts.items()]


def top_stations(df: pd.DataFrame, n: int = 15) -> list[dict[str, Any]]:
    ordered = df.sort_values(["num_bikes_available", "utilisation_pct_calc"], ascending=False).head(n)
    return [
        {
            "name": str(row["station_name"]),
            "zone": str(row["zone_name"]),
            "bikes": int(row["num_bikes_available"]),
            "docks": int(row["num_docks_available"]),
            "capacity": int(row["capacity"]),
            "utilisation_pct": _round(row["utilisation_pct_calc"]),
            "status": str(row["station_status"]),
        }
        for _, row in ordered.iterrows()
    ]


def outliers(df: pd.DataFrame) -> dict[str, Any]:
    over = df[df["is_utilisation_over_100"]].sort_values("utilisation_pct_calc", ascending=False)
    mismatch = df[df["is_capacity_mismatch"]].sort_values("capacity_delta", ascending=False)
    empty = df[df["is_empty"]].sort_values("capacity", ascending=False)
    offline = df[~df["is_available"]]

    def rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "station": str(row["station_name"]),
                "zone": str(row["zone_name"]),
                "bikes": int(row["num_bikes_available"]),
                "docks": int(row["num_docks_available"]),
                "capacity": int(row["capacity"]),
                "utilisation_pct": _round(row["utilisation_pct_calc"]),
            }
            for _, row in frame.head(10).iterrows()
        ]

    return {
        "over_capacity": rows(over),
        "capacity_mismatch": rows(mismatch),
        "empty": rows(empty),
        "offline": rows(offline),
    }


def correlations(df: pd.DataFrame) -> dict[str, Any]:
    pairs = {
        "capacity_vs_bikes": ("capacity", "num_bikes_available"),
        "capacity_vs_docks": ("capacity", "num_docks_available"),
        "bikes_vs_docks": ("num_bikes_available", "num_docks_available"),
    }
    result: dict[str, Any] = {}
    for name, (left, right) in pairs.items():
        if {left, right}.issubset(df.columns):
            value = df[[left, right]].corr(numeric_only=True).iloc[0, 1]
            result[name] = _round(value, 3)
    return result


def insights(df: pd.DataFrame, report: dict[str, Any], zones: list[dict[str, Any]]) -> list[str]:
    stations = len(df)
    empty = int(df["is_empty"].sum())
    offline = int((~df["is_available"]).sum())
    over = int(df["is_utilisation_over_100"].sum())
    mismatch = int(df["is_capacity_mismatch"].sum())
    age = int(df["station_feed_age_seconds"].max()) if "station_feed_age_seconds" in df else 0
    busiest_zone = zones[0] if zones else None
    items = [
        "Run the collector on a schedule to build a time series; this single snapshot cannot show change over time.",
        f"Rebalance the {empty} empty stations before the next commute peak.",
    ]
    if offline:
        items.append(f"Check the {offline} stations that are not available before publishing them as usable capacity.")
    if over:
        items.append(f"Investigate {over} stations reporting more bikes than capacity; clamp or correct their source values.")
    if mismatch:
        items.append(f"Reconcile {mismatch} capacity mismatches between <code>capacity</code> and <code>total_docks_reported</code>.")
    if age > 600:
        items.append(f"Refresh the feed: the oldest station status is <code>{age}s</code> old.")
    if busiest_zone:
        items.append(
            f"<strong>{escape(str(busiest_zone['label']))}</strong> holds the most bikes "
            f"({busiest_zone['bikes']:,}) at {busiest_zone['utilisation_pct']}% utilisation."
        )
    return items


def activity_feed(df: pd.DataFrame, report: dict[str, Any], top: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feed = [
        {
            "time": "ETL",
            "text": f"Snapshot loaded: <strong>{int(len(df))} stations</strong> from <code>{escape(report.get('source_file', 'snapshot'))}</code>",
            "where": "extract + transform",
        }
    ]
    for issue in report.get("issues", [])[:5]:
        feed.append({
            "time": "DQ",
            "text": f"<strong>{escape(str(issue['name']))}</strong> — {escape(str(issue['detail']))}",
            "where": "quality check",
        })
    for row in top[:4]:
        feed.append({
            "time": "TOP",
            "text": f"<strong>{escape(row['name'])}</strong> has {row['bikes']} bikes and {row['docks']} free docks",
            "where": f"{escape(row['zone'])} · {row['utilisation_pct']}%",
        })
    return feed


def quality_notes(df: pd.DataFrame, report: dict[str, Any]) -> list[dict[str, Any]]:
    notes = []
    for issue in report.get("issues", [])[:4]:
        notes.append({
            "title": str(issue["name"]).replace("_", " ").title(),
            "body": escape(str(issue["detail"])),
        })
    if not notes:
        notes.append({
            "title": "Checks passed",
            "body": "Schema, uniqueness, capacity, coordinate, and freshness checks all passed.",
        })
    notes.append({
        "title": "Snapshot context",
        "body": (
            f"Captured <code>{escape(str(report.get('snapshot_utc')))}</code> from "
            f"<code>{escape(str(report.get('system')))}</code>. "
            f"Feed age <code>{report.get('feed_age_seconds', 0)}s</code>."
        ),
    })
    return notes


def dashboard_payload(df: pd.DataFrame, report: dict[str, Any], analytics: dict[str, Any]) -> dict[str, Any]:
    stations = len(df)
    bikes = int(df["num_bikes_available"].sum())
    docks = int(df["num_docks_available"].sum())
    capacity = int(df["capacity"].sum())
    utilisation = _share(bikes, capacity)
    empty_count = int(df["is_empty"].sum())
    over_count = int(df["is_utilisation_over_100"].sum())
    zones = analytics["zones"]
    vehicle = analytics["vehicle_mix"]
    snapshot = str(report.get("snapshot_utc") or "unknown snapshot")
    source_file = str(report.get("source_file") or "snapshot.csv")

    # Table: busiest stations plus the empties worth rebalancing.
    top = analytics["top_stations"]
    empties = df[df["is_empty"]].sort_values("capacity", ascending=False).head(8)
    rows = list(top)
    seen = {row["name"] for row in rows}
    for _, row in empties.iterrows():
        if row["station_name"] in seen:
            continue
        rows.append({
            "name": str(row["station_name"]),
            "zone": str(row["zone_name"]),
            "bikes": int(row["num_bikes_available"]),
            "docks": int(row["num_docks_available"]),
            "capacity": int(row["capacity"]),
            "utilisation_pct": _round(row["utilisation_pct_calc"]),
            "status": str(row["station_status"]),
        })
        seen.add(row["station_name"])
    rows = sorted(rows, key=lambda item: item["utilisation_pct"], reverse=True)[:20]

    status_map = {"offline": "bad", "full": "warn", "busy": "warn", "empty": "warn", "low": "good", "balanced": "good"}
    label_map = {"offline": "offline", "full": "full", "busy": "busy", "empty": "empty", "low": "low", "balanced": "healthy"}
    table_rows = [
        {
            "name": row["name"],
            "bikes": row["bikes"],
            "docks": row["docks"],
            "capacity": row["capacity"],
            "status": status_map.get(row["status"], "good"),
            "statusLabel": label_map.get(row["status"], row["status"]),
        }
        for row in rows
    ]

    trend = analytics["station_profile"]
    trend.update({
        "breakdownTitle": "Vehicle mix",
        "breakdownTotal": f"{sum(item['value'] for item in vehicle):,}",
        "breakdownUnit": "bikes",
        "breakdown": vehicle,
        "breakdownBarsTitle": "Bikes by zone",
        "breakdownBars": [
            {"label": zone["label"], "value": zone["bikes"], "color": zone["color"]}
            for zone in zones[:6]
        ],
        "histogram": {
            "title": "Utilisation distribution",
            "sub": "station count per band",
            "bins": analytics["utilisation_bands"],
        },
    })

    return {
        "page": {
            "title": "Brighton Bikeshare · Live dashboard",
            "eyebrow": "Brighton cycle hire · GBFS snapshot",
            "h1": "Brighton Bikeshare dashboard",
            "lede": (
                f"ETL and analytics over {stations} stations from {source_file}. "
                f"{bikes:,} bikes and {docks:,} free docks at {utilisation:.1f}% network utilisation."
            ),
            "meta": [
                snapshot.replace("T", " ")[:16] + " UTC",
                f"{stations} stations",
                f"{bikes:,} bikes",
                f"{docks:,} free docks",
                f"{utilisation:.1f}% utilised",
            ],
            "tocTitle": "Brighton Bikeshare",
            "sideSub": "Live GBFS snapshot analysed with the ETL + analytics pipeline in src/.",
            "sideFoot": f"Source <code>{escape(source_file)}</code><br>{stations} stations · {capacity:,} capacity",
        },
        "overview": {
            "lede": (
                f"This snapshot captures {stations} stations with {bikes:,} bikes and {docks:,} free docks. "
                f"Utilisation is {utilisation:.1f}% when weighted by capacity, and {report.get('feed_age_seconds', 0)}s of feed age is carried through to the quality checks."
            ),
            "callout": (
                f"<strong>Live snapshot.</strong> {stations} stations, {bikes:,} bikes, and {docks:,} free docks. "
                f"The KPI utilisation is capacity-weighted ({utilisation:.1f}%), which differs from the mean of station-level percentages. "
                f"{over_count} stations report more bikes than capacity and {empty_count} are empty — see the actions below."
            ),
            "notes": analytics["quality_notes"][:3],
        },
        "sections": [
            {"id": "overview", "title": "Overview", "level": 2},
            {"id": "kpis", "title": "KPI cards", "level": 2},
            {"id": "trend", "title": "Charts", "level": 2},
            {"id": "stations", "title": "Station table", "level": 2},
            {"id": "activity", "title": "Pipeline activity", "level": 2},
            {"id": "quality", "title": "Data quality", "level": 2},
            {"id": "next", "title": "Recommended actions", "level": 2},
        ],
        "kpis": analytics["kpis"],
        "trend": trend,
        "stations": table_rows,
        "stationsNote": "Top stations by bikes plus the empties most worth rebalancing. Hover charts for capacity and zone.",
        "activity": analytics["activity"],
        "notes": analytics["quality_notes"],
        "next": analytics["insights"],
        "colophon": f"ETL + analytics over <code>{escape(source_file)}</code> &middot; {stations} stations &middot; generated by <code>src/pipeline.py</code>",
        "chat": {
            "endpoint": "/api/chat",
            "kicker": "Dashboard assistant",
            "title": "Ask the dashboard",
            "placeholder": "Ask about a station, zone, or metric…",
            "greeting": (
                f"Ask about this snapshot: {stations} stations, {bikes:,} bikes, {docks:,} free docks. "
                "Answers use the dashboard data only."
            ),
            "foot": "Uses the current model · snapshot data only",
            "suggestions": [
                "Which stations are empty right now?",
                "Where are the most bikes concentrated?",
                "Which stations should be rebalanced first?",
                "What data quality issues matter most?",
            ],
        },
    }


def analyse(df: pd.DataFrame, report: dict[str, Any]) -> dict[str, Any]:
    """Compute every chart dataset and analysis table."""
    zones = zone_summary(df)
    top = top_stations(df)
    result = {
        "snapshot": report.get("snapshot_utc"),
        "system": report.get("system"),
        "kpis": kpi_cards(df, report),
        "station_profile": station_profile(df),
        "vehicle_mix": vehicle_mix(df),
        "zones": zones,
        "utilisation_bands": utilisation_bands(df),
        "status_counts": status_counts(df),
        "top_stations": top,
        "outliers": outliers(df),
        "correlations": correlations(df),
        "activity": activity_feed(df, report, top),
        "quality_notes": quality_notes(df, report),
        "insights": insights(df, report, zones),
    }
    return jsonable(result)
