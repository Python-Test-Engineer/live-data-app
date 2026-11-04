# src — ETL + analytics pipeline

Turns a combined Brighton GBFS snapshot into analytics, Plotly chart pages, and
a single-file dashboard rendered with the `make-html-dashboard` **base template
v1.0.0** (`skills/make-html-dashboard/template.json`).

## Run

```bash
# newest data/data_*.csv
uv run src/pipeline.py

# the snapshot used for the current dashboard
uv run src/pipeline.py --input data/data_20261104T045733Z.csv

# custom output folder / skip artefacts
uv run src/pipeline.py --outdir /tmp/bikeshare --no-charts
```

## Serve the dashboard + chat

```bash
uv run src/server.py --open
# http://127.0.0.1:5000/
```

The dashboard is static, but the bottom-left chat widget needs a same-origin
endpoint. `src/server.py` serves the built dashboard and proxies questions to
the current OpenRouter model (`PI_MODEL`, `OPENROUTER_MODEL`, or `MODEL`, in that
order) with the ETL/analytics output as context. It reads `OPENROUTER_API_KEY`
from the project `.env` or the environment; the key never reaches the browser.

```bash
uv run src/server.py --host 127.0.0.1 --port 5001 --open
curl http://127.0.0.1:5000/api/health
```

If you open `dashboard.html` directly or through a static preview server (VS Code
Live Server, `python -m http.server`), the widget tries the same-origin endpoint
first and then `http://<host>:5000/api/chat`. Keep the Flask server on **port
5000** in that case. A static preview server answers POST with 404/405/501, which
is exactly the error you would see without the fallback. The Flask server sends
CORS headers for these local origins.

The chat answers from a compact snapshot context: KPIs, zones, vehicle mix,
utilisation bands, outliers, quality checks, and every station row from
`clean_stations.csv`. It cannot answer time-series questions because this
snapshot has no history. The compact panel uses 1.5× type; the header expand
button centers the panel at two thirds of the viewport width with 2× type and
remembers the choice.

The pipeline is also runnable as a module:

```bash
uv run python -m src.pipeline --input data/data_20261104T045733Z.csv
```

## Pipeline

| Step | Module | What it does |
|---|---|---|
| Extract | `etl.py` | Reads the combined CSV; refuses to guess if required columns are missing. |
| Transform | `etl.py` | Parses datetimes, coerces booleans/numbers, fills zone/name labels, recomputes utilisation, derives capacity and status fields. |
| Validate | `etl.py` | Records schema, duplicate, capacity, coordinate, freshness, and availability checks as pass/warn/fail. |
| Analyse | `analytics.py` | KPIs, station availability profile, vehicle mix, zone summary, utilisation bands, status counts, top stations, outliers, correlations, suggested actions. |
| Chart | `charts.py` | Writes standalone Plotly pages into `src/output/charts/` (one shared `plotly.min.js`). |
| Render | `build_dashboard.py` | Writes `dashboard-data.json`, calls `skills/make-html-dashboard/scripts/build_dashboard.mjs`, and produces `dashboard.html`. |
| Chat | `chat.py` + `server.py` | Serves the dashboard and answers questions from the snapshot with the current model. |

## Outputs (`src/output/`)

| File | Purpose |
|---|---|
| `clean_stations.csv` | Transformed station table with derived columns. |
| `etl_report.json` | Row counts, snapshot context, quality checks, warnings. |
| `analysis.json` | Every analytics table used by the charts and dashboard. |
| `dashboard-data.json` | Payload in the dashboard skill's data contract. |
| `charts/*.html` | Six standalone Plotly charts. |
| `dashboard.html` | Self-contained dashboard (sticky TOC, scroll-spy, Aa customiser) with the chat launcher when served locally. |

## Derived fields

- `utilisation_pct_calc` — bikes / capacity × 100 (recomputed from source counts).
- `utilisation_delta` — difference between source and recomputed utilisation.
- `capacity_delta` — `total_docks_reported - capacity`.
- `is_capacity_mismatch`, `is_over_capacity`, `is_utilisation_over_100`.
- `availability_gap` — bikes minus free docks.
- `station_status` — `offline | empty | full | low | balanced | busy | unknown`.

## Notes

- One snapshot cannot show change over time. The "station availability profile"
  is sorted by utilisation, not by timestamp. Schedule `data/fetch_gbfs.py` to
  build a real time series.
- Network utilisation is capacity-weighted (total bikes / total capacity). It
  differs from the mean of station-level percentages.
- `capacity != total_docks_reported` is common in the Beryl feed; the ETL flags
  it rather than silently overwriting `capacity`.
- Plotly pages depend on the shared `src/output/charts/plotly.min.js` that the
  pipeline writes alongside them.
