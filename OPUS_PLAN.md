# OPUS_PLAN — "The AI Analyst": statistical + time-series insight demo on Beryl Brighton snapshots

Goal: a live demo for the Brighton web-dev meetup showing that AI can do more than draw charts —
it can **interrogate** the data, **notice what a human would miss**, **quantify** it, and turn it
into **ranked, costed actions** that would make the bikeshare system run better.

The demo's thesis, in one line:

> Dashboards show *what is*. An AI analyst tells you *what's wrong, why, what will happen next,
> and exactly what to do about it — with the evidence attached.*

---

## 0. Reality check: what is actually in `data/snapshots/` (probed 15 Oct 2026)

| Fact | Value | Why it matters for the demo |
|---|---|---|
| Files | 8 × `DEMO_DATA_YYYYMMDD_HHMMSS.csv` | Each file = one point in time |
| Window | 13 Oct 2026, 07:30 → 10:19 (gap 07:48 → 10:04) | ~3 h, irregular spacing — must resample, not assume a grid |
| Stations | 119 per file, 952 rows total | Panel data: station × time |
| Columns | station_id, num_bikes_available, num_docks_available, is_installed, is_renting, is_returning, last_reported (epoch s, UTC), vehicle_types_available (stringified list of dicts), name, lat, lon, capacity | Rich enough for spatial + fleet-mix analysis |
| Fleet mix (summed obs) | scooter 1,876 · beryl_bike 1,983 · bbe (e-bike) 2,204 | Three products, not one — analyse separately |
| Docked fleet | ~751–762 vehicles per snapshot vs ~1,480 total capacity | System ~51% full overall — the problem is *distribution*, not *quantity* |
| Empty stations | 10 at 07:30 → 14 by 10:04 | A morning-peak signal, already visible in 8 files |
| Not renting | 32 rows, 4 stations (King Alfred, Portslade Station - North, The Droveway - Waitrose, London Rd / Ann Street) | Outages = lost trips; quantifiable |
| Stations that moved at all | 91 / 119; total absolute change 333 vehicles | 28 stations never changed — dead or idle? |
| **Quirk 1** | `num_docks_available == 4` in **51%** of rows | Looks like a reporting floor (virtual bays?) — not real dock counts |
| **Quirk 2** | bikes + docks − capacity ranges **−10 … +14** | Capacity is soft (virtual/overflow bays) — "full" must be defined carefully |
| Extra data | `data/history.csv` (2,856 rows from 10 Oct, 4 cols), `data/free_bike_status.csv` (824 free-floating vehicles), `geofencing_zones.json`, pricing, vehicle_types | Join these for a longer series and the dockless picture |
| Timestamps | file stamp is **local (BST)**; `last_reported` is **UTC epoch** | Normalise everything to UTC or staleness/lag maths will be off by 1 h |

**Honest constraint:** 8 snapshots over 3 hours is enough for *cross-sectional statistics, change
detection, flow estimation and a convincing demo*, but **not** for seasonality (daily/weekly
cycles) or a trustworthy forecast. The plan is built so that:

1. Everything runs and looks good on today's 8 files.
2. Every module automatically gets better as the 5-minute collector (`uv run app.py --snapshot`)
   accumulates days of data — the forecasting/seasonality sections switch on once thresholds are met
   (e.g. ≥ 2 days for daily profile, ≥ 14 days for weekday × hour).
3. The AI states its own confidence and data limits — that honesty is itself part of the "higher
   intelligence" pitch.

Recommendation before the talk: leave the snapshot cron running **every 5 min for ≥ 7 days**
(~2,000 snapshots, ~240k rows). That unlocks Sections 3.3–3.5 properly.

---

## 1. Demo narrative (the talk arc, ~12 minutes)

1. **"Here's a folder of CSVs."** (30 s) Show the raw files. Boring. Unreadable.
2. **"Any tool can chart this."** (1 min) The naive dashboard: total bikes over time, bar of
   bikes per station. Fine, and useless.
3. **"Now ask the AI to be an analyst."** (2 min) It *audits the data first*: finds the docks=4
   floor, the soft capacity, the BST/UTC skew, the dead stations. → "Your 'full station' metric is
   wrong for half the network." This is the first wow: it questioned the data.
4. **Statistical X-ray** (2 min) Inequality (Lorenz/Gini of bikes vs capacity), spatial hot/cold
   clusters on a map, fleet-mix by area (e-bikes pooling in the flats, scooters on the seafront…).
5. **Time-series story** (3 min) Net flow per station, "drain" vs "sink" stations, state-transition
   (empty/ok/full) Markov chain, time-to-empty estimates, the morning drain on the hills.
6. **Actions** (3 min) Insight cards ranked by impact: *"Move 9 bikes from X to Y before 08:00"*,
   *"Re-size these 5 stations"*, *"These 4 stations are offline — est. N missed rentals/day"*,
   a drawn rebalancing van route on the map with km and expected recovered trips.
7. **Closing** (30 s) "Every number on the cards was computed by code; the AI wrote the reasoning
   and the plan. Here is the evidence chart behind each claim." Show the `INSIGHTS.md` report.

The key design principle that makes this credible: **code computes, AI reasons**. No number in an
insight is invented by a language model — every figure traces to a function and a chart.

---

## 2. Analysis menu — what can be done

Grouped by tier. Each item lists: technique → chart → the actionable question it answers.
★ = must-have for the demo. ◐ = needs more data (auto-enabled when available).

### 2.1 Tier A — Data forensics ("the AI questions the data")

| # | Analysis | Technique | Chart | Actionable output |
|---|---|---|---|---|
| A1 ★ | Schema & sanity audit | Per-column null/range/type checks; bikes+docks vs capacity residual | Residual histogram + station table | "Capacity field unreliable for N stations; use observed max occupancy instead" |
| A2 ★ | Reporting floor detection | Mode/mass-at-value test on `num_docks_available` (P(docks==4)) per station | Heatmap station × time of docks value | "Docks=4 is a floor, not a measurement → define FULL as bikes ≥ p95 observed, not docks==0" |
| A3 ★ | Feed staleness | `snapshot_utc − last_reported` per station | Strip plot of lag (min) | "Station X hasn't reported for 3 h — sensor/comms fault, dispatch tech" |
| A4 ★ | Dead / frozen stations | Zero variance across window + `is_renting=False` | Small-multiple sparklines | "28 stations never changed; 4 offline → inspect" |
| A5 | Snapshot cadence & gaps | Inter-arrival times of snapshots | Timeline rug | "Collector missed 07:48–10:04 — fix cron before trusting peaks" |
| A6 | Duplicate/near-duplicate snapshots | Row-hash comparison (07:43:20 vs 07:43:36) | — | De-dupe rule |

### 2.2 Tier B — Statistical analysis (cross-sectional)

| # | Analysis | Technique | Chart | Actionable output |
|---|---|---|---|---|
| B1 ★ | Occupancy distribution | Fill ratio = bikes / effective capacity; KDE + ECDF | Violin by area / ECDF | Share of stations in "danger zones" (<10%, >90%) |
| B2 ★ | Inequality of supply | Lorenz curve & Gini of bikes vs capacity | Lorenz curve | "Top 20% of stations hold 55% of bikes" → redistribution case |
| B3 ★ | Spatial hot/cold spots | Moran's I + Getis-Ord Gi* (or simple kNN local mean) on fill ratio | Map: diverging colour, bubble = capacity | "The North Laine cluster is systematically starved, Hove seafront saturated" |
| B4 ★ | Fleet-mix by place | Parse `vehicle_types_available` → bike/e-bike/scooter counts; chi-square vs network share | Stacked bars + mapped pie markers | "E-bikes pool at the bottom of hills — move them to the top" |
| B5 | Elevation effect | Join station lat/lon to elevation (Open-Elevation/SRTM once, cached) ; Spearman ρ(elevation, fill) | Scatter + LOWESS | Quantifies the Brighton hill problem — a uniquely local insight |
| B6 | Station segmentation | K-means / HDBSCAN on [mean fill, volatility, net flow, e-bike share, capacity] | PCA scatter coloured by cluster, radar per cluster | Named archetypes: "Commuter drain", "Seafront sink", "Sleepy", "Overloaded" — each gets a policy |
| B7 | Capacity right-sizing | Observed peak occupancy vs capacity (p95) | Dumbbell chart | "Shrink these, grow those" |
| B8 | Dockless vs docked | `free_bike_status.csv` KDE vs station locations | Hexbin density + station overlay | "Riders end trips 300 m from any station here → candidate new station site" |
| B9 | Geofence fit | Point-in-polygon of stations/vehicles vs `geofencing_zones.json` | Map with zones | Vehicles stranded near slow/no-ride zones |

### 2.3 Tier C — Time-series analysis

| # | Analysis | Technique | Chart | Actionable output |
|---|---|---|---|---|
| C1 ★ | System pulse | Total docked bikes, empty/full counts over time, resampled to 5-min grid (no fake interpolation across gaps) | Line + shaded gap regions | "Docked fleet dropped 11 and empties rose 10→14 during the morning" |
| C2 ★ | Net flow per station | Δbikes / Δt (bikes/hour) per station; sign → drain vs sink | Diverging bar (top/bottom 15) + map arrows | Drain/sink ranking = rebalancing source/target list |
| C3 ★ | Station heatmap | Station × time matrix of fill ratio, rows ordered by hierarchical clustering | Clustered heatmap | Visually reveals groups moving in sync (commuter corridors) |
| C4 ★ | State machine | Discretise {EMPTY, LOW, OK, HIGH, FULL}; empirical transition matrix; stationary distribution | Transition heatmap + Sankey | P(OK → EMPTY within 30 min) per station = risk score |
| C5 ★ | Time-to-empty / time-to-full | Linear (or Poisson) drain extrapolation from current level & net flow; survival framing once data is long | Gantt-style "minutes until failure" bars | "Station X empties in ~25 min" → the urgency ranking for the van |
| C6 | Volatility & churn | Rolling std, absolute-change sum; churn ≠ net (a station can be busy but balanced) | Scatter churn vs net | Separates "busy-healthy" from "busy-failing" |
| C7 | Co-movement | Correlation of Δbikes between stations (needs ≥ ~50 points) → network graph | Force graph / chord | Origin–destination proxy: "bikes leaving A tend to show up at B" |
| C8 ◐ | Seasonality | Hour-of-day × weekday profiles; STL decomposition (statsmodels) per cluster | Ridge plot / polar clock / STL panels | Shift-planning for the rebalancing crew |
| C9 ◐ | Change-points / anomalies | `ruptures` PELT on system total; robust z-score (MAD) per station | Series with change-point lines; anomaly dots | "Unusual drain at 17:10 Fri — event at the Amex?" |
| C10 ◐ | Forecasting | Ladder: persistence → seasonal-naive → per-station profile → gradient boosting classifier P(empty/full in 30/60 min) | Fan chart; reliability (calibration) curve; backtest MAE vs baseline | Proactive alerts; only shown if it **beats persistence** in backtest |
| C11 ◐ | Lost-demand estimation | Count station-minutes in EMPTY/FULL × (station's typical rental rate) | Bar of estimated missed rentals | £ figure for the business case |

### 2.4 Tier D — Optimisation ("what should we DO?")

| # | Analysis | Technique | Output |
|---|---|---|---|
| D1 ★ | Target inventory per station | Target = level that minimises P(empty)+P(full) over next H minutes given net flow (newsvendor-style: target ≈ capacity × f(flow)) | Table: current, target, surplus/deficit |
| D2 ★ | Rebalancing plan | Match surplus → deficit (min-cost transport via `scipy.optimize.linprog`, haversine distances), then sequence a van route (nearest-neighbour + 2-opt; optional OR-Tools CVRP with van capacity ~20) | Map route, moves list, km, vehicles moved, est. failures avoided |
| D3 ★ | Priority score | Impact = P(failure soon) × station demand weight × outage duration; ranks every action | Ranked action list |
| D4 | Capacity reallocation | Move bays from chronically-sink stations to chronically-full ones (from B7) | Before/after occupancy simulation |
| D5 | Fleet-mix reallocation | E-bikes up the hills, manual bikes on the flat (from B4/B5) | Moves list by vehicle type |
| D6 | Incentive pricing | Stations that are chronic sinks → "return elsewhere" credit zone; drains → "bonus for returning here" | Map of proposed incentive zones |
| D7 | Maintenance dispatch | A3 + A4 → ranked tech-visit list | Ticket list |
| D8 | What-if simulator | Replay observed flows with the plan applied; count avoided empty/full minutes | Before/after small multiples |

### 2.5 Tier E — The AI insight layer (the "higher intelligence" part)

This is what turns analysis into a compelling AI demo:

1. **Rules + statistics generate candidate insights.** Every analysis function returns
   `Insight` objects (structured, numeric, with evidence chart id) — not prose.
2. **Ranking.** Sort by `impact × confidence`; dedupe overlapping insights (same station, same root
   cause) and merge into a single root-cause insight (e.g. "Hill-top drain" explains 6 station alerts).
3. **Narration (optional LLM).** Pass the *structured* insight JSON (never raw data) to an LLM with a
   strict prompt: explain, connect causes, propose action, don't introduce numbers not in the JSON.
   Validate: every number in the output must appear in the input JSON — otherwise reject and fall back
   to the template text. Works fully offline without the LLM (templated narration).
4. **Self-critique.** Each insight carries `limitations` (e.g. "based on 3 h of data, single weekday")
   and a `next_data_needed` hint. The report ends with "What I would need to be more certain".
5. **Action format.** Every action is SMART: *who* (ops / maintenance / pricing / product), *what*,
   *where* (station ids + names), *when* (by time), *expected impact* (number + unit), *how we'll know*
   (metric to watch).

---

## 3. Example insights we can already expect from today's data (hypotheses to verify in code)

These are what the engine should produce on the current 8 files — written as the AI would:

1. **Your "full" metric is broken.** 51% of observations report exactly 4 free docks; bikes+docks
   deviates from capacity by up to ±14. → *Action (product/data):* define FULL as bikes ≥ station p95
   occupancy and treat `num_docks_available` as unreliable; raise with Beryl's feed team.
2. **Morning drain is real even in 3 hours.** Empty stations rose 10 → 14 between 07:30 and 10:04.
   → *Action (ops):* pre-stock the drain stations (C2 top list) by 07:00, not after the peak.
3. **4 stations were not renting** for the whole window. → *Action (maintenance):* dispatch; estimate
   missed rentals once C11 has a rental-rate baseline.
4. **28 stations never moved.** Either genuinely idle (candidate to downsize/relocate bays) or frozen
   sensors (A3 decides which). → *Action:* split into "relocate" vs "repair" lists.
5. **The system isn't short of bikes — it's misallocated.** ~760 docked vehicles vs ~1,480 bays (~51%)
   while 14 stations are empty. → *Action:* the D2 rebalancing route; quantify "N moves fix M empties".
6. **Fleet-mix mismatch** (to verify): e-bikes concentrated low-lying, scooters near seafront.
   → *Action:* type-specific moves (D5).

---

## 4. Tech spec

### 4.1 Layout (fits the existing utils.py + app.py convention)

```
live-data-app/
  app.py                 # existing; add  --analyse  CLI flag and  /insights  route
  utils.py               # existing ETL (unchanged)
  analysis.py            # NEW: all analysis logic (load → audit → stats → ts → optimise → insights)
  charts.py              # NEW: Plotly figure builders, one function per chart id, shared theme
  templates/insights.html  # NEW: renders insight cards + embedded Plotly figures
  reports/<run_stamp>/   # NEW output (gitignored)
     INSIGHTS.md         # qualitative report, ranked insights + actions + limitations
     insights.json       # structured Insight objects
     actions.csv         # SMART action list (who/what/where/when/impact)
     rebalancing_plan.csv
     station_metrics.csv # one row per station, all derived metrics
     charts/*.html       # standalone interactive charts (self-contained, offline)
     charts/*.png        # optional static exports (if kaleido works)
     index.html          # one-page "AI analyst report" for the talk
  tests/test_analysis.py # pytest on synthetic fixtures
```

If the user prefers strictly two files, `charts.py` can be folded into `analysis.py`; keep them split
initially because the chart code will be large.

### 4.2 Dependencies (add with `uv add`)

| Package | Use | Notes |
|---|---|---|
| plotly | All charts, maps (`scatter_map` with OpenStreetMap/Carto tiles — no token), Sankey, heatmaps | Interactive in the browser — best for a live talk; `fig.write_html(include_plotlyjs='cdn' or True)` |
| numpy, scipy | Stats, KDE, `linprog` transport problem, hierarchical clustering | numpy already present via pandas |
| statsmodels | STL, LOWESS, ACF, Poisson GLM | ◐ sections |
| scikit-learn | K-means/HDBSCAN, PCA, GradientBoosting / HistGradientBoostingClassifier, calibration | |
| ruptures | Change-point detection | ◐, optional |
| kaleido (optional) | PNG export of Plotly figures for the Markdown report | Needs Chrome; skip if troublesome — HTML is primary |
| ortools (optional) | CVRP route for van with capacity | Fallback: pure-Python nearest-neighbour + 2-opt |
| openai / anthropic SDK or plain `requests` (optional) | LLM narration | Behind `--llm` flag, env var for key; offline template default |

Windows note: Smart App Control can block freshly installed compiled wheels (scipy/sklearn DLLs).
If an import fails with "Application Control policy has blocked this file":
`uv pip install --reinstall --no-cache <pkg>`. Verify Python 3.14 wheels exist for each package
before committing to it (`uv add` will tell you).

### 4.3 Data model

Canonical long table built once by `load_snapshots()`:

```
obs: snapshot_utc (datetime64[UTC]), station_id (str), name, lat, lon, capacity,
     bikes, docks, is_installed, is_renting, is_returning,
     last_reported_utc, lag_min,
     n_scooter, n_beryl_bike, n_bbe,          # parsed from vehicle_types_available via ast.literal_eval
     eff_capacity,                            # max(capacity, observed max bikes) — see A1
     fill = bikes / eff_capacity,
     state ∈ {EMPTY, LOW, OK, HIGH, FULL}      # thresholds configurable
```

Rules:
- Parse snapshot time from filename as **Europe/London** then convert to UTC.
- `station_id` → `str` everywhere (known int/str mismatch across feeds).
- Optionally union `history.csv` (bikes/docks only) for a longer series; mark source column.
- De-duplicate snapshots < 60 s apart with identical payload hash.
- Resample to a regular grid (`5min`) **per station** with forward-fill limited to one interval;
  never interpolate across collector gaps (keep NaN, shade gaps in charts).

`station_metrics` (one row per station): mean/min/max fill, % time EMPTY/FULL, net_flow_per_h,
churn, volatility, lag stats, minutes_to_empty, minutes_to_full, cluster, gi_star_z, e-bike share,
elevation (optional), priority score.

### 4.4 Core API (`analysis.py`)

```python
@dataclass
class Insight:
    id: str                 # e.g. "A2_docks_floor"
    title: str              # one-line headline
    category: str           # data_quality | statistical | time_series | optimisation
    severity: str           # critical | high | medium | info
    finding: str            # what we observed (templated, numbers inline)
    evidence: dict          # the exact numbers used
    action: str             # SMART action text
    owner: str              # ops | maintenance | pricing | product | data
    stations: list[str]     # affected station ids
    expected_impact: str    # e.g. "avoid ~6 empty-station events this morning"
    impact_score: float     # 0-1 for ranking
    confidence: float       # 0-1, reduced by short windows / few points
    limitations: str
    chart_ids: list[str]

def load_snapshots(path="data/snapshots", include_history=False) -> pd.DataFrame
def audit(obs) -> tuple[pd.DataFrame, list[Insight]]          # Tier A
def station_metrics(obs) -> pd.DataFrame
def statistical(obs, metrics) -> list[Insight]                 # Tier B
def time_series(obs, metrics) -> list[Insight]                 # Tier C (◐ gated by data span)
def optimise(obs, metrics) -> tuple[pd.DataFrame, list[Insight]]   # Tier D → plan
def rank_and_merge(insights) -> list[Insight]                  # Tier E
def narrate(insights, llm=False) -> str                        # Markdown; LLM optional + validated
def run_analysis(out_dir=None, llm=False, quiet=False) -> int  # orchestrator, exit 0/1
```

Capability gating (so it never shows a bad model):
```python
span = obs.snapshot_utc.max() - obs.snapshot_utc.min()
n_snap = obs.snapshot_utc.nunique()
ENABLE_SEASONAL  = span >= pd.Timedelta(days=2)
ENABLE_WEEKDAY   = span >= pd.Timedelta(days=14)
ENABLE_FORECAST  = n_snap >= 200          # and must beat persistence in backtest to be reported
ENABLE_COMOVE    = n_snap >= 50
```

### 4.5 Key algorithms (concise)

- **Net flow (C2):** per station, OLS slope of bikes on time (bikes/hour) over the window, with
  standard error → confidence. Robust to irregular spacing (unlike `diff()`).
- **Time-to-empty (C5):** if slope < 0: `bikes / -slope` hours; to-full: `(eff_capacity − bikes) / slope`.
  Cap at window length × 2 and flag as extrapolation.
- **Transition matrix (C4):** consecutive-state counts per station → row-normalised; network matrix =
  pooled. Stationary distribution via eigenvector of Pᵀ. Risk = P(reach EMPTY in k steps) = (Pᵏ)[s, EMPTY].
- **Gi\* (B3):** kNN (k=6) haversine weights, z-score per station; |z| > 1.96 = hot/cold spot. Pure numpy;
  no geopandas needed.
- **Target level (D1):** target_fill = 0.5 for balanced stations; shift toward full for drains and toward
  empty for sinks: `target = clip(eff_cap/2 − slope × H, 1, eff_cap − 1)` with H = 1–2 h horizon.
- **Rebalancing (D2):** surplus_i = bikes − target (>0), deficit_j = target − bikes (>0); solve the
  transportation LP `min Σ d_ij x_ij` s.t. supplies/demands (scipy `linprog`, highs). Convert flows to
  pick-up/drop stops; sequence with nearest-neighbour + 2-opt honouring van capacity (default 20).
  Output km, vehicles moved, stations fixed.
- **Lost demand (C11):** empty_minutes × station departure rate (from negative slopes in non-empty
  periods). Presented as a range, never a point estimate.
- **Forecast (C10):** features = current fill, slope last 15/30 min, hour, weekday, cluster, neighbours'
  mean fill; target = state in 30/60 min. HistGradientBoostingClassifier, time-series split backtest;
  report Brier score and lift vs persistence. Shown only if it wins.

### 4.6 Charts — design spec ("great charts")

Shared Plotly theme in `charts.py`:
- Template `plotly_white`, font Inter/system-ui, 14 px base, titles that **state the insight**
  (e.g. "14 stations ran dry by 10:04 — up from 10"), not "Chart of bikes".
- Semantic palette, consistent everywhere: EMPTY `#d7263d` (red), LOW `#f49d37`, OK `#3f88c5`,
  HIGH `#44af69`, FULL `#6c3483` (purple); vehicle types: bike `#2e86ab`, e-bike `#f18f01`, scooter `#a23b72`.
- Annotations on every chart pointing at the thing the insight is about (arrow + label).
- Hover templates with station name, id, bikes/capacity, state, and a one-line "why it matters".
- Maps: `scatter_map`, centre (50.83, −0.14), zoom 12, `carto-positron` tiles; size = capacity,
  colour = metric; routes as `line` traces with numbered stops.
- Collector gaps shaded grey with "no data" label (honesty is visible).

Chart inventory (id → function):

| id | Chart | Tier |
|---|---|---|
| ch_audit_residual | Histogram of bikes+docks−capacity, annotated ±14 | A1 |
| ch_docks_floor | Heatmap station × time of docks, the "wall of 4s" | A2 |
| ch_lag | Strip plot of report lag per station | A3 |
| ch_sparklines | Small multiples: 119 tiny lines, dead ones greyed | A4 |
| ch_pulse | System total bikes + empty/full counts, dual axis, gaps shaded | C1 |
| ch_fill_violin | Fill distribution by cluster/area | B1 |
| ch_lorenz | Lorenz curve with Gini in title | B2 |
| ch_map_hotspots | Map Gi* z-scores, diverging | B3 |
| ch_fleet_mix | Stacked bars per area + map of dominant type | B4 |
| ch_clusters | PCA scatter + radar of archetypes | B6 |
| ch_capacity_dumbbell | Capacity vs p95 occupancy | B7 |
| ch_netflow_bar | Diverging bars of bikes/hour, top drains & sinks | C2 |
| ch_netflow_map | Map with flow arrows/colour | C2 |
| ch_heatmap | Clustered station × time fill heatmap | C3 |
| ch_transition | State transition heatmap + Sankey | C4 |
| ch_time_to_empty | "Minutes until failure" horizontal bars, colour by urgency | C5 |
| ch_route | Rebalancing van route on map, numbered stops, moves table | D2 |
| ch_before_after | Simulated empty/full counts with vs without plan | D8 |
| ch_forecast | Fan chart + calibration curve (◐) | C10 |
| ch_seasonal | Polar 24-h clock / STL panels (◐) | C8 |

### 4.7 Integration with the existing app

- `uv run app.py --analyse [--llm] [--quiet]` → `analysis.run_analysis()`; exit 0/1; console
  progress in the house style:
  ```
  [1/7] Loading snapshots ........ 8 files, 952 rows, 119 stations, 07:30-10:19 BST
  [2/7] Auditing data ............ 4 issues (2 critical)
  [3/7] Station metrics .......... 119 stations
  [4/7] Statistical analysis ..... 6 insights
  [5/7] Time-series analysis ..... 5 insights (seasonal/forecast skipped: 2h49m span < 2 days)
  [6/7] Optimisation ............. 9 moves, 4.1 km, fixes 7/14 empty stations
  [7/7] Writing report ........... reports/20261015_093000/index.html
  ```
- Flask: `GET /insights` renders the latest `reports/*/insights.json` as cards (severity colour,
  headline, action, owner, impact, "show evidence" toggles the embedded Plotly chart);
  `POST /analyse` runs it in-process and reloads (same pattern as the existing `/run` button).
- Remember: stop any stale server on :5000 before testing the new route.

### 4.8 LLM narration (optional `--llm`)

- Input: `insights.json` (top 10) + data-span summary. Never the raw CSVs.
- System prompt: "You are a senior transport-operations analyst. Use only numbers present in the JSON.
  Group findings by root cause. For each, give: diagnosis, action (who/what/where/when), expected impact,
  how to measure success, confidence and what data would raise it."
- Guard rail: regex-extract all numbers from the response; any number not in the input → reject and use
  the templated narration. Log which mode produced the report.
- Key from env var only (e.g. `OPENROUTER_API_KEY`); never written to disk or logs.

### 4.9 Testing & validation

- `tests/test_analysis.py` with a synthetic fixture: 5 stations × 12 snapshots with known behaviour
  (one drains linearly, one fills, one frozen, one offline, one with docks floor) — assert each insight
  fires (and only the right one), slopes ≈ known values, LP plan moves the expected bikes.
- Property checks: fill in [0, 1+ε], plan conserves vehicles (Σ pickups = Σ drops), route stops ≤ van cap.
- Backtest gate for forecasts (must beat persistence) — enforced in code, not by judgement.
- Smoke run on the real 8 files in CI-less local check: `uv run app.py --analyse --quiet` exits 0 and
  writes `index.html`.

---

## 5. Build phases

| Phase | Scope | Result |
|---|---|---|
| 1 | `load_snapshots`, audit (A1–A6), station_metrics, ch_pulse/ch_docks_floor/ch_sparklines | "AI questions the data" segment works |
| 2 | Tier B (B1–B4, B6, B7) + maps | Statistical X-ray |
| 3 | Tier C (C1–C6) | Flow & failure story on current data |
| 4 | Tier D (D1–D3, D8) + route map | The actions segment — the climax of the talk |
| 5 | Insight engine, INSIGHTS.md, index.html, /insights route | Presentable end-to-end |
| 6 | Optional LLM narration with guard rail | "AI wrote the briefing" moment |
| 7 ◐ | After ≥ 7 days collection: C7–C11, forecast, seasonality, elevation (B5), dockless (B8), geofence (B9) | Upgraded demo with real predictive power |

Phases 1–5 run entirely on the existing 8 snapshots.

---

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Too little data → spurious insights | Capability gating, confidence scores, explicit limitations section, "needs more data" badges |
| Feed quirks (docks floor, soft capacity) distort metrics | `eff_capacity` from observed occupancy; FULL defined from bikes, not docks |
| BST/UTC confusion | Single tz-normalisation in `load_snapshots`, tested |
| LLM hallucinated numbers | Numbers-must-exist-in-JSON validator; offline template fallback |
| Compiled wheels blocked by Smart App Control | Reinstall with `--no-cache`; keep scipy-free fallbacks for route/stats where cheap |
| Live demo fails on stage | Pre-generated `reports/<stamp>/index.html` as a static backup; all charts self-contained HTML |

---

## 7. Next step

Agree the scope (suggest Phases 1–5 for a first cut), then:
1. Confirm deps: `uv add plotly scipy scikit-learn statsmodels` (optional: `ruptures kaleido ortools`).
2. Ask before changing the snapshot cron cadence to 5 min for the 7-day collection run.
3. Implement Phase 1 and show the audit charts on the real data.
