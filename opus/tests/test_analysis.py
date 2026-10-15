"""Tests for opus/analysis.py on synthetic snapshots with known behaviour.

Run from the repo root:  uv run pytest opus/tests -q
"""

import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analysis  # noqa: E402

CAP = 10


def _station_rows(t_idx: int, n_st: int, rng, daily: bool):
    rows = []
    for k in range(n_st):
        sid = 1000 + k
        lat = 50.82 + 0.004 * (k % 6)
        lon = -0.20 + 0.012 * (k // 6)
        offline = False
        if k == 0:                       # DRAIN: 10 -> 0 at 1 bike/snapshot
            bikes = max(0, 10 - t_idx)
        elif k == 1:                     # FILL: 0 -> 10
            bikes = min(CAP, t_idx)
        elif k == 2:                     # FROZEN
            bikes = 5
        elif k == 3:                     # OFFLINE
            bikes, offline = 3, True
        elif daily:                      # daily rhythm + noise (for the gated models)
            phase = 2 * np.pi * (t_idx * 5 / 60) / 24 + k
            bikes = int(np.clip(round(5 + 5 * np.sin(phase) + rng.normal(0, 1)), 0, CAP))
        else:
            bikes = int(rng.integers(2, 9))
        rows.append({
            "station_id": sid, "num_bikes_available": bikes, "num_docks_available": 4,   # docks floor
            "is_installed": True, "is_renting": not offline, "is_returning": not offline,
            "last_reported": 0,          # patched below
            "vehicle_types_available": str([{"vehicle_type_id": "bbe", "count": bikes // 2},
                                            {"vehicle_type_id": "beryl_bike", "count": bikes - bikes // 2}]),
            "name": f"Station {k}", "lat": lat, "lon": lon, "capacity": CAP,
        })
    return rows


def make_snapshots(folder, n_snap=12, n_st=30, step_min=5, daily=False, seed=0):
    os.makedirs(folder, exist_ok=True)
    rng = np.random.default_rng(seed)
    t0 = datetime(2026, 10, 13, 7, 0, 0)     # local BST
    for i in range(n_snap):
        t = t0 + timedelta(minutes=step_min * i)
        df = pd.DataFrame(_station_rows(i, n_st, rng, daily))
        utc = pd.Timestamp(t).tz_localize("Europe/London").tz_convert("UTC")
        df["last_reported"] = int(utc.timestamp()) - 120
        df.to_csv(os.path.join(folder, f"DEMO_DATA_{t:%Y%m%d_%H%M%S}.csv"), index=False)
    return folder


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(analysis, "FREE_BIKE_CSV", str(tmp_path / "none.csv"))
    monkeypatch.setattr(analysis, "GEOFENCE_JSON", str(tmp_path / "none.json"))
    monkeypatch.setattr(analysis, "CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def snaps(tmp_path):
    return make_snapshots(str(tmp_path / "snaps"))


def test_load_converts_bst_to_utc(snaps):
    obs = analysis.load_snapshots(snaps)
    assert str(obs["snapshot_utc"].dt.tz) == "UTC"
    assert obs["snapshot_utc"].min() == pd.Timestamp("2026-10-13 06:00:00", tz="UTC")
    assert obs["station_id"].dtype == object or str(obs["station_id"].dtype).startswith("str")
    assert (obs["lag_min"].round() == 2).all()
    assert {"n_bbe", "n_beryl_bike"} <= set(obs.columns)


def test_audit_finds_floor_offline_frozen(snaps):
    obs = analysis.load_snapshots(snaps)
    ids = {i.id: i for i in analysis.audit(obs, analysis.snapshot_table(obs), {})}
    assert ids["A2_docks_floor"].evidence["floor_value"] == 4
    assert "1003" in ids["A4_offline"].stations
    assert "1002" in ids["A4_frozen"].stations
    assert "1003" not in ids["A4_frozen"].stations


def test_station_metrics_slopes(snaps):
    obs = analysis.load_snapshots(snaps)
    m = analysis.station_metrics(obs, 5).set_index("station_id")
    # drain loses 1 bike per 5 min until empty at t=10 -> strongly negative
    assert m.loc["1000", "slope_per_h"] < -5
    assert m.loc["1001", "slope_per_h"] > 5
    assert m.loc["1002", "slope_per_h"] == pytest.approx(0, abs=1e-9)
    assert m.loc["1000", "state_now"] == "EMPTY"
    assert m.loc["1003", "state_now"] == "OFFLINE"


def test_plan_conserves_vehicles_and_respects_van(snaps):
    obs = analysis.load_snapshots(snaps)
    m = analysis.station_metrics(obs, 5)
    m["priority"] = analysis.priority(m)
    moves, route = analysis.plan_rebalancing(m)
    assert len(moves) and len(route)
    picks = route.loc[route["action"] == "pick", "qty"].sum()
    drops = route.loc[route["action"] == "drop", "qty"].sum()
    assert picks == drops == moves["qty"].sum()
    assert route["load_after"].between(0, analysis.VAN_CAPACITY).all()
    assert "1000" in set(moves["to_id"])            # the empty drain gets bikes
    assert "1003" not in set(moves["to_id"]) | set(moves["from_id"])   # offline untouched


def test_gini_and_changepoints():
    assert analysis.gini([1, 1, 1, 1]) == pytest.approx(0)
    assert analysis.gini([0, 0, 0, 10]) == pytest.approx(0.75)
    y = np.r_[np.zeros(30), np.ones(30) * 10] + np.random.default_rng(1).normal(0, 0.5, 60)
    assert analysis.binary_segmentation(y) and abs(analysis.binary_segmentation(y)[0] - 30) <= 2


def test_run_analysis_end_to_end(snaps, tmp_path):
    code, text, out = analysis.run_analysis(snaps, str(tmp_path / "reports"), offline=True, quiet=True)
    assert code == 0, text
    for f in ("index.html", "INSIGHTS.md", "insights.json", "actions.csv", "station_metrics.csv"):
        assert os.path.exists(os.path.join(out, f)), f
    assert "[7/7]" in text


def test_gated_models_run_on_long_data(tmp_path):
    folder = make_snapshots(str(tmp_path / "long"), n_snap=600, n_st=24, daily=True)
    code, text, out = analysis.run_analysis(folder, str(tmp_path / "reports"), offline=True, quiet=True)
    assert code == 0, text
    assert "skipped" not in text.split("[5/7]")[1].split("\n")[0]
    md = open(os.path.join(out, "INSIGHTS.md"), encoding="utf-8").read()
    assert "Failures peak around" in md            # hour profile enabled at 50 h span
