# Brighton Bikeshare Dashboard

A small Flask app that pulls **live Brighton cycle-hire data** (operated by Beryl) from its public
GBFS feed, runs an **ETL pipeline**, and presents **charts + analysis** in the browser. Built as a
demo/teaching project for the Brighton Web Dev Meetup — deliberately small, plain Python + pandas +
a little HTML and Chart.js.

## Quick start

```bash
cd "C:\Users\mrcra\Desktop\live-data-app"
uv run app.py
```

Open **http://127.0.0.1:5000**. Dependencies (`flask`, `pandas`, `requests`) are managed by `uv`
and declared in `pyproject.toml`.

## What the dashboard shows

- **Summary cards** — total stations, bikes available, free docks, and network utilisation %.
- **Charts** — total bikes/docks over past snapshots (line), top-10 stations by bikes and by free
  docks (bars), and a station-utilisation histogram.
- **Change vs. last snapshot** — stations that gained/lost the most bikes since the previous load.
- **Full station table** — every station with bike/dock counts and colour-coded utilisation.
- **Two buttons:**
  - **▶ Run pipeline & refresh** — re-pulls all feeds, writes per-feed CSVs + a fresh
    `data/snapshots/DEMO_DATA_<stamp>.csv`, shows the fetch log, then reloads.
  - **▶ Get current data snapshot** — lightweight: fetches the two live feeds and writes a fresh
    `data/snapshots/DEMO_DATA_<stamp>.csv` (same format as above).

## Commands

```bash
uv run app.py                      # start the dashboard
uv run app.py --collect            # one ETL snapshot -> data/history.csv (exit 0/1)
uv run app.py --snapshot           # live data only -> data/snapshots/DEMO_DATA_<stamp>.csv
uv run app.py --snapshot --quiet   # same, silent (for cron)
curl -X POST http://127.0.0.1:5000/snapshot   # current-data DEMO snapshot, no browser
```

**Two collection modes** (keep them separate):

- `--collect` — runs the full ETL and **appends to `data/history.csv`** (feeds the dashboard's
  change-vs-last-snapshot analysis).
- `--snapshot` — fetches the live feeds and writes a fresh **`data/snapshots/DEMO_DATA_<stamp>.csv`**
  (119 stations × 12 cols). It deliberately does NOT touch `history.csv` — use this when you only
  want raw demo snapshots and don't care about the web app's history.

To collect on a schedule (recommended for a time series — see REPORT.md), point whatever
scheduler you use at the `--snapshot --quiet` mode. With Windows Task Scheduler:
```
schtasks /Create /TN "BrightonBikeshareCollect" /SC MINUTE /MO 5 /TR "\"...\python.exe\" \"C:\Users\mrcra\Desktop\live-data-app\app.py\" --snapshot --quiet"
```
(The repo is currently wired to a Hermes cron job, `bikeshare-collect-5min`, every 5 min, which
runs `uv run app.py --snapshot --quiet` and drops one `DEMO_DATA_<stamp>.csv` into `data/snapshots/`
per tick.)

## Project structure

| Path | Purpose |
|------|---------|
| `app.py` | Single entry point: Flask routes (`GET /`, `POST /run`, `POST /snapshot`) + CLI |
| `utils.py` | All logic — GBFS fetch, data pipeline, ETL, analysis, history |
| `templates/index.html` | Dashboard template (HTML/CSS + Chart.js) |
| `data/` | Generated output: `history.csv`, per-feed CSVs, `snapshots/` (DEMO snapshots) (gitignored) |

`utils.py` does the work; `app.py` only wires it to the browser and CLI.

## Docs

- **EXPLAINER.md** — how it works: data source, the ETL, the files, notes & pitfalls.
- **REPORT.md** — qualitative analysis, forecasting plan, and conclusions.