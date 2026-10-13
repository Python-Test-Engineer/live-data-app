# Brighton Bikeshare Web App — EXPLAINER

A small Flask web app that pulls **live Brighton cycle-hire data** (run by **Beryl**), runs an
**ETL pipeline**, and presents **data analysis** in the browser. It is built as a demo/teaching
project for the Brighton Web Dev Meetup — deliberately small, everything in plain Python +
pandas + a little HTML.

---

## 1. What it does

### The data source
Beryl publishes a public **GBFS** feed (General Bikeshare Feed Specification — a standard JSON
format used by bike-share systems worldwide). The live availability feed is:

```
https://beryl-gbfs-production.web.app/v2_2/Brighton/station_status.json
```

Every ~120 seconds Beryl refreshes this with the current state of all ~119 Brighton stations:
how many bikes are docked, how many free docks, whether the station is renting/returning, and
the last time it reported.

### The pipeline (ETL)
Each time you load the page, the app:

- **EXTRACT** — fetches two feeds:
  - `station_status.json`   → live bikes/docks per station
  - `station_information.json` → station names, lat/lon, dock capacity
- **TRANSFORM** — merges the two on `station_id`, converts types, derives a per-station
  utilisation % (share of capacity currently holding a bike).
- **LOAD** — appends a timestamped snapshot (one row per station) to `data/history.csv`, so
  you accumulate a time series you can analyse later.
- **ANALYSE** — computes summary stats and renders them in the dashboard.

### The dashboard
The browser page (`templates/index.html`) shows:

- **Summary cards** — total stations, total bikes available, total free docks, and overall
  network utilisation %.
- **Charts** — a line chart of total bikes/docks across past snapshots, top-10 stations by bikes
  and by free docks (bars), and a station-utilisation histogram (Chart.js).
- **Change vs. last snapshot** — which stations gained/lost the most bikes since the previous
  page load (once enough history exists).
- **Full station table** — every station with bike/dock counts, utilisation colour-coded
  (green = healthy, amber = low, red = empty or near-full).
- **Two action buttons:**
  - **▶ Run pipeline & refresh** — re-pull all feeds, write per-feed CSVs + a timestamped
    `data/snapshots/DEMO_DATA_<stamp>.csv`, show the fetch log, then reload (`POST /run`).
  - **▶ Get current data snapshot** — lightweight: fetch the two live feeds and write a fresh
    `data/snapshots/DEMO_DATA_<stamp>.csv` of exactly the same format (`POST /snapshot`).

---

## 2. The files

| File | Purpose |
|------|---------|
| `app.py` | The single app entry point: Flask routes (`GET /`, `POST /run`, `POST /snapshot`) + CLI dispatch |
| `utils.py` | All shared logic — GBFS fetch, the full data pipeline, the ETL, analysis, history |
| `templates/index.html` | The dashboard template (HTML + inline CSS) |
| `data/` | Output folder (history.csv, per-feed CSVs, snapshots/ DEMO_DATA_*.csv) — gitignored |

`utils.py` is where the actual work lives; `app.py` just wires it to the browser and the CLI. The
older "scripts" are folded in here:
- `data.py` → `utils.run_full_pipeline()` (re-pull every feed → per-feed CSVs + DEMO snapshot)
- `collect.py` → `app.py --collect` (run one ETL snapshot into history.csv)
- `--snapshot` → `utils.run_demo_snapshot()` → `utils.snapshot_current_data()` (live data only,
  one `data/snapshots/DEMO_DATA_<stamp>.csv`, no history.csv)

---

## 3. How to use it

### Run the dashboard
```bash
cd "C:\Users\mrcra\Desktop\live-data-app"
uv run app.py
```
Open **http://127.0.0.1:5000** in a browser. Each page load re-runs the ETL and appends a
snapshot to history. Stop the server with **Ctrl+C**.

### Save a current-data snapshot (from the UI)
Click **"▶ Get current data snapshot"**. This calls `utils.snapshot_current_data()`, which fetches
the two live feeds (`station_status` + `station_information`), merges them, and writes a fresh
`data/snapshots/DEMO_DATA_<stamp>.csv` — identical 12-column format to the reference
`data/snapshots/DEMO_DATA_20261013_073228.csv`. Lightweight: 2 feeds, no per-feed CSVs. (From
curl: `curl -X POST http://127.0.0.1:5000/snapshot`.)

### Re-pull the raw feeds to CSV (from the UI)
On the dashboard, click **"▶ Run pipeline & refresh"**. This calls `utils.run_full_pipeline()`,
which re-pulls every feed, writes a timestamped `DEMO_DATA_<stamp>.csv` into `data/snapshots/`, and shows
the fetch log inline before reloading. (Same thing from curl: `curl -X POST http://127.0.0.1:5000/run`.)

### Collect data on a schedule (recommended)
History grows fast if you poll every few minutes, and you don't need the page open. There are
**two distinct collection modes** — pick the one you want:

```bash
uv run app.py --collect            # full ETL snapshot -> appended to data/history.csv
uv run app.py --snapshot           # live data only  -> data/snapshots/DEMO_DATA_<stamp>.csv
uv run app.py --snapshot --quiet   # same, no console output (exit 0 = success)
```

`--snapshot` explicitly does **not** write to `history.csv`; it writes a standalone, timestamped
demo file per run (119 stations × 12 cols) — use it when you only want demo data for analysis and
don't want the web app's history series growing. Exit code is 0 on success, 1 on failure, so both
modes are cron-friendly.

To schedule it every 5 minutes on Windows (replace the python path with `where python`):
```
schtasks /Create /TN "BrightonBikeshareCollect" /SC MINUTE /MO 5 /TR "\"C:\path\to\python.exe\" \"C:\Users\mrcra\Desktop\live-data-app\app.py\" --snapshot --quiet"
```
The repo is currently wired to a **Hermes cron job** (`bikeshare-collect-5min`, every 5 min) that
runs `uv run app.py --snapshot --quiet` and drops one `DEMO_DATA_<stamp>.csv` into `data/snapshots/`
per tick.

### Raw per-feed CSVs
`utils.run_full_pipeline()` also writes one CSV per feed into `data/` (station_information.csv,
station_status.csv, free_bike_status.csv, vehicle_types.csv, system_pricing_plans.csv,
system_regions.csv, gbfs_versions.csv, system_information.csv) plus `geofencing_zones.json`
(raw JSON — GeoJSON doesn't flatten to a table). The per-feed explainer that used to live at the
top of `data.py` is now the module docstring/comments in `utils.py`.

### Requirements
- Python 3 (`uv`) + `flask`, `pandas`, `requests` (declared in `pyproject.toml`).

---

## 4. What you can do with the captured data

Once `history.csv`/`data/snapshots/DEMO_DATA_*.csv` accumulate over time, you can:

- Track **empty / full stations over time** to spot where riders get locked out.
- Measure **arrivals vs. departures** per station by comparing consecutive snapshots.
- Build **forecasts** (a plan is written up in `REPORT.md` at the project root) — e.g. predict
  which stations will be empty/full in the next 30–60 minutes using a "baseline = current"
  model first, then move to time-of-day profiles and lightweight ML once history is thick.

---

## 5. Notes & pitfalls we hit

- **`station_id` type mismatch** — `station_status` returns it as a number, other feeds as a
  string. Merge after casting both to `str` (a silent killer in pandas merges).
- **`free_bike_status` is NOT empty** — it carries ~862 free-ranging bikes/e-bikes/scooters;
  don't skip it if you care about the full fleet, not just docked bikes.
- **`geofencing_zones` is GeoJSON** — don't try to flatten it to CSV; keep the raw JSON.
- **Debug recon** — find all available feeds from the manifest:
  `https://beryl-gbfs-production.web.app/v2_2/Brighton/gbfs.json`.
- **Stale servers on port 5000** — each `uv run app.py` holds port 5000. If you start a second one
  it runs the OLD code while the first keeps answering, so a route you just added 404s (or serves
  stale data). If in doubt, `netstat -ano | grep :5000` for the PIDs (or `Stop-Process -Id <pid> -Force`),
  make sure only ONE `app.py` is running, then start fresh.

---

## 6. Quick demo flow

1. `uv run app.py` → open http://127.0.0.1:5000 → see live stats.
2. Load the page a few times → history accumulates → the "change vs last snapshot" section appears.
3. Click **"▶ Get current data snapshot"** → a fresh `data/snapshots/DEMO_DATA_<stamp>.csv` is written;
   open it in Excel/pandas.
4. Click **"▶ Run pipeline & refresh"** for the full re-pull (all per-feed CSVs + a DEMO snapshot).
5. Let `uv run app.py --collect` run on schedule → build the time series → try forecasting
   (see REPORT.md).