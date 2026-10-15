"""
Opus AI-analyst for the Beryl Brighton bikeshare snapshots.

Pipeline (see OPUS_PLAN.md):
    load_snapshots -> audit (Tier A) -> station_metrics -> statistical (Tier B)
    -> time_series (Tier C) -> optimise (Tier D) -> rank_and_merge + narrate (Tier E)

Design rule: CODE COMPUTES, AI REASONS. Every number in an insight is produced
here and stored in ``Insight.evidence``; optional LLM narration may only reword
those numbers (validated in ``narrate_llm``).

Entry point: ``run_analysis()`` (used by ``app.py --analyse`` and POST /analyse).
"""

from __future__ import annotations

import ast
import glob
import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from os.path import abspath, basename, dirname, exists, join

import numpy as np
import pandas as pd
import requests

import charts

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HERE = dirname(abspath(__file__))
ROOT = dirname(HERE)
DATA_DIR = join(ROOT, "data")
SNAPSHOTS_DIR = join(DATA_DIR, "snapshots")
HISTORY_CSV = join(DATA_DIR, "history.csv")
FREE_BIKE_CSV = join(DATA_DIR, "free_bike_status.csv")
GEOFENCE_JSON = join(DATA_DIR, "geofencing_zones.json")
REPORTS_DIR = join(HERE, "reports")
CACHE_DIR = join(HERE, "cache")
TEMPLATES_DIR = join(HERE, "templates")

LOCAL_TZ = "Europe/London"
DEPOT = (50.8289, -0.1411)          # Brighton station: van start point
ROAD_FACTOR = 1.3                   # haversine -> street distance
VAN_CAPACITY = 20
HORIZON_H = 1.0                     # target-level horizon for rebalancing
SIM_HOURS = 2.0
STALE_MIN = 60
LOW_RANGE_M = 10_000
STATE_ORDER = ["EMPTY", "LOW", "OK", "HIGH", "FULL"]
SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.75, "medium": 0.5, "info": 0.25}

# capability gates: never show a model the data can't support
GATES = {
    "comovement": ("snapshots", 50),
    "changepoints": ("snapshots", 20),
    "anomalies": ("snapshots", 20),
    "hour_profile": ("span_h", 48),
    "forecast": ("snapshots", 200),
}


# ---------------------------------------------------------------------------
# Insight model
# ---------------------------------------------------------------------------
@dataclass
class Insight:
    id: str
    title: str
    category: str               # data_quality | statistical | time_series | optimisation
    severity: str               # critical | high | medium | info
    finding: str
    action: str
    owner: str                  # ops | maintenance | pricing | product | data | planning
    expected_impact: str
    impact_score: float         # 0-1
    confidence: float           # 0-1
    limitations: str = ""
    evidence: dict = field(default_factory=dict)
    stations: list = field(default_factory=list)
    chart_ids: list = field(default_factory=list)
    when: str = ""
    kpi: str = ""
    related: list = field(default_factory=list)

    @property
    def score(self) -> float:
        return SEVERITY_WEIGHT.get(self.severity, 0.25) * self.impact_score * self.confidence


class Log:
    """[n/N]-style console progress, also captured for the web UI."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.lines: list[str] = []

    def __call__(self, msg: str) -> None:
        self.lines.append(msg)
        if not self.quiet:
            print(msg, flush=True)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def dist_matrix(lat_a, lon_a, lat_b, lon_b) -> np.ndarray:
    return haversine_km(np.asarray(lat_a)[:, None], np.asarray(lon_a)[:, None],
                        np.asarray(lat_b)[None, :], np.asarray(lon_b)[None, :])


def names(m: pd.DataFrame, ids, k: int = 5) -> str:
    lookup = m.set_index("station_id")["name"]
    out = [str(lookup.get(i, i)) for i in list(ids)[:k]]
    more = len(list(ids)) - k
    return ", ".join(out) + (f" (+{more} more)" if more > 0 else "")


def gini(x) -> float:
    x = np.sort(np.asarray(x, dtype=float))
    if x.sum() == 0:
        return 0.0
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def classify_state(bikes, fill, offline):
    s = np.select(
        [offline, bikes <= 0, fill < 0.2, fill >= 0.9, fill >= 0.75],
        ["OFFLINE", "EMPTY", "LOW", "FULL", "HIGH"], default="OK")
    return s


def data_confidence(n_snap: int, span_h: float) -> float:
    """0.15-1: how much a time-dependent claim can be trusted given data volume."""
    c = 0.6 * math.log1p(n_snap) / math.log1p(500) + 0.4 * min(span_h / 168, 1)
    return float(np.clip(c, 0.15, 1.0))


def _parse_types(s) -> dict:
    try:
        return {d["vehicle_type_id"]: int(d["count"]) for d in ast.literal_eval(s)}
    except (ValueError, SyntaxError, TypeError, KeyError):
        return {}


# ---------------------------------------------------------------------------
# [1] Load
# ---------------------------------------------------------------------------
STAMP_RE = re.compile(r"(\d{8}_\d{6})")


def load_snapshots(path: str = SNAPSHOTS_DIR, include_history: bool = False) -> pd.DataFrame:
    files = sorted(glob.glob(join(path, "*.csv")))
    frames = []
    for f in files:
        m = STAMP_RE.search(basename(f))
        if not m:
            continue
        df = pd.read_csv(f)
        local = pd.Timestamp(datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"))
        df["snapshot_utc"] = local.tz_localize(LOCAL_TZ, ambiguous=True, nonexistent="shift_forward").tz_convert("UTC")
        df["source"] = basename(f)
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No DEMO_DATA_*.csv snapshots found in {path}")
    obs = pd.concat(frames, ignore_index=True)
    obs["station_id"] = obs["station_id"].astype(str)
    obs = obs.rename(columns={"num_bikes_available": "bikes", "num_docks_available": "docks"})

    if include_history and exists(HISTORY_CSV):
        h = pd.read_csv(HISTORY_CSV)
        h["station_id"] = h["station_id"].astype(str)
        h = h.rename(columns={"num_bikes_available": "bikes", "num_docks_available": "docks"})
        h["snapshot_utc"] = pd.to_datetime(h["snapshot_time"], utc=True)
        static = obs.sort_values("snapshot_utc").groupby("station_id").last()[["name", "lat", "lon", "capacity"]]
        h = h.join(static, on="station_id", how="inner")
        h["source"] = "history.csv"
        for c, v in (("is_installed", True), ("is_renting", True), ("is_returning", True)):
            h[c] = v
        obs = pd.concat([obs, h[[c for c in h.columns if c in obs.columns]]], ignore_index=True)
        obs = obs.drop_duplicates(["station_id", "snapshot_utc"], keep="first")

    # vehicle mix
    if "vehicle_types_available" in obs:
        parsed = obs["vehicle_types_available"].map(_parse_types)
        types = sorted({k for d in parsed for k in d})
        for t in types:
            obs[f"n_{t}"] = parsed.map(lambda d, t=t: d.get(t, 0))
    for c in ("is_installed", "is_renting", "is_returning"):
        obs[c] = obs[c].astype(str).str.lower().isin(["true", "1"])

    if "last_reported" in obs:
        obs["last_reported_utc"] = pd.to_datetime(obs["last_reported"], unit="s", utc=True)
        obs["lag_min"] = (obs["snapshot_utc"] - obs["last_reported_utc"]).dt.total_seconds() / 60

    obs["max_bikes_seen"] = obs.groupby("station_id")["bikes"].transform("max")
    obs["eff_capacity"] = np.maximum(obs["capacity"].fillna(0), obs["max_bikes_seen"]).clip(lower=1)
    obs["fill"] = (obs["bikes"] / obs["eff_capacity"]).clip(0, 1)
    obs["offline"] = ~(obs["is_installed"] & obs["is_renting"])
    obs["state"] = classify_state(obs["bikes"].values, obs["fill"].values, obs["offline"].values)
    return obs.sort_values(["snapshot_utc", "station_id"]).reset_index(drop=True)


def snapshot_table(obs: pd.DataFrame) -> pd.DataFrame:
    """One row per snapshot with payload hash, interval and duplicate flag."""
    g = obs.groupby("snapshot_utc")
    tab = pd.DataFrame({
        "rows": g.size(),
        "hash": g.apply(lambda d: hashlib.md5(
            d.sort_values("station_id")[["station_id", "bikes", "docks"]].to_csv(index=False).encode()).hexdigest(),
            include_groups=False),
    })
    tab["interval_min"] = tab.index.to_series().diff().dt.total_seconds() / 60
    tab["duplicate"] = (tab["hash"] == tab["hash"].shift()) & (tab["interval_min"] < 1)
    return tab


# ---------------------------------------------------------------------------
# [2] Tier A - data forensics
# ---------------------------------------------------------------------------
def audit(obs: pd.DataFrame, snaps: pd.DataFrame, figs: dict) -> list[Insight]:
    out: list[Insight] = []
    n_st = obs["station_id"].nunique()
    names_by_id = obs.groupby("station_id")["name"].last()

    # A1 capacity residual
    resid = obs["bikes"] + obs["docks"] - obs["capacity"]
    per_station = resid.groupby(obs["station_id"]).median()
    bad = per_station[per_station.abs() >= 3]
    figs["ch_audit_residual"] = charts.residual_hist(resid)
    out.append(Insight(
        id="A1_soft_capacity", title="Stated capacity doesn't match bikes + docks",
        category="data_quality", severity="high" if len(bad) > 0.1 * n_st else "medium",
        finding=(f"bikes + docks differs from stated capacity by {resid.min():+.0f} to {resid.max():+.0f}; "
                 f"{len(bad)} of {n_st} stations are off by 3+ at the median. Capacity behaves as a soft limit "
                 f"(virtual bays / overflow)."),
        action=("Use effective capacity = max(stated capacity, observed peak bikes) for all fill-ratio and "
                "'full' calculations; ask Beryl which field is authoritative."),
        owner="data", expected_impact=f"correct fill metrics for {len(bad)} stations",
        impact_score=min(1.0, len(bad) / n_st + 0.3), confidence=0.9,
        evidence={"resid_min": float(resid.min()), "resid_max": float(resid.max()), "stations_off": len(bad)},
        stations=list(bad.index), chart_ids=["ch_audit_residual"], kpi="share of stations with |residual| ≥ 3"))

    # A2 docks floor
    mode_val = int(obs["docks"].mode().iloc[0])
    share = float((obs["docks"] == mode_val).mean())
    zero_docks = float((obs["docks"] == 0).mean())
    if mode_val > 0 and share > 0.3:
        piv = obs.pivot_table(index="station_id", columns="snapshot_utc", values="docks")
        piv = piv.loc[(piv == mode_val).mean(axis=1).sort_values(ascending=False).index]
        piv.index = [names_by_id.get(i, i) for i in piv.index]
        figs["ch_docks_floor"] = charts.docks_heatmap(piv, mode_val, share)
        floor_st = obs.groupby("station_id")["docks"].apply(lambda s: (s == mode_val).mean())
        floor_st = floor_st[floor_st > 0.8]
        out.append(Insight(
            id="A2_docks_floor", title=f"'{mode_val} free docks' is a reporting floor, not a measurement",
            category="data_quality", severity="critical",
            finding=(f"{share:.0%} of all readings report exactly {mode_val} free docks and only {zero_docks:.1%} "
                     f"ever report 0. {len(floor_st)} stations sit on the floor >80% of the time. "
                     f"A 'full station' alert built on docks == 0 would almost never fire."),
            action=(f"Define FULL from bikes (fill ≥ 90% of effective capacity), never from num_docks_available; "
                    f"raise the floor value with Beryl's GBFS team."),
            owner="data", expected_impact="full-station detection that actually works",
            impact_score=0.95, confidence=0.95,
            evidence={"floor_value": mode_val, "floor_share": share, "zero_docks_share": zero_docks,
                      "stations_on_floor": len(floor_st)},
            stations=list(floor_st.index), chart_ids=["ch_docks_floor"],
            kpi="full-station alerts per day (should become non-zero)"))

    # A3 staleness
    if "lag_min" in obs:
        lag = obs.groupby("station_id")["lag_min"].median()
        stale = lag[lag > STALE_MIN].sort_values(ascending=False)
        neg = int((obs["lag_min"] < -5).sum())
        if len(stale):
            out.append(Insight(
                id="A3_stale_stations", title=f"{len(stale)} stations are reporting stale data",
                category="data_quality", severity="high" if len(stale) >= 3 else "medium",
                finding=(f"{len(stale)} stations' last report is > {STALE_MIN} min old at the median "
                         f"(worst: {names_by_id.get(stale.index[0])} at {stale.iloc[0] / 60:.1f} h). Riders see "
                         f"availability that may be wrong."),
                action="Dispatch a technician to check comms/power at these stations; hide their counts in the rider app until fixed.",
                owner="maintenance", expected_impact=f"trustworthy availability at {len(stale)} stations",
                impact_score=min(1.0, 0.3 + len(stale) / n_st * 3), confidence=0.85,
                evidence={"stale_count": len(stale), "worst_lag_h": float(stale.iloc[0] / 60), "neg_lag_rows": neg},
                stations=list(stale.index), chart_ids=["ch_lag"], when="today",
                kpi="stations with lag > 60 min"))

    # A4 dead / offline
    nun = obs.groupby("station_id")["bikes"].nunique()
    offline_all = obs.groupby("station_id")["offline"].mean()
    offline = offline_all[offline_all > 0.5].index
    span_h = (obs["snapshot_utc"].max() - obs["snapshot_utc"].min()).total_seconds() / 3600
    frozen = nun[(nun == 1)].index.difference(offline) if obs["snapshot_utc"].nunique() >= 3 else pd.Index([])
    if len(offline):
        out.append(Insight(
            id="A4_offline", title=f"{len(offline)} stations are offline (not renting)",
            category="data_quality", severity="critical",
            finding=(f"{names(obs.drop_duplicates('station_id'), offline)} reported is_renting/is_installed = False "
                     f"for most of the {span_h:.1f} h window. Every rental attempt there fails."),
            action="Open maintenance tickets now; prioritise by local demand (see priority list).",
            owner="maintenance", expected_impact="restore rentals at offline stations (see lost-demand estimate)",
            impact_score=0.9, confidence=0.9, evidence={"offline_count": len(offline)},
            stations=list(offline), chart_ids=["ch_sparklines"], when="today",
            kpi="offline station-hours per day"))
    if len(frozen):
        out.append(Insight(
            id="A4_frozen", title=f"{len(frozen)} stations never changed",
            category="data_quality", severity="medium",
            finding=(f"{len(frozen)} of {n_st} stations show the identical bike count in every snapshot over "
                     f"{span_h:.1f} h. Either genuinely idle (bays in the wrong place) or a frozen sensor."),
            action=("Cross-check with last_reported: frozen + stale → repair list; frozen + fresh → candidate to "
                    "downsize or relocate bays after a week of data."),
            owner="planning", expected_impact="separate 'broken' from 'unused' stations",
            impact_score=0.5, confidence=0.6 if span_h < 24 else 0.85,
            limitations="Short windows naturally contain quiet stations; re-check over ≥ 7 days.",
            evidence={"frozen_count": len(frozen)}, stations=list(frozen), chart_ids=["ch_sparklines"]))

    # A5 gaps / A6 duplicates
    iv = snaps["interval_min"].dropna()
    if len(iv) >= 2:
        med = float(iv.median())
        gap_rows = snaps[(snaps["interval_min"] > max(15, 3 * med))]
        if len(gap_rows):
            worst = gap_rows["interval_min"].max()
            out.append(Insight(
                id="A5_collector_gaps", title=f"Collector missed {len(gap_rows)} window(s), longest {worst:.0f} min",
                category="data_quality", severity="medium",
                finding=(f"Median snapshot interval is {med:.1f} min but there are {len(gap_rows)} gap(s) of up to "
                         f"{worst:.0f} min. Peaks inside gaps are invisible."),
                action="Run the snapshot collector on a fixed 5-minute schedule and alert on missed ticks.",
                owner="data", expected_impact="complete time series for peak-hour analysis",
                impact_score=0.4, confidence=0.95,
                evidence={"median_interval_min": med, "gaps": len(gap_rows), "max_gap_min": float(worst)},
                chart_ids=["ch_pulse"]))
    dups = int(snaps["duplicate"].sum())
    if dups:
        out.append(Insight(
            id="A6_duplicates", title=f"{dups} duplicate snapshot(s) removed",
            category="data_quality", severity="info",
            finding=f"{dups} snapshot(s) taken < 1 min after the previous one carry an identical payload.",
            action="Deduplicate on payload hash at collection time (done automatically in this analysis).",
            owner="data", expected_impact="unbiased time-weighted statistics", impact_score=0.2, confidence=1.0,
            evidence={"duplicates": dups}))
    return out


# ---------------------------------------------------------------------------
# [3] Station metrics
# ---------------------------------------------------------------------------
def _intervals(obs: pd.DataFrame, cap_min: float) -> pd.DataFrame:
    o = obs.sort_values(["station_id", "snapshot_utc"]).copy()
    o["next_t"] = o.groupby("station_id")["snapshot_utc"].shift(-1)
    o["next_bikes"] = o.groupby("station_id")["bikes"].shift(-1)
    o["next_state"] = o.groupby("station_id")["state"].shift(-1)
    o["dt_min"] = (o["next_t"] - o["snapshot_utc"]).dt.total_seconds() / 60
    o["dt_capped_min"] = o["dt_min"].clip(upper=cap_min)
    o["delta"] = o["next_bikes"] - o["bikes"]
    return o.dropna(subset=["next_t"])


def station_metrics(obs: pd.DataFrame, med_interval: float) -> pd.DataFrame:
    t0 = obs["snapshot_utc"].min()
    o = obs.assign(x=(obs["snapshot_utc"] - t0).dt.total_seconds() / 3600, y=obs["bikes"].astype(float))
    o["xx"], o["xy"], o["yy"] = o["x"] ** 2, o["x"] * o["y"], o["y"] ** 2
    g = o.groupby("station_id")
    s = g[["x", "y", "xx", "xy", "yy"]].sum()
    n = g.size()
    sxx = s["xx"] - s["x"] ** 2 / n
    slope = (s["xy"] - s["x"] * s["y"] / n) / sxx.replace(0, np.nan)
    a = (s["y"] - slope * s["x"]) / n
    sse = (s["yy"] - a * s["y"] - slope * s["xy"]).clip(lower=0)
    se = np.sqrt(sse / (n - 2).clip(lower=1) / sxx.replace(0, np.nan))

    last = obs.sort_values("snapshot_utc").groupby("station_id").last()
    m = pd.DataFrame({
        "name": last["name"], "lat": last["lat"], "lon": last["lon"], "capacity": last["capacity"],
        "eff_capacity": last["eff_capacity"], "bikes_now": last["bikes"], "fill_now": last["fill"],
        "state_now": last["state"], "n_obs": n,
        "mean_fill": g["fill"].mean(), "min_bikes": g["bikes"].min(), "max_bikes": g["bikes"].max(),
        "p95_bikes": g["bikes"].quantile(0.95), "volatility": g["bikes"].std().fillna(0),
        "pct_empty": g["state"].apply(lambda s: (s == "EMPTY").mean()),
        "pct_full": g["state"].apply(lambda s: (s == "FULL").mean()),
        "pct_offline": g["offline"].mean(),
        "slope_per_h": slope.where(n >= 3), "slope_se": se.where(n >= 4),
    })
    if "lag_min" in obs:
        m["lag_median_min"] = g["lag_min"].median()
    type_cols = [c for c in obs.columns if c.startswith("n_")]
    if type_cols:
        tot = obs[type_cols].sum(axis=1).replace(0, np.nan)
        for c in type_cols:
            m[c.replace("n_", "share_")] = (obs[c] / tot).groupby(obs["station_id"]).mean()
        m["ebike_share"] = m.get("share_bbe", pd.Series(0.0, index=m.index)).fillna(0)

    iv = _intervals(obs, cap_min=max(30, 3 * med_interval))
    gi = iv.groupby("station_id")
    hours = gi["dt_capped_min"].sum() / 60
    m["churn_per_h"] = (gi["delta"].apply(lambda d: d.abs().sum()) / hours.replace(0, np.nan)).reindex(m.index).fillna(0)
    dep = iv[iv["state"] != "EMPTY"].groupby("station_id")
    m["departure_rate_h"] = (dep["delta"].apply(lambda d: (-d.clip(upper=0)).sum()) /
                             (dep["dt_capped_min"].sum() / 60).replace(0, np.nan)).reindex(m.index)
    m["empty_h"] = iv[iv["state"] == "EMPTY"].groupby("station_id")["dt_capped_min"].sum().reindex(m.index).fillna(0) / 60
    m["offline_h"] = iv[iv["state"] == "OFFLINE"].groupby("station_id")["dt_capped_min"].sum().reindex(m.index).fillna(0) / 60

    # time to failure (linear extrapolation, only for credible trends)
    t_stat = (m["slope_per_h"] / m["slope_se"].replace(0, np.nan)).abs()
    credible = (t_stat >= 1.5) | (m["slope_se"].isna() & m["slope_per_h"].abs().gt(0))
    drain = (m["slope_per_h"] < -0.5) & credible & (m["bikes_now"] > 0) & (m["state_now"] != "OFFLINE")
    fillup = (m["slope_per_h"] > 0.5) & credible & (m["state_now"] != "FULL") & (m["state_now"] != "OFFLINE")
    m["min_to_empty"] = np.where(drain, m["bikes_now"] / -m["slope_per_h"] * 60, np.nan)
    m["min_to_full"] = np.where(fillup, (0.9 * m["eff_capacity"] - m["bikes_now"]).clip(lower=0) / m["slope_per_h"] * 60, np.nan)
    m.index.name = "station_id"
    return m.reset_index()


def assign_areas(m: pd.DataFrame, k: int = 6) -> pd.Series:
    from sklearn.cluster import KMeans
    k = max(1, min(k, len(m) // 8))
    xy = np.c_[m["lat"], m["lon"] * math.cos(math.radians(50.83))]
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(xy)
    labels = {}
    for c in range(k):
        idx = np.where(km.labels_ == c)[0]
        d = ((xy[idx] - km.cluster_centers_[c]) ** 2).sum(axis=1)
        labels[c] = f"{m['name'].iloc[idx[d.argmin()]]} area"
    return pd.Series([labels[c] for c in km.labels_], index=m.index)


# ---------------------------------------------------------------------------
# [4] Tier B - statistics
# ---------------------------------------------------------------------------
def getis_ord(m: pd.DataFrame, values: pd.Series, k: int = 6) -> np.ndarray:
    d = dist_matrix(m["lat"], m["lon"], m["lat"], m["lon"])
    w = np.zeros_like(d)
    nn = np.argsort(d, axis=1)[:, : k + 1]      # includes self -> Gi*
    for i, row in enumerate(nn):
        w[i, row] = 1.0
    x = values.to_numpy(dtype=float)
    n, xbar = len(x), x.mean()
    s = math.sqrt(max((x ** 2).mean() - xbar ** 2, 1e-12))
    wi = w.sum(axis=1)
    num = w @ x - xbar * wi
    den = s * np.sqrt((n * wi - wi ** 2) / (n - 1))
    return num / den


def fetch_elevation(m: pd.DataFrame, offline: bool, log: Log) -> pd.Series | None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = join(CACHE_DIR, "elevation.csv")
    have = pd.Series(dtype=float, name="elevation_m")
    if exists(cache):
        c = pd.read_csv(cache, dtype={"station_id": str})
        if {"station_id", "elevation_m"} <= set(c.columns):
            have = c.set_index("station_id")["elevation_m"]
    missing = m[~m["station_id"].isin(have.index)]
    if len(missing) and not offline:
        try:
            got = {}
            for i in range(0, len(missing), 100):
                chunk = missing.iloc[i:i + 100]
                locs = "|".join(f"{a:.6f},{b:.6f}" for a, b in zip(chunk["lat"], chunk["lon"]))
                r = requests.get(f"https://api.opentopodata.org/v1/srtm30m?locations={locs}", timeout=20)
                r.raise_for_status()
                for sid, res in zip(chunk["station_id"], r.json()["results"]):
                    got[sid] = res["elevation"]
            have = pd.concat([have, pd.Series(got, dtype=float)])
            pd.DataFrame({"station_id": have.index, "elevation_m": have.values}).to_csv(cache, index=False)
        except (requests.RequestException, KeyError, ValueError) as e:
            log(f"      elevation lookup skipped ({type(e).__name__})")
    if not len(have):
        return None
    return m["station_id"].map(have)


def point_in_poly(lon, lat, ring) -> np.ndarray:
    ring = np.asarray(ring)
    x, y = np.asarray(lon), np.asarray(lat)
    inside = np.zeros(len(x), dtype=bool)
    xj, yj = ring[-1, 0], ring[-1, 1]
    for xi, yi in ring:
        cond = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        inside ^= cond
        xj, yj = xi, yi
    return inside


def in_geofence(lon, lat) -> np.ndarray | None:
    if not exists(GEOFENCE_JSON):
        return None
    with open(GEOFENCE_JSON, encoding="utf-8") as f:
        g = json.load(f)
    feats = g.get("data", {}).get("geofencing_zones", {}).get("features", [])
    inside = np.zeros(len(lon), dtype=bool)
    for ft in feats:
        geom = ft["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            outer = point_in_poly(lon, lat, poly[0])
            for hole in poly[1:]:
                outer &= ~point_in_poly(lon, lat, hole)
            inside |= outer
    return inside


def statistical(obs: pd.DataFrame, m: pd.DataFrame, figs: dict, offline: bool, log: Log) -> list[Insight]:
    out: list[Insight] = []
    latest_t = obs["snapshot_utc"].max()
    latest = obs[obs["snapshot_utc"] == latest_t].merge(m[["station_id", "area"]], on="station_id")
    live = latest[~latest["offline"]]

    # B1 danger zones
    danger = live[(live["fill"] < 0.1) | (live["fill"] > 0.9)]
    figs["ch_fill_violin"] = charts.fill_violin(live)
    out.append(Insight(
        id="B1_danger_zone", title=f"{len(danger) / len(live):.0%} of live stations are in a danger zone",
        category="statistical", severity="high" if len(danger) / len(live) > 0.15 else "medium",
        finding=(f"At the latest snapshot {int((live['fill'] < 0.1).sum())} stations are below 10% fill (rider "
                 f"can't find a bike) and {int((live['fill'] > 0.9).sum())} above 90% (rider can't park), out of "
                 f"{len(live)} live stations."),
        action="Treat the < 10% and > 90% sets as the rebalancing work queue (see route).",
        owner="ops", expected_impact=f"{len(danger)} stations returned to a usable range",
        impact_score=min(1.0, len(danger) / len(live) * 3), confidence=0.8,
        evidence={"danger": len(danger), "live": len(live)}, stations=list(danger["station_id"]),
        chart_ids=["ch_fill_violin"], kpi="share of stations with fill in 10-90%"))

    # B2 inequality
    g_val = gini(live["bikes"])
    srt = np.sort(live["bikes"].to_numpy())[::-1]
    top20 = srt[: max(1, int(round(0.2 * len(srt))))].sum() / max(1, srt.sum())
    total_bikes, total_cap = int(live["bikes"].sum()), int(live["eff_capacity"].sum())
    empty_now = int((live["bikes"] == 0).sum())
    figs["ch_lorenz"] = charts.lorenz(live["bikes"], g_val, top20)
    out.append(Insight(
        id="B2_misallocation", title="The system isn't short of bikes — it's misallocated",
        category="statistical", severity="high",
        finding=(f"{total_bikes} docked vehicles against {total_cap} effective bays ({total_bikes / total_cap:.0%} "
                 f"full overall), yet {empty_now} stations are empty. Gini = {g_val:.2f}; the best-stocked 20% of "
                 f"stations hold {top20:.0%} of all bikes."),
        action="Fix distribution before buying fleet: run the rebalancing plan rather than adding vehicles.",
        owner="ops", expected_impact="fewer empty stations with zero capex",
        impact_score=0.85, confidence=0.85,
        evidence={"total_bikes": total_bikes, "total_cap": total_cap, "gini": g_val, "top20_share": float(top20),
                  "empty_now": empty_now}, chart_ids=["ch_lorenz"], kpi="Gini of bikes across stations"))

    # B3 hot / cold spots
    m["gi_z"] = getis_ord(m, m["mean_fill"])
    cold = m[m["gi_z"] < -1.96].sort_values("gi_z")
    hot = m[m["gi_z"] > 1.96].sort_values("gi_z", ascending=False)
    figs["ch_map_hotspots"] = charts.station_map(
        m, "gi_z", f"Spatial clusters: {len(cold)} stations in starved zones, {len(hot)} in saturated zones",
        "Getis-Ord Gi* z-score of mean fill (k=6 neighbours). Blue = cluster of full, red = cluster of empty",
        colorscale="RdBu", cmid=0, cbar_title="Gi* z")
    if len(cold) or len(hot):
        out.append(Insight(
            id="B3_spatial_clusters", title="Shortages are neighbourhood-wide, not station-specific",
            category="statistical", severity="high" if len(cold) >= 3 else "medium",
            finding=(f"{len(cold)} stations sit in statistically significant cold spots (|z| > 1.96) — whole "
                     f"neighbourhoods starved: {names(m, cold['station_id'])}. {len(hot)} sit in hot spots: "
                     f"{names(m, hot['station_id'])}."),
            action=("Rebalance between zones, not neighbouring stations: walking to the next station won't help "
                    "a rider in a cold spot. Consider a 'return-here' credit inside cold zones."),
            owner="ops", expected_impact="area-level availability rather than whack-a-mole",
            impact_score=0.75, confidence=0.7,
            evidence={"cold": len(cold), "hot": len(hot)},
            stations=list(cold["station_id"]) + list(hot["station_id"]), chart_ids=["ch_map_hotspots"]))

    # B4 fleet mix
    share_cols = [c for c in m.columns if c.startswith("share_")]
    if share_cols:
        from scipy.stats import chi2_contingency
        type_cols = [c.replace("share_", "n_") for c in share_cols]
        ct = latest.groupby("area")[type_cols].sum()
        ct = ct.loc[ct.sum(axis=1) > 0, ct.sum(axis=0) > 0]
        mix = ct.div(ct.sum(axis=1), axis=0)
        mix.columns = [c.replace("n_", "") for c in mix.columns]
        figs["ch_fleet_mix"] = charts.fleet_mix(mix)
        if ct.shape[0] > 1 and ct.shape[1] > 1:
            chi2, p, _, exp = chi2_contingency(ct.values)
            resid = (ct.values - exp) / np.sqrt(exp)
            i, j = np.unravel_index(np.abs(resid).argmax(), resid.shape)
            t = mix.columns[j]
            direction = "over" if resid[i, j] > 0 else "under"
            out.append(Insight(
                id="B4_fleet_mix", title="Vehicle types are not evenly spread",
                category="statistical", severity="medium" if p < 0.05 else "info",
                finding=(f"Fleet mix differs by area (χ² = {chi2:.0f}, p = {p:.3g}). Biggest deviation: "
                         f"{charts.TYPE_LABELS.get(t, t)}s are {direction}-represented in {ct.index[i]} "
                         f"({mix.iloc[i, j]:.0%} vs {ct.iloc[:, j].sum() / ct.values.sum():.0%} network-wide)."),
                action=(f"Make rebalancing type-aware: move {charts.TYPE_LABELS.get(t, t).lower()}s "
                        f"{'out of' if direction == 'over' else 'into'} {ct.index[i]} and track rentals per "
                        f"vehicle type there to confirm the mix is what riders want."),
                owner="ops", expected_impact="right vehicle for the local terrain/trip",
                impact_score=0.5, confidence=0.75 if p < 0.05 else 0.4,
                evidence={"chi2": float(chi2), "p": float(p), "type": t, "area": ct.index[i],
                          "area_share": float(mix.iloc[i, j])}, chart_ids=["ch_fleet_mix"]))

    # B5 elevation
    elev = fetch_elevation(m, offline, log)
    if elev is not None and elev.notna().sum() > 10:
        from scipy.stats import spearmanr
        m["elevation_m"] = elev.values
        ok = m.dropna(subset=["elevation_m"])
        rho, p = spearmanr(ok["elevation_m"], ok["mean_fill"])
        rho_e, p_e = spearmanr(ok["elevation_m"], ok["ebike_share"]) if "ebike_share" in ok else (np.nan, np.nan)
        figs["ch_elevation"] = charts.elevation_scatter(ok, float(rho), float(p))
        high = ok[ok["elevation_m"] > ok["elevation_m"].quantile(0.75)]
        significant = p < 0.05 and rho < 0
        if significant:
            title = "Brighton's hills drain bikes downhill"
            action = ("Stock hill-top stations first each morning and bias e-bikes uphill; a downhill-return "
                      "incentive (credit for ending a trip at a high station) attacks the root cause.")
        else:
            title = "Hills are NOT the main driver (yet) — don't price on it"
            action = ("Hold off on elevation-based pricing: the obvious 'gravity' story isn't supported by this "
                      "data. Re-test after a week; look at commuter corridors (net-flow map) instead.")
        out.append(Insight(
            id="B5_hills", title=title,
            category="statistical", severity="high" if significant else "info",
            finding=(f"Spearman ρ(elevation, mean fill) = {rho:+.2f} (p = {p:.3f}) across {len(ok)} stations "
                     f"({ok['elevation_m'].min():.0f}-{ok['elevation_m'].max():.0f} m). The top-quartile stations "
                     f"(> {high['elevation_m'].min():.0f} m) average {high['mean_fill'].mean():.0%} fill vs "
                     f"{ok['mean_fill'].mean():.0%} overall. ρ(elevation, e-bike share) = {rho_e:+.2f}."),
            action=action,
            owner="pricing", expected_impact="structural fix for gravity-driven drain" if significant
            else "avoid a pricing change the data doesn't justify",
            impact_score=0.7 if significant else 0.35, confidence=0.8 if p < 0.05 else 0.6,
            evidence={"rho": float(rho), "p": float(p), "rho_ebike": float(rho_e),
                      "high_fill": float(high["mean_fill"].mean()), "all_fill": float(ok["mean_fill"].mean())},
            stations=list(high["station_id"]), chart_ids=["ch_elevation"]))

    # B6 archetypes
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    feats = ["mean_fill", "slope_per_h", "churn_per_h", "volatility", "ebike_share", "eff_capacity"]
    feats = [f for f in feats if f in m]
    X = m[feats].fillna(0).to_numpy()
    k = max(2, min(5, len(m) // 20))
    Xs = StandardScaler().fit_transform(X)
    km = KMeans(n_clusters=k, n_init=20, random_state=0).fit(Xs)
    cent = pd.DataFrame(km.cluster_centers_, columns=feats)
    m["archetype"] = _name_archetypes(cent, km.labels_)
    pcs = PCA(n_components=2, random_state=0).fit_transform(Xs)
    pc = pd.DataFrame({"pc1": pcs[:, 0], "pc2": pcs[:, 1], "archetype": m["archetype"], "name": m["name"]})
    prof = m.groupby("archetype")[feats].mean()
    prof = (prof - prof.min()) / (prof.max() - prof.min()).replace(0, 1)
    figs["ch_clusters"] = charts.clusters_pca(pc, prof)
    counts = m["archetype"].value_counts()
    out.append(Insight(
        id="B6_archetypes", title=f"{k} station archetypes need {k} different policies",
        category="statistical", severity="medium",
        finding="Behavioural clustering found: " + "; ".join(f"{a} ({n})" for a, n in counts.items()) + ".",
        action=("Draining → pre-stock before peaks; Filling → scheduled pickups / 'return elsewhere' credit; "
                "Sleepy → candidates for downsizing; Starved → more bays or a new nearby station."),
        owner="planning", expected_impact="policy per archetype instead of one-size-fits-all",
        impact_score=0.5, confidence=0.55, limitations="Archetypes stabilise with ≥ 7 days of data.",
        evidence={"k": k, "counts": counts.to_dict()}, chart_ids=["ch_clusters"]))

    # B7 capacity right-sizing
    m["cap_gap"] = m["p95_bikes"] - m["capacity"]
    over = m[(m["p95_bikes"] <= 0.4 * m["capacity"]) & (m["capacity"] >= 10) & (m["pct_offline"] < 0.5)]
    under = m[(m["max_bikes"] > m["capacity"]) | (m["pct_full"] > 0.3)]
    sel = pd.concat([over.nsmallest(8, "cap_gap"), under.nlargest(8, "cap_gap")]).drop_duplicates("station_id")
    if len(sel):
        figs["ch_capacity_dumbbell"] = charts.capacity_dumbbell(sel)
        spare = int((over["capacity"] - over["p95_bikes"].apply(math.ceil) - 2).clip(lower=0).sum())
        out.append(Insight(
            id="B7_capacity", title="Bays are in the wrong places",
            category="statistical", severity="medium",
            finding=(f"{len(over)} stations never used more than 40% of their bays (≈ {spare} spare bays), while "
                     f"{len(under)} overflowed capacity or were full > 30% of the time: {names(m, under['station_id'])}."),
            action="Move virtual bays (cheap: it's paint and a geofence) from over- to under-provisioned stations.",
            owner="planning", expected_impact=f"up to {spare} bays reallocated at near-zero cost",
            impact_score=0.55, confidence=0.5, limitations="Needs a full week to see each station's true peak.",
            evidence={"over": len(over), "under": len(under), "spare_bays": spare},
            stations=list(over["station_id"]) + list(under["station_id"]), chart_ids=["ch_capacity_dumbbell"]))

    # B8/B9 dockless, battery and geofence (single free_bike_status snapshot)
    if exists(FREE_BIKE_CSV):
        fb = pd.read_csv(FREE_BIKE_CSV)
        fb["station_id"] = pd.to_numeric(fb["station_id"], errors="coerce").astype("Int64").astype("string")
        free = fb[fb["station_id"].isna()].copy()
        sites = pd.DataFrame(columns=["lat", "lon", "n"])
        if len(free):
            d = dist_matrix(free["lat"], free["lon"], m["lat"], m["lon"]).min(1)
            free["dist_m"] = d * 1000
            far = free[free["dist_m"] > 250]
            if len(far) >= 3:
                from sklearn.cluster import DBSCAN
                lab = DBSCAN(eps=0.2 / 6371, min_samples=3, metric="haversine").fit_predict(np.radians(far[["lat", "lon"]]))
                far = far.assign(c=lab)
                sites = far[far["c"] >= 0].groupby("c").agg(lat=("lat", "mean"), lon=("lon", "mean"), n=("lat", "size"))
                sites = sites.sort_values("n", ascending=False)
            if len(sites):
                out.append(Insight(
                    id="B8_new_sites", title=f"{len(sites)} candidate sites for new stations",
                    category="statistical", severity="medium",
                    finding=(f"{len(far)} of {len(free)} free-floating vehicles were left > 250 m from any station; "
                             f"{int(sites['n'].sum())} of them form {len(sites)} tight clusters (DBSCAN, 200 m). "
                             f"Riders are voting with their feet."),
                    action="Survey the cluster centres (map) for new virtual bays.",
                    owner="planning", expected_impact="capture demand currently ending outside the network",
                    impact_score=0.5, confidence=0.45, limitations="Single free_bike_status snapshot; repeat over a week.",
                    evidence={"far": len(far), "free": len(free), "sites": len(sites)}, chart_ids=["ch_dockless"]))
        powered = fb[fb["current_range_meters"].notna()]
        low = powered[powered["current_range_meters"] < LOW_RANGE_M]
        if len(powered):
            figs["ch_battery"] = charts.battery_hist(powered)
            low_st = low["station_id"].dropna().value_counts()
            out.append(Insight(
                id="B9_battery", title=f"{len(low)} powered vehicles need a battery swap",
                category="optimisation", severity="high" if len(low) / len(powered) > 0.1 else "medium",
                finding=(f"{len(low)} of {len(powered)} e-bikes/scooters ({len(low) / len(powered):.0%}) have < "
                         f"{LOW_RANGE_M // 1000} km range. {len(low_st)} stations hold at least one; the top ones: "
                         f"{names(m, low_st.index)}."),
                action="Combine battery swaps with the rebalancing van stops; swap the worst-range vehicles first.",
                owner="ops", expected_impact=f"{len(low)} vehicles back to rentable range",
                impact_score=min(1.0, 0.3 + len(low) / len(powered) * 2), confidence=0.8,
                evidence={"low": len(low), "powered": len(powered)}, stations=list(low_st.index),
                chart_ids=["ch_battery"], when="next van run"))
        figs["ch_dockless"] = charts.dockless_map(free, m, sites.reset_index(drop=True) if len(sites) else sites, low)
        inside = in_geofence(free["lon"].to_numpy(), free["lat"].to_numpy()) if len(free) else None
        if inside is not None and (~inside).sum():
            n_out = int((~inside).sum())
            out.append(Insight(
                id="B10_outside_zone", title=f"{n_out} vehicles are outside every operating zone",
                category="optimisation", severity="medium",
                finding=f"{n_out} free-floating vehicles sit outside all published geofencing zones.",
                action="Add them to the van route for retrieval; check whether the zone boundary needs extending.",
                owner="ops", expected_impact=f"{n_out} stranded vehicles recovered", impact_score=0.4,
                confidence=0.7, evidence={"outside": n_out}, chart_ids=["ch_dockless"]))
    return out


def _name_archetypes(cent: pd.DataFrame, labels: np.ndarray) -> list[str]:
    names_ = {}
    remaining = list(cent.index)

    def take(idx, name):
        if idx in remaining:
            names_[idx] = name
            remaining.remove(idx)

    if "slope_per_h" in cent:
        lo = cent.loc[remaining, "slope_per_h"].idxmin()
        if cent.loc[lo, "slope_per_h"] < -0.3:
            take(lo, "Draining")
        if remaining:
            hi = cent.loc[remaining, "slope_per_h"].idxmax()
            if cent.loc[hi, "slope_per_h"] > 0.3:
                take(hi, "Filling")
    if remaining and "churn_per_h" in cent:
        take(cent.loc[remaining, "churn_per_h"].idxmin(), "Sleepy")
    if remaining:
        take(cent.loc[remaining, "mean_fill"].idxmin(), "Starved")
    if remaining:
        take(cent.loc[remaining, "mean_fill"].idxmax(), "Well-stocked")
    for i in remaining:
        names_[i] = f"Balanced {i}"
    return [names_[l] for l in labels]


# ---------------------------------------------------------------------------
# [5] Tier C - time series
# ---------------------------------------------------------------------------
def gaps_of(snaps: pd.DataFrame) -> list[tuple]:
    iv = snaps["interval_min"]
    med = float(iv.dropna().median()) if iv.notna().any() else 5
    out = []
    ts = list(snaps.index)
    for prev, cur, v in zip(ts[:-1], ts[1:], iv.iloc[1:]):
        if v > max(15, 3 * med):
            out.append((prev, cur))
    return out


def transition_matrix(obs: pd.DataFrame, max_gap_min: float):
    iv = _intervals(obs, cap_min=1e9)
    iv = iv[(iv["dt_min"] <= max_gap_min) & iv["state"].isin(STATE_ORDER) & iv["next_state"].isin(STATE_ORDER)]
    counts = pd.crosstab(iv["state"], iv["next_state"]).reindex(index=STATE_ORDER, columns=STATE_ORDER, fill_value=0)
    probs = counts.div(counts.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    for s in STATE_ORDER:                      # unseen rows: assume persistence
        if counts.loc[s].sum() == 0:
            probs.loc[s, s] = 1.0
    return counts, probs


def binary_segmentation(y: np.ndarray, max_cp: int = 3, min_size: int = 5) -> list[int]:
    y = np.asarray(y, dtype=float)
    sigma2 = (np.median(np.abs(np.diff(y))) * 1.4826) ** 2 / 2 or np.var(y) or 1.0
    pen = 2 * sigma2 * math.log(len(y))

    def best(a, b):
        seg = y[a:b]
        if len(seg) < 2 * min_size:
            return None, 0
        tot = ((seg - seg.mean()) ** 2).sum()
        gains = [(tot - ((seg[:k] - seg[:k].mean()) ** 2).sum() - ((seg[k:] - seg[k:].mean()) ** 2).sum(), a + k)
                 for k in range(min_size, len(seg) - min_size)]
        g, k = max(gains)
        return k, g

    cps, segs = [], [(0, len(y))]
    while len(cps) < max_cp and segs:
        cands = [(best(a, b), (a, b)) for a, b in segs]
        (k, g), (a, b) = max(cands, key=lambda c: c[0][1])
        if k is None or g < pen:
            break
        cps.append(k)
        segs.remove((a, b))
        segs += [(a, k), (k, b)]
    return sorted(cps)


def time_series(obs: pd.DataFrame, m: pd.DataFrame, snaps: pd.DataFrame, figs: dict, ctx: dict) -> list[Insight]:
    out: list[Insight] = []
    dconf = ctx["data_conf"]
    span_h, n_snap = ctx["span_h"], ctx["n_snap"]
    gaps = gaps_of(snaps)

    # C1 pulse
    tot = obs.groupby("snapshot_utc").agg(
        bikes=("bikes", "sum"), empty=("state", lambda s: (s == "EMPTY").sum()),
        full=("state", lambda s: (s == "FULL").sum()), offline=("state", lambda s: (s == "OFFLINE").sum()))
    tot.index = tot.index.tz_convert(LOCAL_TZ)
    figs["ch_pulse"] = charts.pulse(tot, [(a.tz_convert(LOCAL_TZ), b.tz_convert(LOCAL_TZ)) for a, b in gaps])
    d_b, d_e = int(tot["bikes"].iloc[-1] - tot["bikes"].iloc[0]), int(tot["empty"].iloc[-1] - tot["empty"].iloc[0])
    out.append(Insight(
        id="C1_pulse", title=f"Empty stations went {int(tot['empty'].iloc[0])} → {int(tot['empty'].iloc[-1])}",
        category="time_series", severity="high" if d_e > 0 else "info",
        finding=(f"Between {tot.index[0]:%H:%M} and {tot.index[-1]:%H:%M} ({span_h:.1f} h) docked vehicles changed "
                 f"by {d_b:+d} and the number of empty stations by {d_e:+d}. Bikes are leaving stations faster than "
                 f"they're being returned to the right places."),
        action="Schedule the first rebalancing run before the morning peak, not after it.",
        owner="ops", expected_impact="fewer empty stations during peak", impact_score=0.6 if d_e > 0 else 0.2,
        confidence=dconf, limitations=f"{n_snap} snapshots on {tot.index[0]:%a %d %b}; not yet a daily pattern.",
        evidence={"d_bikes": d_b, "d_empty": d_e, "empty_start": int(tot["empty"].iloc[0]),
                  "empty_end": int(tot["empty"].iloc[-1])}, chart_ids=["ch_pulse"], kpi="empty stations at 09:00"))

    # C2 net flow
    figs["ch_netflow_bar"] = charts.netflow_bar(m)
    figs["ch_netflow_map"] = charts.station_map(
        m.assign(slope_per_h=m["slope_per_h"].fillna(0)), "slope_per_h",
        "Net flow map: red stations drain, blue stations fill", "OLS slope of bikes over time (bikes/hour)",
        colorscale="RdBu", cmid=0, fmt="+.1f", cbar_title="bikes/h")
    sig = m[(m["slope_se"].notna()) & ((m["slope_per_h"] / m["slope_se"].replace(0, np.nan)).abs() >= 2)]
    drains = sig[sig["slope_per_h"] < -0.5].sort_values("slope_per_h")
    sinks = sig[sig["slope_per_h"] > 0.5].sort_values("slope_per_h", ascending=False)
    if len(drains) or len(sinks):
        out.append(Insight(
            id="C2_drains_sinks", title=f"{len(drains)} drains and {len(sinks)} sinks drive the imbalance",
            category="time_series", severity="high",
            finding=(f"Statistically significant trends (|t| ≥ 2): drains {names(m, drains['station_id'])} "
                     f"(worst {drains['slope_per_h'].min():+.1f}/h); sinks {names(m, sinks['station_id'])} "
                     f"(worst {sinks['slope_per_h'].max() if len(sinks) else 0:+.1f}/h)."),
            action="Sinks are the free supply for drains: pair them in the van route (done in the plan below).",
            owner="ops", expected_impact="balanced flows with the shortest van km",
            impact_score=0.75, confidence=dconf + (1 - dconf) * 0.3,
            evidence={"drains": len(drains), "sinks": len(sinks)},
            stations=list(drains["station_id"]) + list(sinks["station_id"]),
            chart_ids=["ch_netflow_bar", "ch_netflow_map"]))

    # C3 heatmap
    fill = obs.pivot_table(index="station_id", columns="snapshot_utc", values="fill")
    if fill.shape[1] >= 3 and fill.shape[0] > 2:
        from scipy.cluster.hierarchy import leaves_list, linkage
        order = leaves_list(linkage(fill.fillna(fill.mean(axis=1).mean()).values, "ward"))
        fill = fill.iloc[order]
        fill.columns = [c.tz_convert(LOCAL_TZ) for c in fill.columns]
        fill.index = m.set_index("station_id").loc[fill.index, "name"]
        figs["ch_heatmap"] = charts.fill_heatmap(fill)

    # C4 transitions
    counts, probs = transition_matrix(obs, max_gap_min=max(30, 3 * ctx["med_interval"]))
    if counts.values.sum() > 0:
        figs["ch_transition"] = charts.transition(probs, counts)
        p_low_empty = float(probs.loc["LOW", "EMPTY"])
        steps = max(1, int(round(30 / max(ctx["med_interval"], 1))))
        Pk = np.linalg.matrix_power(probs.values, steps)
        risk = pd.Series(Pk[:, STATE_ORDER.index("EMPTY")], index=STATE_ORDER)
        m["p_empty_30"] = m["state_now"].map(risk).fillna(0)
        n_empty_obs = int(counts.loc["EMPTY"].sum())
        recovered = int(counts.loc["EMPTY", ["LOW", "OK", "HIGH", "FULL"]].sum())
        p_recover = recovered / n_empty_obs if n_empty_obs else float("nan")
        into_empty = counts["EMPTY"].drop("EMPTY")
        feeders = into_empty[into_empty > 0]
        feeder_txt = (", ".join(f"{s} ({int(v)})" for s, v in feeders.items()) if len(feeders)
                      else "none in regularly-spaced snapshots")
        counts_all, _ = transition_matrix(obs, max_gap_min=1e9)
        hidden = int(counts_all["EMPTY"].drop("EMPTY").sum() - feeders.sum())
        if hidden > 0:
            feeder_txt += f" — {hidden} more happened inside collector gaps, unseen"
        sticky = n_empty_obs > 0 and p_recover < 0.3
        # wording follows the numbers, not a script
        if sticky and p_low_empty >= 0.1:
            title = "Stations slide LOW → EMPTY and then stay empty"
            action = ("Trigger the van at LOW (< 20% fill), not at EMPTY: the slide is predictable and empty "
                      "stations don't recover on their own.")
        elif sticky:
            title = "Empty stations never refill on their own"
            action = (f"Only {recovered} of {n_empty_obs} EMPTY observations recovered by the next snapshot: riders "
                      f"don't fix empties, the van must. Restock every EMPTY station on the next run and track "
                      f"how long each stays empty.")
        else:
            title = "Empty stations recover on their own"
            action = ("Riders refill empties quickly here: deprioritise them in the van route and focus on "
                      "stations that stay empty for > 30 min.")
        out.append(Insight(
            id="C4_state_machine", title=title,
            category="time_series", severity="high" if sticky else "medium",
            finding=(f"From {int(counts.values.sum())} observed snapshot-to-snapshot transitions: {recovered} of "
                     f"{n_empty_obs} EMPTY observations recovered (P = {p_recover:.2f}). Transitions into EMPTY came "
                     f"from: {feeder_txt}. P(LOW → EMPTY next snapshot) = {p_low_empty:.2f}; a LOW station has a "
                     f"{risk['LOW']:.0%} chance of being empty within ~30 min."),
            action=action,
            owner="ops", expected_impact="van time spent where riders can't self-correct",
            impact_score=0.7 if sticky else 0.4, confidence=min(0.9, dconf + 0.2),
            limitations="Few transitions per state in a short window; matrix sharpens with every snapshot.",
            evidence={"transitions": int(counts.values.sum()), "p_low_empty": p_low_empty, "p_recover": p_recover,
                      "empty_obs": n_empty_obs, "recovered": recovered, "risk_low_30": float(risk["LOW"])},
            chart_ids=["ch_transition"], kpi="median minutes a station stays EMPTY"))

    # C5 time to failure
    ttf = pd.concat([
        m.dropna(subset=["min_to_empty"]).assign(minutes=lambda d: d["min_to_empty"], kind="empty"),
        m.dropna(subset=["min_to_full"]).assign(minutes=lambda d: d["min_to_full"], kind="full")])
    ttf = ttf[ttf["minutes"] <= 120]
    if len(ttf):
        figs["ch_time_to_empty"] = charts.time_to_failure(ttf[["name", "minutes", "kind"]])
        first = ttf.sort_values("minutes").iloc[0]
        out.append(Insight(
            id="C5_time_to_failure", title=f"{len(ttf)} stations will fail within 2 hours on current trend",
            category="time_series", severity="critical" if (ttf["minutes"] <= 60).sum() >= 3 else "high",
            finding=(f"{int((ttf['kind'] == 'empty').sum())} heading for empty and {int((ttf['kind'] == 'full').sum())} "
                     f"for full. First to go: {first['name']} ({first['kind']} in ~{first['minutes']:.0f} min)."),
            action="Visit in order of minutes-to-failure; the route below already sequences them.",
            owner="ops", expected_impact=f"pre-empt {len(ttf)} failures", when="next 2 hours",
            impact_score=0.85, confidence=dconf + (1 - dconf) * 0.25,
            limitations="Linear extrapolation; demand rarely stays linear through a peak.",
            evidence={"n": len(ttf), "first": first["name"], "first_min": float(first["minutes"])},
            stations=list(ttf["station_id"]), chart_ids=["ch_time_to_empty"]))

    # C6 churn vs net
    figs["ch_churn_net"] = charts.churn_vs_net(m.dropna(subset=["slope_per_h"]))
    busy = m[m["churn_per_h"] >= m["churn_per_h"].quantile(0.8)]
    busy_bad = busy[busy["slope_per_h"] < -0.5]
    if len(busy):
        out.append(Insight(
            id="C6_churn", title=f"{len(busy_bad)} of the busiest stations are also draining",
            category="time_series", severity="medium",
            finding=(f"The busiest 20% of stations ({len(busy)}) move ≥ {busy['churn_per_h'].min():.1f} vehicles/h. "
                     f"{len(busy) - len(busy_bad)} of them are busy but balanced (healthy); {len(busy_bad)} are busy "
                     f"and draining: {names(m, busy_bad['station_id'])}."),
            action="Prioritise busy-and-draining stations: they lose the most rentals per minute empty.",
            owner="ops", expected_impact="protect the highest-value stations", impact_score=0.55,
            confidence=dconf, evidence={"busy": len(busy), "busy_bad": len(busy_bad)},
            stations=list(busy_bad["station_id"]), chart_ids=["ch_churn_net"]))

    # C11 lost demand
    net_rate = float(m["departure_rate_h"].replace(0, np.nan).median()) if m["departure_rate_h"].notna().any() else 0.0
    rate = m["departure_rate_h"].fillna(net_rate).replace(0, net_rate)
    lost = (m["empty_h"] + m["offline_h"]) * rate
    total_lost = float(lost.sum())
    if total_lost > 0:
        top = lost.sort_values(ascending=False)
        top_ids = m.loc[top.index[:5], "station_id"]
        out.append(Insight(
            id="C11_lost_demand", title=f"~{total_lost:.0f} rentals lost to empty or offline stations",
            category="time_series", severity="high",
            finding=(f"Station-hours spent EMPTY ({m['empty_h'].sum():.1f}) and OFFLINE ({m['offline_h'].sum():.1f}) "
                     f"× each station's own departure rate ≈ {0.5 * total_lost:.0f}-{1.5 * total_lost:.0f} missed "
                     f"rentals in the {span_h:.1f} h window. Biggest losers: {names(m, top_ids)}."),
            action="Use this as the business case: every avoided empty hour at these stations is recovered revenue.",
            owner="ops", expected_impact=f"recover up to ~{total_lost:.0f} rentals per comparable window",
            impact_score=0.8, confidence=dconf, limitations="Rough: departure rate estimated from few intervals.",
            evidence={"lost": total_lost, "lo": 0.5 * total_lost, "hi": 1.5 * total_lost,
                      "empty_h": float(m["empty_h"].sum()), "offline_h": float(m["offline_h"].sum())},
            stations=list(top_ids)))

    # ---- gated (need more data) ----
    grid = obs.pivot_table(index="snapshot_utc", columns="station_id", values="bikes").resample("5min").mean().ffill(limit=1)
    if ctx["enabled"]["comovement"]:
        d = grid.diff().dropna(how="all")
        c = d.corr(min_periods=30)
        c = c.mask(np.eye(len(c), dtype=bool))
        pairs = c.stack().sort_values().head(5)
        if len(pairs):
            (a, b), r = pairs.index[0], pairs.iloc[0]
            out.append(Insight(
                id="C7_comovement", title="Origin-destination pairs detected from co-movement",
                category="time_series", severity="medium",
                finding=(f"Strongest anti-correlated pair: {names(m, [a])} loses bikes when {names(m, [b])} gains them "
                         f"(r = {r:.2f}) — a commuting corridor."),
                action="Rebalance along detected corridors in the reverse direction at off-peak.",
                owner="ops", expected_impact="cheaper, predictable rebalancing loops", impact_score=0.5,
                confidence=dconf, evidence={"r": float(r)}, stations=[a, b]))
    if ctx["enabled"]["changepoints"]:
        tot_g = grid.sum(axis=1, min_count=1).dropna()
        cps = binary_segmentation(tot_g.values)
        if cps:
            figs["ch_changepoints"] = charts.series_with_points(
                tot_g.tz_convert(LOCAL_TZ), [tot_g.index[i].tz_convert(LOCAL_TZ) for i in cps],
                f"{len(cps)} regime change(s) in total docked fleet", "Binary segmentation on 5-min totals")
            out.append(Insight(
                id="C9_changepoints", title=f"{len(cps)} regime change(s) detected in the fleet total",
                category="time_series", severity="info",
                finding="Fleet total shifted level at " + ", ".join(f"{tot_g.index[i].tz_convert(LOCAL_TZ):%a %H:%M}" for i in cps) + ".",
                action="Match change points to operations logs (van runs, events, weather) to learn what moves the system.",
                owner="ops", expected_impact="causal understanding of system shifts", impact_score=0.3,
                confidence=dconf, chart_ids=["ch_changepoints"]))
    if ctx["enabled"]["hour_profile"]:
        o = obs.assign(hour=obs["snapshot_utc"].dt.tz_convert(LOCAL_TZ).dt.hour)
        per = o.groupby(["snapshot_utc", "hour"]).agg(bikes=("bikes", "sum"), empty=("state", lambda s: (s == "EMPTY").sum()))
        prof = per.groupby("hour").mean()
        figs["ch_hour_profile"] = charts.hour_profile(prof)
        worst = int(prof["empty"].idxmax())
        out.append(Insight(
            id="C8_daily_rhythm", title=f"Failures peak around {worst:02d}:00",
            category="time_series", severity="high",
            finding=f"Averaged over {span_h / 24:.1f} days, empty stations peak at {prof['empty'].max():.1f} around {worst:02d}:00.",
            action=f"Shift the rebalancing crew so the first run finishes by {max(worst - 1, 0):02d}:00.",
            owner="ops", expected_impact="crew time aligned with failure peak", impact_score=0.7,
            confidence=dconf, chart_ids=["ch_hour_profile"]))
    if ctx["enabled"]["forecast"]:
        res = forecast_failures(grid, m)
        if res and res["brier"] < res["brier_base"]:
            figs["ch_forecast"] = charts.calibration(res["prob"], res["y"], res["brier"], res["brier_base"])
            out.append(Insight(
                id="C10_forecast", title="A 30-minute failure forecast beats 'assume no change'",
                category="time_series", severity="high",
                finding=(f"Gradient-boosted classifier on held-out later data: Brier {res['brier']:.3f} vs persistence "
                         f"{res['brier_base']:.3f} ({(1 - res['brier'] / res['brier_base']):.0%} better)."),
                action="Drive the van dispatch from predicted risk, not current state.",
                owner="ops", expected_impact="act 30 minutes earlier", impact_score=0.8, confidence=dconf,
                evidence={"brier": res["brier"], "brier_base": res["brier_base"]}, chart_ids=["ch_forecast"]))
    return out


def forecast_failures(grid: pd.DataFrame, m: pd.DataFrame, horizon: int = 6) -> dict | None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    cap = m.set_index("station_id")["eff_capacity"].reindex(grid.columns)
    fill = grid.div(cap, axis=1)
    fail = ((grid <= 0) | (fill >= 0.9)).astype(float).where(grid.notna())
    def broadcast(values) -> pd.DataFrame:
        return pd.DataFrame(np.repeat(np.asarray(values)[:, None], fill.shape[1], 1),
                            index=fill.index, columns=fill.columns)

    local = fill.index.tz_convert(LOCAL_TZ)
    feats = {
        "fill": fill, "d1": fill.diff(1), "d3": fill.diff(3), "d6": fill.diff(6),
        "system_fill": broadcast(fill.mean(axis=1).values),
        "hour": broadcast(local.hour + local.minute / 60), "dow": broadcast(local.dayofweek),
        "now_fail": fail,
    }
    y = fail.shift(-horizon)
    long = pd.concat({k: v.stack(future_stack=True) for k, v in feats.items()} | {"y": y.stack(future_stack=True)}, axis=1).dropna()
    if len(long) < 500 or long["y"].nunique() < 2:
        return None
    t = long.index.get_level_values(0)
    cut = t.sort_values()[int(len(t) * 0.7)]
    tr, te = long[t < cut], long[t >= cut]
    if te["y"].nunique() < 2 or tr["y"].nunique() < 2:
        return None
    X = [c for c in long.columns if c != "y"]
    clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=0).fit(tr[X], tr["y"])
    prob = clf.predict_proba(te[X])[:, 1]
    yv = te["y"].to_numpy()
    return {"prob": prob, "y": yv, "brier": float(((prob - yv) ** 2).mean()),
            "brier_base": float(((te["now_fail"].to_numpy() - yv) ** 2).mean())}


# ---------------------------------------------------------------------------
# [6] Tier D - optimisation
# ---------------------------------------------------------------------------
def target_levels(m: pd.DataFrame) -> pd.Series:
    slope = m["slope_per_h"].fillna(0)
    t = (m["eff_capacity"] * 0.5 - slope * HORIZON_H).round()
    return t.clip(lower=1, upper=(m["eff_capacity"] - 1).clip(lower=1)).astype(int)


def priority(m: pd.DataFrame) -> pd.Series:
    tte = m[["min_to_empty", "min_to_full"]].min(axis=1)
    p_fail = np.where(m["state_now"].isin(["EMPTY", "FULL"]), 1.0, np.exp(-tte.fillna(1e6) / 60))
    p_fail = np.maximum(p_fail, m.get("p_empty_30", pd.Series(0, index=m.index)).fillna(0))
    demand = 0.3 + 0.7 * m["churn_per_h"].rank(pct=True).fillna(0)
    return pd.Series(p_fail * demand, index=m.index).where(m["state_now"] != "OFFLINE", 0)


def plan_rebalancing(m: pd.DataFrame, max_vehicles: int = 2 * VAN_CAPACITY) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Plan ONE realistic van run: the highest-priority deficits up to ``max_vehicles`` (default 2 loads)."""
    from scipy.optimize import linprog
    m = m.copy()
    m["target"] = target_levels(m)
    live = m["state_now"] != "OFFLINE"
    need_mask = live & (m["state_now"].isin(["EMPTY", "LOW"]) | (m["min_to_empty"] <= 90)) & (m["target"] > m["bikes_now"])
    needs = m[need_mask].assign(qty=lambda d: d["target"] - d["bikes_now"],
                                rank_key=lambda d: (d["state_now"] == "EMPTY").astype(int) + d.get("priority", 0))
    needs = needs.sort_values("rank_key", ascending=False)
    needs = needs[needs["qty"].cumsum().shift(fill_value=0) < max_vehicles].copy()
    overflow = needs["qty"].sum() - max_vehicles
    if overflow > 0:                       # trim the last (lowest-priority) stop to fit the budget
        needs.iloc[-1, needs.columns.get_loc("qty")] -= overflow
    sink_mask = live & (m["state_now"].isin(["FULL", "HIGH"]) | (m["min_to_full"] <= 90))
    donor_mask = live & ~need_mask & ((m["bikes_now"] - m["target"] >= 3) | (sink_mask & (m["bikes_now"] > m["target"])))
    donors = m[donor_mask].assign(qty=lambda d: d["bikes_now"] - d["target"],
                                  sink=lambda d: sink_mask[d.index])
    if needs.empty or donors.empty:
        return pd.DataFrame(), pd.DataFrame()
    D = dist_matrix(donors["lat"], donors["lon"], needs["lat"], needs["lon"]) * ROAD_FACTOR
    D = D * np.where(donors["sink"].to_numpy()[:, None], 0.6, 1.0)  # prefer draining sinks
    nd, nn = D.shape
    demand = needs["qty"].to_numpy(float)
    supply = donors["qty"].to_numpy(float)
    if supply.sum() < demand.sum():
        demand = np.floor(demand * supply.sum() / demand.sum())
    A_ub = np.zeros((nd, nd * nn)); A_eq = np.zeros((nn, nd * nn))
    for i in range(nd):
        A_ub[i, i * nn:(i + 1) * nn] = 1
    for j in range(nn):
        A_eq[j, j::nn] = 1
    res = linprog(D.ravel(), A_ub=A_ub, b_ub=supply, A_eq=A_eq, b_eq=demand, bounds=(0, None), method="highs")
    if not res.success:
        return pd.DataFrame(), pd.DataFrame()
    x = np.round(res.x.reshape(nd, nn)).astype(int)
    moves = [{"from_id": donors["station_id"].iloc[i], "from": donors["name"].iloc[i],
              "to_id": needs["station_id"].iloc[j], "to": needs["name"].iloc[j], "qty": int(x[i, j]),
              "km": float(D[i, j] / (0.6 if donors["sink"].iloc[i] else 1.0))}
             for i in range(nd) for j in range(nn) if x[i, j] > 0]
    moves = pd.DataFrame(moves)
    pick = moves.groupby("from_id")["qty"].sum()
    drop = moves.groupby("to_id")["qty"].sum()
    return moves, route_van(m.set_index("station_id"), pick.to_dict(), drop.to_dict())


def route_van(st: pd.DataFrame, pick: dict, drop: dict, cap: int = VAN_CAPACITY) -> pd.DataFrame:
    pos, load, stops = DEPOT, 0, []
    pick, drop = dict(pick), dict(drop)
    while any(v > 0 for v in drop.values()):
        opts = []
        if load < cap:
            opts += [("pick", s) for s, v in pick.items() if v > 0]
        if load > 0:
            opts += [("drop", s) for s, v in drop.items() if v > 0]
        if not opts:
            break
        dists = [haversine_km(pos[0], pos[1], st.at[s, "lat"], st.at[s, "lon"]) for _, s in opts]
        act, s = opts[int(np.argmin(dists))]
        if act == "pick":
            q = min(pick[s], cap - load); pick[s] -= q; load += q
        else:
            q = min(drop[s], load); drop[s] -= q; load -= q
        stops.append({"action": act, "station_id": s, "qty": int(q)})
        pos = (st.at[s, "lat"], st.at[s, "lon"])
    stops = _two_opt(_merge_stops(stops), st, cap)
    df = pd.DataFrame(_merge_stops(stops))
    if df.empty:
        return df
    df["name"] = df["station_id"].map(st["name"])
    df["lat"] = df["station_id"].map(st["lat"])
    df["lon"] = df["station_id"].map(st["lon"])
    df["seq"] = np.arange(1, len(df) + 1)
    df["load_after"] = np.cumsum(np.where(df["action"] == "pick", df["qty"], -df["qty"]))
    lat = np.r_[DEPOT[0], df["lat"]]; lon = np.r_[DEPOT[1], df["lon"]]
    df["leg_km"] = haversine_km(lat[:-1], lon[:-1], lat[1:], lon[1:]) * ROAD_FACTOR
    return df


def _merge_stops(stops: list[dict]) -> list[dict]:
    """Collapse consecutive identical (action, station) stops into one."""
    out: list[dict] = []
    for s in stops:
        if out and out[-1]["action"] == s["action"] and out[-1]["station_id"] == s["station_id"]:
            out[-1] = out[-1] | {"qty": out[-1]["qty"] + s["qty"]}
        else:
            out.append(dict(s))
    return out


def _route_len(stops, st) -> float:
    lat = [DEPOT[0]] + [st.at[s["station_id"], "lat"] for s in stops]
    lon = [DEPOT[1]] + [st.at[s["station_id"], "lon"] for s in stops]
    return float(haversine_km(np.array(lat[:-1]), np.array(lon[:-1]), np.array(lat[1:]), np.array(lon[1:])).sum())


def _feasible(stops, cap) -> bool:
    load = 0
    for s in stops:
        load += s["qty"] if s["action"] == "pick" else -s["qty"]
        if load < 0 or load > cap:
            return False
    return True


def _two_opt(stops, st, cap, iters: int = 4):
    best, best_len = stops, _route_len(stops, st)
    for _ in range(iters):
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 2, len(best) + 1):
                cand = best[:i] + best[i:j][::-1] + best[j:]
                if _feasible(cand, cap):
                    L = _route_len(cand, st)
                    if L < best_len - 1e-6:
                        best, best_len, improved = cand, L, True
        if not improved:
            break
    return best


def simulate(m: pd.DataFrame, moves: pd.DataFrame) -> pd.DataFrame:
    live = m[m["state_now"] != "OFFLINE"].set_index("station_id")
    b0 = live["bikes_now"].astype(float)
    b1 = b0.copy()
    if len(moves):
        b1 = b1.sub(moves.groupby("from_id")["qty"].sum(), fill_value=0).add(moves.groupby("to_id")["qty"].sum(), fill_value=0)
        b1 = b1.reindex(b0.index)
    slope = live["slope_per_h"].fillna(0)
    cap = live["eff_capacity"]
    rows = []
    for t in np.arange(0, SIM_HOURS * 60 + 1, 5):
        def fails(b):
            x = (b + slope * t / 60).clip(lower=0, upper=cap)
            return int(((x < 0.5) | (x >= 0.9 * cap)).sum())
        rows.append({"minutes": t, "failing_no_plan": fails(b0), "failing_with_plan": fails(b1)})
    return pd.DataFrame(rows)


def optimise(m: pd.DataFrame, figs: dict, ctx: dict) -> tuple[list[Insight], pd.DataFrame, pd.DataFrame]:
    out: list[Insight] = []
    m["target"] = target_levels(m)
    m["priority"] = priority(m)
    moves, route = plan_rebalancing(m)
    if len(route):
        km = float(route["leg_km"].sum())
        moved = int(route.loc[route["action"] == "drop", "qty"].sum())
        fixed = moves["to_id"].nunique()
        figs["ch_route"] = charts.route_map(m, route, DEPOT, km, moved)
        sim = simulate(m, moves)
        figs["ch_before_after"] = charts.before_after(sim)
        saved_h = float((sim["failing_no_plan"] - sim["failing_with_plan"]).sum() * 5 / 60)
        empty_now = int((m["state_now"] == "EMPTY").sum())
        fixed_empty = int(m[m["station_id"].isin(moves["to_id"]) & (m["state_now"] == "EMPTY")].shape[0])
        live = m["state_now"] != "OFFLINE"
        backlog = int((live & (m["state_now"].isin(["EMPTY", "LOW"]) | (m["min_to_empty"] <= 90))
                       & (m["target"] > m["bikes_now"])).sum())
        out.append(Insight(
            id="D2_rebalancing_plan", title=f"Van run #1: move {moved} vehicles in {len(route)} stops to fix {fixed} stations",
            category="optimisation", severity="critical",
            finding=(f"Min-cost transport LP (supply = surplus above target, demand = deficit below target, "
                     f"{HORIZON_H:.0f} h horizon) then a capacity-{VAN_CAPACITY} van route (nearest-neighbour + 2-opt): "
                     f"{moved} vehicles, {len(route)} stops, ~{km:.1f} km from Brighton station. Covers the "
                     f"highest-priority {fixed} of {backlog} stations that need bikes, restocking {fixed_empty} of "
                     f"{empty_now} empty stations. Simulated saving: ~{saved_h:.1f} station-hours of "
                     f"failure over {SIM_HOURS:.0f} h."),
            action="Dispatch the van with the stop list in rebalancing_plan.csv (pick-ups green, drops red on the map).",
            owner="ops", expected_impact=f"~{saved_h:.1f} station-hours of failure avoided", when="now",
            impact_score=0.95, confidence=0.5 + 0.5 * ctx["data_conf"],
            limitations="Simulation assumes current net flows persist; street distances approximated (×1.3).",
            evidence={"moved": moved, "stops": len(route), "km": km, "fixed": int(fixed),
                      "fixed_empty": fixed_empty, "empty_now": empty_now, "saved_station_h": saved_h},
            stations=list(moves["to_id"].unique()), chart_ids=["ch_route", "ch_before_after"],
            kpi="empty station-hours per day"))

    # D3/D7 priority + maintenance
    top = m[m["priority"] > 0].nlargest(10, "priority")
    if len(top):
        out.append(Insight(
            id="D3_priority", title="Top-10 stations to protect right now",
            category="optimisation", severity="high",
            finding=("Priority = P(failure soon) × demand weight (churn rank). Top: " +
                     ", ".join(f"{r['name']} ({r['priority']:.2f})" for _, r in top.head(5).iterrows()) + "."),
            action="Use this as the dispatcher's watch-list; refresh every 5 minutes with new snapshots.",
            owner="ops", expected_impact="attention where riders get burned most", impact_score=0.6,
            confidence=0.4 + 0.5 * ctx["data_conf"], evidence={"top": top["name"].head(10).tolist()},
            stations=list(top["station_id"])))

    # D6 incentives
    if "gi_z" in m:
        bonus = m[(m["gi_z"] < -1.5) | (m["slope_per_h"] < -1)]
        credit = m[(m["gi_z"] > 1.5) | (m["slope_per_h"] > 1)]
        if len(bonus) and len(credit):
            out.append(Insight(
                id="D6_incentives", title="Let riders do the rebalancing",
                category="optimisation", severity="medium",
                finding=(f"{len(bonus)} stations in drain/cold zones ({names(m, bonus['station_id'], 3)}) and "
                         f"{len(credit)} in fill/hot zones ({names(m, credit['station_id'], 3)})."),
                action=("Pilot dynamic pricing: a ride credit for ending trips at the drain/cold stations, and a "
                        "small 'return elsewhere' nudge at the hot ones. Measure against van km."),
                owner="pricing", expected_impact="fewer van km per rebalanced bike", impact_score=0.55,
                confidence=0.45, limitations="Effect size unknown until A/B tested.",
                stations=list(bonus["station_id"]) + list(credit["station_id"])))
    return out, moves, route


# ---------------------------------------------------------------------------
# [7] Tier E - rank, merge, narrate
# ---------------------------------------------------------------------------
def rank_and_merge(insights: list[Insight]) -> list[Insight]:
    ranked = sorted(insights, key=lambda i: i.score, reverse=True)
    kept: list[Insight] = []
    for ins in ranked:
        s = set(ins.stations)
        parent = None
        if s and ins.category != "data_quality":
            for k in kept:
                ks = set(k.stations)
                if k.category != "data_quality" and ks and len(s & ks) / len(s | ks) >= 0.6:
                    parent = k
                    break
        if parent:
            parent.related.append(ins.id)
        kept.append(ins)
    return kept


def narrate(insights: list[Insight], ctx: dict, skipped: dict) -> str:
    L = ["# AI Analyst Report — Beryl Brighton bikeshare", ""]
    L.append(f"Data: {ctx['n_files']} snapshot files, {ctx['n_snap']} unique snapshots, {ctx['n_stations']} stations, "
             f"{ctx['start']:%a %d %b %Y %H:%M} → {ctx['end']:%H:%M} {ctx['tz']} ({ctx['span_h']:.1f} h). "
             f"Data confidence: {ctx['data_conf']:.0%}.")
    L.append("")
    L.append("Every number below was computed by code (`opus/analysis.py`); the reasoning and actions are the "
             "analyst's interpretation of those numbers.")
    L += ["", "## Executive summary — do these first", ""]
    for i, ins in enumerate([x for x in insights if x.category != "data_quality"][:5], 1):
        L.append(f"{i}. **{ins.title}** — {ins.action} _(owner: {ins.owner}; impact: {ins.expected_impact})_")
    dq = [x for x in insights if x.category == "data_quality"][:3]
    if dq:
        L += ["", "Before trusting any dashboard built on this feed:", ""]
        L += [f"- **{x.title}** — {x.action}" for x in dq]
    titles = {"data_quality": "1. Data forensics — questioning the data", "statistical": "2. Statistical X-ray",
              "time_series": "3. Time-series story", "optimisation": "4. Optimisation — what to do"}
    for cat, head in titles.items():
        items = [x for x in insights if x.category == cat]
        if not items:
            continue
        L += ["", f"## {head}", ""]
        for x in items:
            L += [f"### {x.title}", "",
                  f"- **Severity:** {x.severity} · **confidence:** {x.confidence:.0%} · **owner:** {x.owner}"
                  + (f" · **when:** {x.when}" if x.when else ""),
                  f"- **Finding:** {x.finding}",
                  f"- **Action:** {x.action}",
                  f"- **Expected impact:** {x.expected_impact}"]
            if x.kpi:
                L.append(f"- **How we'll know:** {x.kpi}")
            if x.limitations:
                L.append(f"- **Limitations:** {x.limitations}")
            if x.chart_ids:
                L.append(f"- **Evidence:** " + ", ".join(f"[{c}](charts/{c}.html)" for c in x.chart_ids))
            if x.related:
                L.append(f"- **Related:** {', '.join(x.related)}")
            L.append("")
    L += ["## What I would need to be more certain", ""]
    for k, why in skipped.items():
        L.append(f"- **{k}** not run: {why}")
    L.append(f"- Run the snapshot collector every 5 minutes for ≥ 7 days; data confidence is {ctx['data_conf']:.0%} now.")
    L.append("- Trip-level data (origin/destination) would replace flow proxies with real demand.")
    L.append("- Weather and event calendars would explain change points and peaks.")
    return "\n".join(L) + "\n"


def narrate_llm(insights: list[Insight], ctx: dict, log: Log) -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        log("      LLM narration skipped: OPENROUTER_API_KEY not set")
        return None
    payload = [{k: v for k, v in asdict(i).items() if k not in ("stations",)} for i in insights[:10]]
    facts = json.dumps({"context": {k: str(v) for k, v in ctx.items() if k != "enabled"}, "insights": payload}, default=str)
    prompt = ("You are a senior transport-operations analyst briefing the Brighton bikeshare operations manager. "
              "Using ONLY the numbers in this JSON (never introduce new numbers), write a one-page Markdown briefing: "
              "group findings by root cause, give a diagnosis, then a numbered action plan (who/what/where/when, "
              "expected impact, how to measure), then confidence and what data would raise it.\n\n" + facts)
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=120,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": os.environ.get("OPUS_LLM_MODEL", "anthropic/claude-sonnet-4.5"),
                                "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        log(f"      LLM narration failed ({type(e).__name__}); using template")
        return None
    allowed = set(re.findall(r"\d+(?:\.\d+)?", facts))
    allowed |= {str(i) for i in range(0, 25)}            # list numbering, hours
    used = set(re.findall(r"\d+(?:\.\d+)?", text))
    rogue = sorted(n for n in used if n not in allowed and n.rstrip("0").rstrip(".") not in allowed)
    if len(rogue) > 3:
        log(f"      LLM narration rejected: {len(rogue)} numbers not in evidence (e.g. {rogue[:5]})")
        return None
    return text


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def build_context(obs: pd.DataFrame, snaps: pd.DataFrame, n_files: int) -> dict:
    start, end = obs["snapshot_utc"].min(), obs["snapshot_utc"].max()
    span_h = (end - start).total_seconds() / 3600
    n_snap = int(snaps.shape[0])
    iv = snaps["interval_min"].dropna()
    enabled, skipped = {}, {}
    for k, (kind, thr) in GATES.items():
        have = n_snap if kind == "snapshots" else span_h
        enabled[k] = have >= thr
        if not enabled[k]:
            unit = "snapshots" if kind == "snapshots" else "hours of span"
            skipped[k] = f"needs ≥ {thr} {unit}, have {have:.0f}"
    return {"n_files": n_files, "n_snap": n_snap, "n_stations": int(obs["station_id"].nunique()),
            "start": start.tz_convert(LOCAL_TZ), "end": end.tz_convert(LOCAL_TZ), "tz": "Europe/London",
            "span_h": span_h, "med_interval": float(iv.median()) if len(iv) else 5.0,
            "data_conf": data_confidence(n_snap, span_h), "enabled": enabled, "skipped": skipped}


def run_analysis(snap_dir: str = SNAPSHOTS_DIR, out_root: str = REPORTS_DIR, include_history: bool = False,
                 llm: bool = False, offline: bool = False, quiet: bool = False, log: Log | None = None) -> tuple[int, str, str | None]:
    """Run the full pipeline. Returns (exit_code, console_text, report_dir)."""
    log = log or Log(quiet)
    try:
        figs: dict = {}
        n_files = len(glob.glob(join(snap_dir, "*.csv")))
        obs = load_snapshots(snap_dir, include_history)
        snaps = snapshot_table(obs)
        dup_t = snaps.index[snaps["duplicate"]]
        obs_ts = obs[~obs["snapshot_utc"].isin(dup_t)]
        snaps_ts = snapshot_table(obs_ts)
        ctx = build_context(obs_ts, snaps_ts, n_files)
        log(f"[1/7] Loading snapshots ........ {n_files} files, {len(obs)} rows, {ctx['n_stations']} stations, "
            f"{ctx['start']:%d %b %H:%M}-{ctx['end']:%H:%M} {ctx['tz']}")

        ins = audit(obs, snaps, figs)
        log(f"[2/7] Auditing data ............ {len(ins)} issues "
            f"({sum(i.severity == 'critical' for i in ins)} critical)")

        m = station_metrics(obs_ts, ctx["med_interval"])
        m["area"] = assign_areas(m)
        flagged = set(m.loc[(m["pct_offline"] > 0.5) | (m["max_bikes"] == m["min_bikes"]), "station_id"])
        bikes_piv = obs_ts.pivot_table(index="snapshot_utc", columns="station_id", values="bikes")
        bikes_piv.index = bikes_piv.index.tz_convert(LOCAL_TZ)
        figs["ch_sparklines"] = charts.sparklines(bikes_piv, dict(zip(m["station_id"], m["name"])), flagged)
        if "lag_median_min" in m:
            figs["ch_lag"] = charts.lag_strip(m)
        log(f"[3/7] Station metrics .......... {len(m)} stations, data confidence {ctx['data_conf']:.0%}")

        b = statistical(obs_ts, m, figs, offline, log)
        ins += b
        log(f"[4/7] Statistical analysis ..... {len(b)} insights")

        c = time_series(obs_ts, m, snaps_ts, figs, ctx)
        ins += c
        skipped_txt = f" (skipped: {', '.join(ctx['skipped'])})" if ctx["skipped"] else ""
        log(f"[5/7] Time-series analysis ..... {len(c)} insights{skipped_txt}")

        d, moves, route = optimise(m, figs, ctx)
        ins += d
        if len(route):
            log(f"[6/7] Optimisation ............. {int(moves['qty'].sum())} vehicles, {len(route)} stops, "
                f"{route['leg_km'].sum():.1f} km")
        else:
            log("[6/7] Optimisation ............. no rebalancing needed")

        ins = rank_and_merge(ins)
        out_dir = write_report(out_root, obs_ts, m, ins, figs, moves, route, ctx, llm, log)
        log(f"[7/7] Writing report ........... {out_dir}")
        log(f"      {len(ins)} insights, {len(figs)} charts → open {join(out_dir, 'index.html')}")
        return 0, log.text, out_dir
    except Exception as e:  # noqa: BLE001 - CLI/cron wants a clean exit code
        import traceback
        log(f"ERROR: {type(e).__name__}: {e}")
        log(traceback.format_exc())
        return 1, log.text, None


def write_report(out_root, obs, m, ins, figs, moves, route, ctx, llm, log) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = join(out_root, stamp)
    cdir = join(out, "charts")
    os.makedirs(cdir, exist_ok=True)

    for cid, fig in figs.items():
        fig.write_html(join(cdir, f"{cid}.html"), include_plotlyjs="directory", full_html=True)
        with open(join(cdir, f"{cid}.json"), "w", encoding="utf-8") as f:
            f.write(fig.to_json())
    from plotly.offline import get_plotlyjs
    with open(join(out, "plotly.min.js"), "w", encoding="utf-8") as f:
        f.write(get_plotlyjs())

    m.to_csv(join(out, "station_metrics.csv"), index=False)
    if len(moves):
        moves.to_csv(join(out, "rebalancing_moves.csv"), index=False)
    if len(route):
        route.to_csv(join(out, "rebalancing_plan.csv"), index=False)
    pd.DataFrame([{"rank": n, "id": i.id, "severity": i.severity, "owner": i.owner, "when": i.when,
                   "action": i.action, "where": names(m, i.stations, 8) if i.stations else "",
                   "expected_impact": i.expected_impact, "kpi": i.kpi, "confidence": round(i.confidence, 2),
                   "score": round(i.score, 3)} for n, i in enumerate(ins, 1)]).to_csv(join(out, "actions.csv"), index=False)
    with open(join(out, "insights.json"), "w", encoding="utf-8") as f:
        json.dump({"context": {k: (str(v) if not isinstance(v, (int, float, dict)) else v) for k, v in ctx.items()},
                   "insights": [asdict(i) | {"score": i.score} for i in ins]}, f, indent=2, default=str)

    md = narrate(ins, ctx, ctx["skipped"])
    brief = narrate_llm(ins, ctx, log) if llm else None
    if brief:
        md = md.replace("## Executive summary", "## AI briefing (LLM-narrated, numbers validated)\n\n" + brief +
                        "\n\n## Executive summary", 1)
    with open(join(out, "INSIGHTS.md"), "w", encoding="utf-8") as f:
        f.write(md)
    html = render_report(ins, ctx, {k: v.to_json() for k, v in figs.items()}, route, "plotly.min.js", brief)
    with open(join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    return out


def render_report(ins, ctx, figs_json: dict, route: pd.DataFrame, plotly_src: str, brief: str | None,
                  analyse_button: bool = False) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(["html"]))
    tpl = env.get_template("report.html")
    ins_d = [asdict(i) | {"score": i.score} if isinstance(i, Insight) else i for i in ins]
    return tpl.render(insights=ins_d, ctx=ctx, figs_json=figs_json,
                      route=route.to_dict("records") if len(route) else [],
                      plotly_src=plotly_src, brief=brief, analyse_button=analyse_button,
                      generated=datetime.now().strftime("%d %b %Y %H:%M"))


def latest_report_dir(out_root: str = REPORTS_DIR) -> str | None:
    dirs = sorted(d for d in glob.glob(join(out_root, "*")) if exists(join(d, "insights.json")))
    return dirs[-1] if dirs else None


def clean_reports(keep: int = 5, out_root: str = REPORTS_DIR) -> None:
    dirs = sorted(d for d in glob.glob(join(out_root, "*")) if os.path.isdir(d))
    for d in dirs[:-keep]:
        shutil.rmtree(d, ignore_errors=True)
