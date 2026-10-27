"""Generate the six STEP_N teaching folders.

Each folder is self-contained: PLAN.md, README.md, agent.py, harness.py, tools.py.
The code is cumulative — STEP_2 adds time-series tools to STEP_1's auditor, and
so on. Run `uv run python tools/build_steps.py` from the repo root to rebuild.

The generated folders are the deliverable; this file is the reproducible source.
"""

from __future__ import annotations

import pprint
import sys
import textwrap
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# harness.py — identical in every stage
# ---------------------------------------------------------------------------

HARNESS = r'''"""The harness around the model: tools, evidence ledger, bounded loop, LLM.

The model never executes Python. It can only ask the harness to call a named
tool. The harness validates the name, runs the function, stamps the result with
an evidence id, logs it, and hands it back.

Read this file after the talk: it is the part that makes the agent auditable.
"""

from __future__ import annotations

import inspect
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    """Raised when the optional language model cannot be reached."""


class Ledger:
    """Every tool result gets an id, so prose can be traced back to a number."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        eid = f"ev_{len(self.items) + 1:03d}"
        payload["evidence_id"] = eid
        self.items[eid] = payload
        return payload

    def by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        return [self.items[i] for i in ids if i in self.items]

    def numbers(self, ids: list[str] | None = None) -> list[float]:
        """Flatten every number in the selected evidence (or all of it)."""
        payloads = self.by_ids(ids) if ids is not None else list(self.items.values())
        found: list[float] = []

        def walk(value: Any) -> None:
            if isinstance(value, bool):
                return
            if isinstance(value, (int, float)):
                found.append(float(value))
            elif isinstance(value, dict):
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)

        walk(payloads)
        return found

    def text(self, ids: list[str] | None = None) -> str:
        payloads = self.by_ids(ids) if ids is not None else list(self.items.values())
        return json.dumps(payloads, default=str, ensure_ascii=False)

    def summaries(self) -> list[dict[str, str]]:
        return [
            {
                "evidence_id": eid,
                "tool": str(p.get("tool", "")),
                "summary": str(p.get("summary", "")),
            }
            for eid, p in self.items.items()
        ]


@dataclass
class Harness:
    """A tiny, bounded tool-calling harness."""

    tools: dict[str, Callable[..., dict[str, Any]]]
    specs: list[dict[str, Any]]
    max_steps: int = 8
    verbose: bool = True
    ledger: Ledger = field(default_factory=Ledger)
    transcript: list[dict[str, Any]] = field(default_factory=list)

    def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self.tools:
            raise KeyError(f"unknown tool: {name!r}; available: {sorted(self.tools)}")
        fn = self.tools[name]
        kwargs = dict(args or {})
        # Two tools need the ledger to resolve evidence ids. Keep that out of
        # the public JSON schema so the model cannot forge it.
        if "ledger" in inspect.signature(fn).parameters:
            kwargs["ledger"] = self.ledger

        started = time.perf_counter()
        payload = fn(**kwargs)
        if not isinstance(payload, dict):
            payload = {"data": payload}
        payload.setdefault("tool", name)
        payload.setdefault("caveats", [])
        payload = self.ledger.record(payload)
        payload["_ms"] = int((time.perf_counter() - started) * 1000)
        self.transcript.append(payload)

        if self.verbose:
            print(f"\n[tool] {name}({json.dumps(args or {}, default=str)})")
            print(f"       -> {payload['evidence_id']} in {payload['_ms']} ms")
            summary = payload.get("summary")
            if summary:
                print(f"       {summary}")
        return payload

    def reset(self) -> None:
        self.ledger = Ledger()
        self.transcript.clear()


# ---------------------------------------------------------------------------
# optional model layer
# ---------------------------------------------------------------------------


def _env_values() -> dict[str, str]:
    """Read the repo-root .env without adding a dotenv dependency."""
    root = Path(__file__).resolve().parents[1]
    values: dict[str, str] = {}
    for path in (root / ".env", Path.cwd() / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def _normalise_model(name: str) -> str:
    if "/" in name:
        return name
    prefixes = (
        ("gpt", "openai/"),
        ("o1", "openai/"),
        ("o3", "openai/"),
        ("o4", "openai/"),
        ("claude", "anthropic/"),
        ("gemini", "google/"),
        ("deepseek", "deepseek/"),
        ("llama", "meta-llama/"),
        ("mistral", "mistralai/"),
        ("qwen", "qwen/"),
    )
    for prefix, vendor in prefixes:
        if name.startswith(prefix):
            return vendor + name
    return "openrouter/auto"


def have_api_key() -> bool:
    env = _env_values()
    return bool(env.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_KEY"))


class LLMClient:
    """Minimal OpenRouter client. Tool calling is the OpenAI-compatible format."""

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        env = _env_values()
        self.api_key = api_key or env.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_KEY")
        if not self.api_key:
            raise LLMError("No OPENROUTER_API_KEY / OPENROUTER_KEY found in .env or environment.")
        raw_model = model or env.get("OPENROUTER_MODEL") or env.get("MODEL") or "openrouter/auto"
        self.model = _normalise_model(raw_model)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://craigwestai.com/",
                "X-Title": "Brighton data intelligence agent talk",
            },
            json=body,
            timeout=120,
        )
        if response.status_code != 200:
            raise LLMError(f"OpenRouter {response.status_code}: {response.text[:500]}")
        return response.json()


def run_llm(
    harness: Harness,
    system: str,
    question: str,
    client: LLMClient,
    max_steps: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """The agent loop: model -> tool call -> harness -> result -> model."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    for _ in range(max_steps or harness.max_steps):
        data = client.chat(messages, harness.specs)
        message = data["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            return message.get("content") or "", messages

        messages.append(
            {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": calls,
            }
        )
        for call in calls:
            name = call["function"]["name"]
            raw = call["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {}
            result = harness.call(name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": name,
                    "content": json.dumps(result, default=str),
                }
            )
    return "Stopped: step limit reached before the model produced an answer.", messages
'''


# ---------------------------------------------------------------------------
# tools.py — common data layer, then one block per tool
# ---------------------------------------------------------------------------

COMMON = r'''"""Tools for __STAGE_TITLE__.

The language model never computes a number. Every function here returns a
structured payload with its own window, caveats and summary. The harness adds
an evidence id.

Data: __DATA_NOTE__
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
'''


TOOL_BLOCKS: dict[str, str] = {}


TOOL_BLOCKS["list_snapshots"] = r'''
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
'''


TOOL_BLOCKS["read_snapshot"] = r'''
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
'''


TOOL_BLOCKS["profile_columns"] = r'''
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
'''


TOOL_BLOCKS["audit_snapshots"] = r'''
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
'''


TOOL_BLOCKS["build_panel"] = r'''
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
'''


TOOL_BLOCKS["net_flow"] = r'''
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
'''


TOOL_BLOCKS["state_transitions"] = r'''
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
'''


TOOL_BLOCKS["failure_risk"] = r'''
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
'''


TOOL_BLOCKS["rebalance_plan"] = r'''
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
'''


TOOL_BLOCKS["rank_actions"] = r'''
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
'''


TOOL_BLOCKS["forecast_gate"] = r'''
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
'''


TOOL_BLOCKS["validate_claim"] = r'''
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
'''


TOOL_BLOCKS["write_report"] = r'''
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
'''


TOOL_BLOCKS["fleet_mix"] = r'''
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
'''


# ---------------------------------------------------------------------------
# JSON schemas handed to the model
# ---------------------------------------------------------------------------


def _spec(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


TOOL_SPECS: dict[str, dict] = {
    "list_snapshots": _spec(
        "list_snapshots",
        "List every snapshot file with its observation time, feed lag, counts and duplicate status.",
    ),
    "read_snapshot": _spec(
        "read_snapshot",
        "Read one snapshot: schema, sample rows and key counts.",
        {
            "source_file": {"type": "string", "description": "File name; omit for the latest snapshot."},
            "rows": {"type": "integer", "description": "Sample rows (1-20).", "minimum": 1, "maximum": 20},
        },
    ),
    "profile_columns": _spec(
        "profile_columns",
        "Profile every column: type, nulls, numeric range or top values.",
    ),
    "audit_snapshots": _spec(
        "audit_snapshots",
        "Audit data quality before analysis: docks floor, soft capacity, duplicates, feed lag, outages, gaps.",
    ),
    "build_panel": _spec(
        "build_panel",
        "Build the deduplicated station-by-time panel and show cadence, gaps and state counts per moment.",
    ),
    "net_flow": _spec(
        "net_flow",
        "Signed bike change per station between the first and last snapshot in a window: drains vs sinks.",
        {
            "start": {"type": "string", "description": "ISO timestamp; omit for the start of the data."},
            "end": {"type": "string", "description": "ISO timestamp; omit for the end of the data."},
            "top_n": {"type": "integer", "description": "How many drains and sinks to return.", "minimum": 1, "maximum": 30},
        },
    ),
    "state_transitions": _spec(
        "state_transitions",
        "Observed EMPTY/LOW/OK/FULL transition matrix and per-station failure probabilities.",
    ),
    "failure_risk": _spec(
        "failure_risk",
        "Rank stations by how soon a rider is locked out or cannot dock, with a reason and extrapolated minutes.",
        {
            "horizon_min": {"type": "integer", "description": "Risk horizon in minutes.", "minimum": 5, "maximum": 240},
            "top_n": {"type": "integer", "description": "How many stations to return.", "minimum": 1, "maximum": 30},
        },
    ),
    "rebalance_plan": _spec(
        "rebalance_plan",
        "Match surplus stations to deficit stations, nearest first, and cost the moves in bikes and km.",
        {
            "max_moves": {"type": "integer", "description": "Maximum bikes to move.", "minimum": 1, "maximum": 100},
        },
    ),
    "rank_actions": _spec(
        "rank_actions",
        "Turn findings into owner-shaped actions ranked by impact and confidence.",
        {"top_n": {"type": "integer", "description": "How many actions to return.", "minimum": 1, "maximum": 10}},
    ),
    "forecast_gate": _spec(
        "forecast_gate",
        "Check whether a forecast is supportable. Returns insufficient_data / baseline_only / no_skill and why.",
        {"horizon_min": {"type": "integer", "description": "Forecast horizon in minutes.", "minimum": 5, "maximum": 240}},
    ),
    "validate_claim": _spec(
        "validate_claim",
        "Check that every number in a claim appears in the cited evidence ids. Returns PASS or REJECT.",
        {
            "claim": {"type": "string", "description": "The sentence to check."},
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Evidence ids returned by earlier tool calls.",
            },
        },
        ["claim", "evidence_ids"],
    ),
    "write_report": _spec(
        "write_report",
        "Validate claims and write a traceable Markdown report into this stage's reports/ folder.",
        {
            "title": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "action": {"type": "object"},
                        "impact": {"type": "string"},
                        "confidence": {"type": "string"},
                        "limits": {"type": "array", "items": {"type": "string"}},
                        "falsifier": {"type": "string"},
                    },
                    "required": ["text", "evidence_ids"],
                },
            },
            "filename": {"type": "string", "description": "Report file name, e.g. INSIGHTS.md."},
        },
        ["title", "claims"],
    ),
    "fleet_mix": _spec(
        "fleet_mix",
        "Vehicle-type mix overall, by latitude band, and which type is left at one-bike stations.",
    ),
}


# ---------------------------------------------------------------------------
# stage definitions
# ---------------------------------------------------------------------------

STAGES: dict[int, dict] = {
    1: {
        "title": "The smallest agent: audit before analysis",
        "tools": ["list_snapshots", "read_snapshot", "profile_columns", "audit_snapshots"],
        "goal": "Build the smallest useful agent: it can look at the files, but it cannot yet analyse a time series.",
        "changed": "This is the first rung. It combines the baseline dashboard and the read-only auditor.",
        "guard": "Read-only tools, a named registry, a step limit and an evidence ledger.",
        "teaching": "The first useful output is a warning about the data, not a chart.",
        "question": "Before analysing anything, what would make a conclusion unsafe?",
        "expected": "50.8% of rows report exactly 4 free docks; 46 stations never report anything else; docks==0 never occurs. One observation appears in two identical files. Feed lag is 5.4-10.2 minutes.",
        "next": "STEP_2 gives the agent a clock: panel, flow, states and risk.",
        "result_file": "stage1_audit.json",
    },
    2: {
        "title": "Give it time: levels become flows",
        "tools": [
            "list_snapshots",
            "read_snapshot",
            "profile_columns",
            "audit_snapshots",
            "build_panel",
            "net_flow",
            "state_transitions",
            "failure_risk",
        ],
        "goal": "Teach the agent to compare moments, not just read one snapshot.",
        "changed": "Adds a deduplicated panel, signed net flow, state transitions and a risk ranking.",
        "guard": "Every rate uses elapsed time and reports gaps; no fake regular grid.",
        "teaching": "The station with the fewest bikes is not always the one to fix first.",
        "question": "Which stations are failing riders, and which are merely busy?",
        "expected": "7 deduped snapshots over 2.75 h. Fastest drain: Lewes Road & Edinburgh Road at -3.27 bikes/h. Fastest sink: Richmond Place at +5.08 bikes/h. 14 empty and 17 full at the last snapshot.",
        "next": "STEP_3 turns the risk list into moves and owner-shaped actions.",
        "result_file": "stage2_risk.json",
    },
    3: {
        "title": "Give it judgment: actions, not observations",
        "tools": [
            "list_snapshots",
            "read_snapshot",
            "profile_columns",
            "audit_snapshots",
            "build_panel",
            "net_flow",
            "state_transitions",
            "failure_risk",
            "rebalance_plan",
            "rank_actions",
        ],
        "goal": "Turn a finding into a decision: who does what, where, by when, with what expected effect.",
        "changed": "Adds surplus-to-deficit matching, distance costing and a ranked action list.",
        "guard": "Every action names an owner, a deadline, a confidence and a falsifier.",
        "teaching": "An insight is decision-shaped. 'Utilisation is 51%' is not an action.",
        "question": "What should we do before the next morning peak?",
        "expected": "A 20-bike plan from surplus stations to deficit stations, plus data, maintenance and network actions. The top ops move is nearest-source greedy, not an optimal solve.",
        "next": "STEP_4 adds the power to refuse: the forecast gate.",
        "result_file": "stage3_actions.json",
    },
    4: {
        "title": "Give it restraint: the forecast gate",
        "tools": [
            "list_snapshots",
            "read_snapshot",
            "profile_columns",
            "audit_snapshots",
            "build_panel",
            "net_flow",
            "state_transitions",
            "failure_risk",
            "rebalance_plan",
            "rank_actions",
            "forecast_gate",
        ],
        "goal": "Make the agent check whether a forecast is supportable, and refuse when it is not.",
        "changed": "Adds a persistence baseline, a backtest, data-sufficiency thresholds and a refusal path.",
        "guard": "No forecast unless it has enough history AND beats persistence.",
        "teaching": "A defensible refusal is more convincing than an invented forecast.",
        "question": "Which stations will be empty in 60 minutes?",
        "expected": "status=insufficient_data: 2.75 h, 7 snapshots, 1 day. The agent reports persistence MAE (about 0.47 bikes at 5-minute steps) but refuses the 60-minute claim and falls back to risk at the current drain.",
        "next": "STEP_5 adds the evidence trail and a validator that can reject a false claim.",
        "result_file": "stage4_forecast_gate.json",
    },
    5: {
        "title": "Give it an evidence trail",
        "tools": [
            "list_snapshots",
            "read_snapshot",
            "profile_columns",
            "audit_snapshots",
            "build_panel",
            "net_flow",
            "state_transitions",
            "failure_risk",
            "rebalance_plan",
            "rank_actions",
            "forecast_gate",
            "validate_claim",
            "write_report",
        ],
        "goal": "Make every sentence traceable to a tool result, and prove the check by rejecting a false claim.",
        "changed": "Adds number validation and a Markdown report writer. The false claim is rejected on stage.",
        "guard": "Every number in prose must exist in the cited evidence; unknown evidence ids fail.",
        "teaching": "Code computes. The model reasons. The validator checks the seam.",
        "question": "Write the insight report, and show me a claim you had to reject.",
        "expected": "Four supported claims and one rejected claim ('42 stations will be empty by noon') in reports/INSIGHTS.md.",
        "next": "STEP_6 hands the same loop to the room and adds fleet-mix analysis.",
        "result_file": "INSIGHTS.md",
    },
    6: {
        "title": "Hand it to the room: extend, then close",
        "tools": [
            "list_snapshots",
            "read_snapshot",
            "profile_columns",
            "audit_snapshots",
            "build_panel",
            "net_flow",
            "state_transitions",
            "failure_risk",
            "rebalance_plan",
            "rank_actions",
            "forecast_gate",
            "validate_claim",
            "write_report",
            "fleet_mix",
        ],
        "goal": "Add one new question (fleet mix), run the full loop and produce the final report.",
        "changed": "Adds vehicle-type parsing by latitude band and the one-bike 'last vehicle left' view.",
        "guard": "Same evidence rules; the latitude band is explicitly a proxy, not elevation.",
        "teaching": "The harness is the product: a new question is usually a new tool, not a new agent.",
        "question": "Are e-bikes pooling in the north, and what would you do about it?",
        "expected": "E-bikes are 36.3% of the docked fleet; their share rises from 30.0% in the southern third to 44.4% in the northern third. The full report includes actions and the forecast refusal.",
        "next": "After the talk: add weather, events, a longer collector run and a specialist critic agent.",
        "result_file": "FULL_REPORT.md",
    },
}


# ---------------------------------------------------------------------------
# agent.py — shared shell + one demo per stage
# ---------------------------------------------------------------------------

AGENT_SHELL = r'''#!/usr/bin/env python
"""__STAGE_HEADER__

Run the deterministic demo:
    uv run python __FOLDER__/agent.py

Ask a question through the model (needs OPENROUTER_API_KEY in .env):
    uv run python __FOLDER__/agent.py --llm -q "Which stations are at risk?"

Use a different data folder:
    uv run python __FOLDER__/agent.py --data path/to/snapshots
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from harness import Harness, LLMClient, LLMError, have_api_key, run_llm
from tools import DEFAULT_DATA, SPECS, TOOLS

STAGE = "__STAGE_HEADER__"
REPORTS = Path(__file__).resolve().parent / "reports"

SYSTEM = """You are a data intelligence agent analysing Brighton Bikeshare (Beryl) snapshots.

Hard rules:
1. Use the tools. Never calculate a number yourself and never invent one.
2. Every claim must cite at least one evidence_id returned by a tool.
3. State the window, the gaps and the limits behind each claim.
4. Prefer a refusal over a forecast the data cannot support.
5. End with an action: owner, what, where, when, expected impact, confidence and a falsifier.
"""

ROUTES = [
    (("audit", "quality", "duplicate", "missing", "null", "metric", "docks"), "audit_snapshots", {}),
    (("timeline", "panel", "gap", "cadence", "when"), "build_panel", {}),
    (("flow", "drain", "sink", "change", "moving"), "net_flow", {}),
    (("transition", "state"), "state_transitions", {}),
    (("risk", "empty", "fail", "urgent", "soon", "lock"), "failure_risk", {}),
    (("move", "rebalance", "surplus", "deficit", "route"), "rebalance_plan", {}),
    (("action", "should", "recommend", "priority", "fix"), "rank_actions", {}),
    (("forecast", "predict", "next hour", "tomorrow"), "forecast_gate", {}),
    (("fleet", "e-bike", "ebike", "scooter", "vehicle", "mix", "type"), "fleet_mix", {}),
]


def build_harness(args: argparse.Namespace) -> Harness:
    if args.data:
        os.environ["BIKESHARE_DATA"] = str(Path(args.data).resolve())
    return Harness(TOOLS, SPECS, max_steps=args.max_steps, verbose=not args.quiet)


def route(harness: Harness, question: str) -> dict:
    text = question.lower()
    for keywords, tool, payload in ROUTES:
        if tool in TOOLS and any(word in text for word in keywords):
            return harness.call(tool, payload)
    fallback = "audit_snapshots" if "audit_snapshots" in TOOLS else next(iter(TOOLS))
    return harness.call(fallback, {})


def ask(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print(f"Q: {args.question}\n")
    if args.llm:
        if not have_api_key():
            print("No OPENROUTER_API_KEY / OPENROUTER_KEY found; falling back to the deterministic demo.")
            demo(harness, args)
            return
        try:
            client = LLMClient(model=args.model)
            answer, _messages = run_llm(harness, SYSTEM, args.question, client, args.max_steps)
        except LLMError as exc:
            print(f"Model unavailable: {exc}")
            print("Falling back to the deterministic demo.\n")
            demo(harness, args)
            return
        print("\n--- model answer ---\n")
        print(answer)
        print("\nEvidence ledger:")
        for row in harness.ledger.summaries():
            print(f"  {row['evidence_id']}  {row['tool']:<18} {row['summary']}")
        return

    result = route(harness, args.question)
    print("\n--- result ---")
    print(json.dumps(result["data"], indent=2, default=str)[:5000])
    print("\n(Deterministic router. Use --llm for model-driven tool choice.)")


def main() -> None:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("-q", "--question", help="question to ask; omit for the stage demo")
    parser.add_argument("--llm", action="store_true", help="let the model choose tools (needs an API key)")
    parser.add_argument("--model", help="OpenRouter model override")
    parser.add_argument("--data", help=f"snapshot folder (default: {DEFAULT_DATA})")
    parser.add_argument("--max-steps", type=int, default=8, help="tool-call loop limit")
    parser.add_argument("--json", action="store_true", help="also print the structured result")
    parser.add_argument("--quiet", action="store_true", help="do not print every tool call")
    args = parser.parse_args()

    REPORTS.mkdir(exist_ok=True)
    harness = build_harness(args)
    if args.question:
        ask(harness, args)
    else:
        demo(harness, args)


if __name__ == "__main__":
    main()
'''


DEMOS: dict[int, str] = {}

DEMOS[1] = r'''
def demo(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print("Question: before any analysis, what would make a conclusion unsafe?\n")
    snapshots = harness.call("list_snapshots")
    audit = harness.call("audit_snapshots")
    data = audit["data"]
    metrics = data["metrics"]

    print("\n--- Findings ---")
    for finding in data["findings"]:
        print(f"[{finding['severity'].upper():6}] {finding['id']}  {finding['finding']}")
        print(f"           why it matters: {finding['consequence']}")
        print(f"           fix: {finding['fix']}")

    print("\n--- Baseline a dashboard would show ---")
    print(
        f"{metrics['n_stations']} stations | {metrics['last_bikes']} bikes | "
        f"{metrics['last_docks']} docks | {metrics['last_empty']} empty | "
        f"{metrics['last_full']} full | {metrics['not_renting_stations']} not renting"
    )

    print("\n--- Recommended definitions before anyone charts this ---")
    for key, value in data["recommended_definitions"].items():
        print(f"  {key:<8} {value}")

    result = {"snapshots": snapshots["data"], "audit": data, "metrics": metrics}
    (REPORTS / "stage1_audit.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {REPORTS / 'stage1_audit.json'}")
    print("\nTakeaway: the first useful output is a warning about the data, not a chart.")
    if args.json:
        print(json.dumps(audit, indent=2, default=str))
'''

DEMOS[2] = r'''
def demo(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print("Question: which stations are failing riders, and which are merely busy?\n")
    panel = harness.call("build_panel")
    flow = harness.call("net_flow")
    risk = harness.call("failure_risk")

    print("\n--- Timeline (deduplicated) ---")
    for row in panel["data"]["timeline"]:
        gap = "" if row["gap_from_previous_min"] is None else f"  gap {row['gap_from_previous_min']:.0f} min"
        print(
            f"{row['snapshot_ts'][11:16]}  bikes {row['bikes']:>4}  empty {row['empty']:>2}  "
            f"low {row['low']:>2}  full {row['full']:>2}{gap}"
        )

    print("\n--- Fastest drains (bikes/hour) ---")
    for row in flow["data"]["top_drains"][:6]:
        print(f"  {row['rate_per_hour']:+6.2f}/h  {row['name']:<38} {row['first_bikes']:>2} -> {row['last_bikes']:>2}")

    print("\n--- Fastest sinks (bikes/hour) ---")
    for row in flow["data"]["top_sinks"][:6]:
        print(f"  {row['rate_per_hour']:+6.2f}/h  {row['name']:<38} {row['first_bikes']:>2} -> {row['last_bikes']:>2}")

    print("\n--- Failure risk now ---")
    print(f"states: {risk['data']['state_counts']}")
    for row in risk["data"]["top_risk"][:8]:
        if row["failure_mode"] == "EMPTY_NOW":
            minutes = "now"
        elif row["minutes_to_empty"] is None:
            minutes = "-"
        else:
            minutes = f"{row['minutes_to_empty']} min"
        print(
            f"  {row['risk_score']:.2f}  {row['failure_mode']:<11} {row['name']:<36} "
            f"bikes {row['bikes']:>2}  rate {row['rate_per_hour']:+5.2f}/h  ~{minutes}"
        )

    print("\n--- About to fail, not failed yet ---")
    for row in risk["data"]["about_to_fail"][:8]:
        minutes = row["minutes_to_empty"] if row["minutes_to_empty"] is not None else "-"
        print(
            f"  {row['failure_mode']:<11} {row['name']:<36} bikes {row['bikes']:>2}  "
            f"rate {row['rate_per_hour']:+5.2f}/h  ~{minutes} min to empty"
        )

    result = {"panel": panel["data"], "flow": flow["data"], "risk": risk["data"]}
    (REPORTS / "stage2_risk.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {REPORTS / 'stage2_risk.json'}")
    print("\nTakeaway: read flows, not levels. A station can be busy and balanced, or quiet and failing.")
    if args.json:
        print(json.dumps(risk, indent=2, default=str))
'''

DEMOS[3] = r'''
def demo(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print("Question: what should we do before the next morning peak?\n")
    risk = harness.call("failure_risk")
    plan = harness.call("rebalance_plan")
    actions = harness.call("rank_actions")

    print("\n--- Current failures ---")
    print(
        f"{risk['data']['state_counts']['EMPTY']} empty, "
        f"{risk['data']['state_counts']['LOW']} low, "
        f"{risk['data']['state_counts']['FULL']} full"
    )
    print("Top risk:")
    for row in risk["data"]["top_risk"][:5]:
        print(f"  {row['risk_score']:.2f}  {row['name']:<38} {row['reason']}")

    print("\n--- Rebalance plan ---")
    for move in plan["data"]["moves"]:
        print(
            f"  {move['bikes']:>2} bikes  {move['from_name']:<34} -> {move['to_name']:<34} "
            f"{move['km']:.2f} km"
        )
    print(
        f"  Total: {plan['data']['total_bikes']} bikes, {plan['data']['total_km']} km, "
        f"{plan['data']['deficits_helped']} deficit stations helped"
    )

    print("\n--- Ranked actions ---")
    for action in actions["data"]["actions"]:
        print(f"\n[{action['id']}] {action['owner'].upper()}  (confidence: {action['confidence']})")
        print(f"  Do:      {action['action']}")
        print(f"  Where:   {action['where']}")
        print(f"  When:    {action['when']}")
        print(f"  Impact:  {action['expected_impact']}")
        print(f"  Falsify: {action['falsifier']}")
        print(f"  Limits:  {action['limits']}")

    result = {"risk": risk["data"], "plan": plan["data"], "actions": actions["data"]}
    (REPORTS / "stage3_actions.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {REPORTS / 'stage3_actions.json'}")
    print("\nTakeaway: an insight is decision-shaped — owner, place, deadline, impact, confidence, falsifier.")
    if args.json:
        print(json.dumps(actions, indent=2, default=str))
'''

DEMOS[4] = r'''
def demo(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print("Question: which stations will be empty in 60 minutes?\n")
    gate = harness.call("forecast_gate", {"horizon_min": 60})
    data = gate["data"]

    print("\n--- Forecast gate ---")
    print(f"status: {data['status']}")
    print(f"reason: {data['reason']}")
    print("\nData sufficiency:")
    for key, value in data["data_sufficiency"].items():
        print(f"  {key:<20} {value}")
    print("\nBaselines (the bar any forecast must beat):")
    for key, value in data["baselines"].items():
        print(f"  {key:<26} {value}")
    print("\nWhat the agent would need:")
    for item in data["would_need"]:
        print(f"  - {item}")
    print(f"\nFallback: {data['fallback']}")

    risk = harness.call("failure_risk", {"horizon_min": 60})
    print("\n--- Defensible statement instead (current-drain risk, not a forecast) ---")
    for row in risk["data"]["top_risk"][:6]:
        print(f"  {row['risk_score']:.2f}  {row['name']:<38} {row['reason']}")

    result = {"forecast_gate": data, "fallback_risk": risk["data"]}
    (REPORTS / "stage4_forecast_gate.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {REPORTS / 'stage4_forecast_gate.json'}")
    print("\nTakeaway: an agent that cannot say 'not yet' is a random number generator with good manners.")
    if args.json:
        print(json.dumps(gate, indent=2, default=str))
'''

DEMOS[5] = r'''
def demo(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print("Question: write the insight report, and show me a claim you had to reject.\n")
    audit = harness.call("audit_snapshots")
    flow = harness.call("net_flow")
    risk = harness.call("failure_risk")
    plan = harness.call("rebalance_plan")

    a = audit["data"]["metrics"]
    drains = flow["data"]["top_drains"]
    sinks = flow["data"]["top_sinks"]
    p = plan["data"]

    claims = [
        {
            "text": (
                f"{a['docks4_share']:.1%} of rows report exactly 4 free docks, and "
                f"{a['docks4_stations']} stations never report anything else."
            ),
            "evidence_ids": [audit["evidence_id"]],
            "action": {"owner": "data / product", "what": "replace docks == 0 with docks <= 4 AND occupancy >= 0.75", "when": "next release"},
            "impact": "a FULL alert that can actually fire",
            "confidence": "high",
            "limits": ["occupancy still relies on a soft capacity field"],
            "falsifier": "a future snapshot with num_docks_available == 0",
        },
        {
            "text": (
                f"{a['duplicate_observations']} observation time appears in more than one file; "
                f"the panel keeps {a['n_unique_snapshots']} snapshots from {a['n_files']} files."
            ),
            "evidence_ids": [audit["evidence_id"]],
            "action": {"owner": "data engineering", "what": "deduplicate on last_reported before any rate calculation", "when": "now"},
            "impact": "removes a doubled fleet and empty count at that moment",
            "confidence": "high",
            "limits": ["only catches exact observation-time duplicates"],
            "falsifier": "two different snapshots share a last_reported value",
        },
        {
            "text": (
                f"The fastest drain loses {abs(drains[0]['rate_per_hour']):.2f} bikes per hour "
                f"({drains[0]['name']}); the fastest sink gains {sinks[0]['rate_per_hour']:.2f} per hour "
                f"({sinks[0]['name']})."
            ),
            "evidence_ids": [flow["evidence_id"]],
            "action": {"owner": "operations", "what": "pre-stock the drain stations and use the sink stations as sources", "when": "before 07:00"},
            "impact": "reduces the morning lock-out window",
            "confidence": "medium",
            "limits": ["2.75 h, one weekday", "one 134-minute collection gap"],
            "falsifier": "the same stations still drain after a full week of data",
        },
        {
            "text": (
                f"Moving {p['total_bikes']} bikes in {len(p['moves'])} moves restores at least one bike "
                f"to {p['deficits_helped']} stations."
            ),
            "evidence_ids": [plan["evidence_id"]],
            "action": {"owner": "operations", "what": "run the nearest-source rebalance plan", "when": "before the next weekday peak"},
            "impact": f"{p['deficits_helped']} stations helped over {p['total_km']} km",
            "confidence": "medium",
            "limits": ["greedy matching, not optimal transport", "no van capacity or traffic"],
            "falsifier": "helped stations are still empty two hours after the move",
        },
        {
            "text": "42 stations will be empty by noon.",
            "evidence_ids": [risk["evidence_id"]],
            "action": {"owner": "nobody", "what": "do not publish this", "when": "never"},
            "impact": "unsupported",
            "confidence": "none",
            "limits": ["invented number"],
            "falsifier": "the number is not in the evidence",
        },
    ]

    print("\n--- Claim validation ---")
    for claim in claims:
        check = harness.call(
            "validate_claim", {"claim": claim["text"], "evidence_ids": claim["evidence_ids"]}
        )
        print(f"  {check['summary']}")

    report = harness.call(
        "write_report",
        {
            "title": "Brighton Bikeshare — evidence-backed insight report",
            "claims": claims,
            "filename": "INSIGHTS.md",
        },
    )
    print(f"\nReport: {report['data']['path']}")
    print(f"Written: {report['data']['written']}   Rejected: {len(report['data']['rejected'])}")
    for rejected in report["data"]["rejected"]:
        print(f"  REJECTED: {rejected['text']}  ({rejected['explanation']})")

    result = {
        "claims": claims,
        "report": report["data"],
    }
    (REPORTS / "stage5_claims.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("\nTakeaway: code computes, the model reasons, the validator checks the seam.")
    if args.json:
        print(json.dumps(report, indent=2, default=str))
'''

DEMOS[6] = r'''
def demo(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print("Question: are e-bikes pooling in the north, and what would you do about it?\n")
    fleet = harness.call("fleet_mix")
    audit = harness.call("audit_snapshots")
    flow = harness.call("net_flow")
    risk = harness.call("failure_risk")
    plan = harness.call("rebalance_plan")
    gate = harness.call("forecast_gate", {"horizon_min": 60})

    f = fleet["data"]
    shares = f["overall_shares"]
    by_band = {row["band"]: row["share"] for row in f["by_lat_band"]}
    south = by_band.get("south", {})
    north = by_band.get("north", {})
    last_left = f["last_one_left"]
    a = audit["data"]["metrics"]
    p = plan["data"]

    print("\n--- Fleet mix ---")
    for key, count in sorted(f["overall_counts"].items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {key:<12} {count:>5} vehicles  {shares[key]:.1%}")
    print("\nE-bike share by latitude band:")
    for row in f["by_lat_band"]:
        print(f"  {row['band']:<6} e-bike {row['share'].get('bbe', 0):.1%}  scooter {row['share'].get('scooter', 0):.1%}")
    print("\nLast vehicle left at one-bike stations:")
    for key, count in sorted(last_left.items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {key:<12} {count}")
    print("\nTop e-bike stations (min 5 observations):")
    for row in f["top_ebike_share"][:5]:
        print(f"  {row['ebb_share']:.0%}  {row['name']}")

    claims = [
        {
            "text": (
                f"E-bikes are {shares.get('bbe', 0):.1%} of the docked fleet and scooters are "
                f"{shares.get('scooter', 0):.1%}."
            ),
            "evidence_ids": [fleet["evidence_id"]],
            "action": {"owner": "fleet planning", "what": "treat the three vehicle types as separate products", "when": "now"},
            "impact": "avoids averaging incompatible demand",
            "confidence": "high",
            "limits": ["counts are docked vehicles only; free-floating bikes are a separate feed"],
            "falsifier": "a snapshot where the shares reverse",
        },
        {
            "text": (
                f"E-bike share rises from {south.get('bbe', 0):.0%} in the southern third to "
                f"{north.get('bbe', 0):.0%} in the northern third."
            ),
            "evidence_ids": [fleet["evidence_id"]],
            "action": {"owner": "operations", "what": "test type-specific moves up the hill rather than generic bike moves", "when": "next rebalance trial"},
            "impact": "may reduce the hill-top drain without adding vehicles",
            "confidence": "medium",
            "limits": ["latitude is a proxy for elevation, not a measurement"],
            "falsifier": "e-bike share at hill-top stations does not predict a slower drain",
        },
        {
            "text": (
                f"Beryl bikes are the last vehicle at {last_left.get('beryl_bike', 0)} of "
                f"{f['one_bike_observations']} one-bike observations."
            ),
            "evidence_ids": [fleet["evidence_id"]],
            "action": {"owner": "rider product", "what": "show vehicle type, not just 'bike available'", "when": "next sprint"},
            "impact": "fewer surprises for riders who need a specific type",
            "confidence": "medium",
            "limits": ["85 observations, one morning"],
            "falsifier": "the last-vehicle mix matches the overall fleet mix",
        },
        {
            "text": (
                f"The last snapshot has {a['last_empty']} empty and {a['last_full']} full stations, "
                f"while {a['last_bikes']} of {a['last_capacity']} reported bays are occupied."
            ),
            "evidence_ids": [audit["evidence_id"]],
            "action": {"owner": "operations", "what": "fix distribution, not total fleet size", "when": "this week"},
            "impact": "the network has stock; it is in the wrong places",
            "confidence": "high",
            "limits": ["capacity is soft; occupancy uses observed bays"],
            "falsifier": "empty stations remain empty after a full rebalance cycle",
        },
        {
            "text": (
                f"Moving {p['total_bikes']} bikes in {len(p['moves'])} moves restores at least one bike "
                f"to {p['deficits_helped']} stations."
            ),
            "evidence_ids": [plan["evidence_id"]],
            "action": {"owner": "operations", "what": "run the nearest-source plan", "when": "before the next weekday peak"},
            "impact": f"{p['deficits_helped']} stations helped over {p['total_km']} km",
            "confidence": "medium",
            "limits": ["greedy matching", "no van capacity or traffic"],
            "falsifier": "helped stations are still empty two hours later",
        },
        {
            "text": (
                f"The forecast gate refuses a {gate['data']['horizon_min']}-minute forecast because there are "
                f"only {gate['data']['data_sufficiency']['duration_hours']} hours and "
                f"{gate['data']['data_sufficiency']['n_snapshots']} snapshots."
            ),
            "evidence_ids": [gate["evidence_id"]],
            "action": {"owner": "data engineering", "what": "keep the 5-minute collector running for at least 7 days", "when": "from today"},
            "impact": "unlocks a forecast that can be validated",
            "confidence": "high",
            "limits": ["the refusal is the correct output today"],
            "falsifier": "a longer series still fails to beat persistence",
        },
    ]

    print("\n--- Validated report ---")
    report = harness.call(
        "write_report",
        {
            "title": "Brighton Bikeshare — full agent report",
            "claims": claims,
            "filename": "FULL_REPORT.md",
        },
    )
    for row in harness.ledger.summaries():
        print(f"  {row['evidence_id']}  {row['tool']:<18} {row['summary']}")
    print(f"\nReport: {report['data']['path']}  ({report['data']['written']} claims, {len(report['data']['rejected'])} rejected)")

    print("\n--- What the room can ask next ---")
    print("  uv run python STEP_6/agent.py --llm -q \"Which stations need maintenance vs rebalancing?\"")
    print("  Try adding one tool (weather, events, free-floating bikes) and re-run the same loop.")
    print("\nTakeaway: the model is the easy part. The intelligence is in the tools, the time handling,")
    print("the evidence trail, and the willingness to say 'not yet'.")
    if args.json:
        print(json.dumps(report, indent=2, default=str))
'''


# ---------------------------------------------------------------------------
# PLAN.md and README.md
# ---------------------------------------------------------------------------

PLAN_TEMPLATE = """# __FOLDER__ — __TITLE__

Part __N__ of 6 in the talk build ladder.
Full talk plan: `../TALK_PLAN.html` (or `../TALK_PLAN.md`).

## Goal

__GOAL__

## What changed at this rung

__CHANGED__

## The agent's powers at this stage

__TOOLS__

## Guardrail added

__GUARD__

## Demo question

> __QUESTION__

## Expected result with the bundled snapshots (13 Oct 2026)

__EXPECTED__

## Teaching point

__TEACHING__

## Run it

```bash
cd __FOLDER__
uv run python agent.py
```

Options:

```bash
uv run python agent.py -q "your question"          # deterministic router
uv run python agent.py --llm -q "your question"    # model chooses tools
uv run python agent.py --data ../data/snapshots     # different snapshots
uv run python agent.py --json                       # structured result
```

## Evidence contract

Every tool returns:

- `window` — start, end, snapshot count, duration, gaps
- `data` — the computed numbers
- `caveats` — what the numbers assume
- `summary` — one line for the log
- `evidence_id` — added by the harness, cited by any prose

The model never computes a number. If a number is not in a tool result, it is not
allowed in the answer.

## Audience prompt

__AUDIENCE__

## Next

__NEXT__
"""


README_TEMPLATE = """# __FOLDER__ — __TITLE__

Self-contained stage of the talk build. Start with `PLAN.md` for the stage
contract, then run the demo.

```bash
uv run python agent.py
```

What is here:

| File | Purpose |
|---|---|
| `PLAN.md` | the stage plan, expected result, teaching point and audience prompt |
| `README.md` | this quick start |
| `agent.py` | the stage's deterministic demo and optional model loop |
| `harness.py` | tool registry, evidence ledger, step limit, OpenRouter client |
| `tools.py` | the tools this stage is allowed to use |
| `reports/` | output written by the demo (created at runtime) |

Data defaults to `../data/snapshots`; override with `--data`.

__QUICKSTART__
"""


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------


def _tools_markdown(stage: dict) -> str:
    lines = []
    for name in stage["tools"]:
        desc = TOOL_SPECS[name]["function"]["description"]
        lines.append(f"- `{name}` — {desc}")
    return "\n".join(lines)


def _agent_source(number: int, stage: dict) -> str:
    header = f"STEP {number} — {stage['title']}"
    source = AGENT_SHELL.replace("__STAGE_HEADER__", header).replace("__FOLDER__", f"STEP_{number}")
    demo = DEMOS[number]
    marker = "\ndef main() -> None:"
    return source.replace(marker, demo + marker)


def _tools_source(number: int, stage: dict) -> str:
    title = f"STEP {number} — {stage['title']}"
    data_note = "`../data/snapshots/DEMO_DATA_*.csv` by default (repo-relative)."
    parts = [COMMON.replace("__STAGE_TITLE__", title).replace("__DATA_NOTE__", data_note).rstrip()]
    for name in stage["tools"]:
        parts.append(TOOL_BLOCKS[name].strip())
    registry = "TOOLS = {\n" + "".join(f'    "{name}": {name},\n' for name in stage["tools"]) + "}\n"
    specs = pprint.pformat([TOOL_SPECS[name] for name in stage["tools"]], width=100, sort_dicts=False)
    parts.append(registry + "\nSPECS = " + specs + "\n")
    return "\n\n\n".join(parts)


def _write_stage(number: int, stage: dict) -> None:
    folder = ROOT / f"STEP_{number}"
    folder.mkdir(exist_ok=True)
    (folder / "PLAN.md").write_text(
        PLAN_TEMPLATE.replace("__FOLDER__", folder.name)
        .replace("__TITLE__", stage["title"])
        .replace("__N__", str(number))
        .replace("__GOAL__", stage["goal"])
        .replace("__CHANGED__", stage["changed"])
        .replace("__TOOLS__", _tools_markdown(stage))
        .replace("__GUARD__", stage["guard"])
        .replace("__QUESTION__", stage["question"])
        .replace("__EXPECTED__", stage["expected"])
        .replace("__TEACHING__", stage["teaching"])
        .replace("__AUDIENCE__", stage["question"])
        .replace("__NEXT__", stage["next"]),
        encoding="utf-8",
    )
    (folder / "README.md").write_text(
        README_TEMPLATE.replace("__FOLDER__", folder.name)
        .replace("__TITLE__", stage["title"])
        .replace("__QUICKSTART__", f"Expected: {stage['expected']}"),
        encoding="utf-8",
    )
    (folder / "harness.py").write_text(HARNESS, encoding="utf-8")
    (folder / "tools.py").write_text(_tools_source(number, stage), encoding="utf-8")
    (folder / "agent.py").write_text(_agent_source(number, stage), encoding="utf-8")


def main() -> None:
    for number, stage in STAGES.items():
        _write_stage(number, stage)
        print(f"STEP_{number}: {len(stage['tools'])} tools — {stage['title']}")


if __name__ == "__main__":
    main()
