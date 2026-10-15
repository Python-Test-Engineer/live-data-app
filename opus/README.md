# Opus — the AI analyst for Beryl Brighton bikeshare

Implements OPUS_PLAN.md. Reads every `data/snapshots/DEMO_DATA_*.csv` and produces a ranked report of
statistical and time-series findings, each with a SMART action. Code computes every number; the
optional LLM briefing may only reword them.

## Run (from the repo root)

    uv sync                                   # first time: plotly, scipy, scikit-learn, statsmodels, pytest
    uv run opus/app.py --analyse              # full analysis -> opus/reports/<stamp>/
    uv run opus/app.py                        # web UI on http://127.0.0.1:5001 (Re-run button included)
    uv run pytest opus/tests -q               # 7 tests on synthetic data (incl. a 50 h run for gated models)

Flags for `--analyse`:

    --history   also fold in data/history.csv
    --llm       add an LLM-written briefing (needs OPENROUTER_API_KEY; optional OPUS_LLM_MODEL).
                It's rejected if it uses numbers that aren't in the evidence.
    --offline   skip the one-off station elevation lookup (opentopodata, cached in opus/cache/)
    --quiet     no console output; exit code 0/1 for schedulers

## Output: opus/reports/<stamp>/

    index.html             self-contained interactive report (works offline, open from disk)
    INSIGHTS.md            qualitative report: executive summary, findings, actions, limits
    actions.csv            ranked SMART actions (owner, when, where, impact, KPI, confidence)
    rebalancing_plan.csv   van stop list (pick/drop, qty, van load, leg km)
    rebalancing_moves.csv  LP origin -> destination flows
    station_metrics.csv    one row per station, all derived metrics
    insights.json          structured insights (input for the LLM briefing / web UI)
    charts/*.html|json     every chart standalone

## What it does

    [1/7] load      BST filename stamps -> UTC, payload-hash dedupe, vehicle mix parsed,
                    effective capacity, EMPTY/LOW/OK/HIGH/FULL/OFFLINE states
    [2/7] audit     soft capacity, docks reporting floor, stale feeds, offline/frozen stations,
                    collector gaps, duplicate snapshots
    [3/7] metrics   OLS net flow ± SE, churn, departure rate, time-to-empty/full
    [4/7] stats     danger zones, Gini/Lorenz, Getis-Ord Gi* hot/cold spots, fleet mix chi-square,
                    elevation (Spearman), K-means archetypes, capacity right-sizing,
                    dockless DBSCAN new-site candidates, battery swap list, geofence check
    [5/7] series    system pulse, drains/sinks, clustered heatmap, Markov state machine,
                    time-to-failure, churn vs net, lost-demand estimate
                    + gated (need more data): co-movement OD pairs (>=50 snapshots),
                    change points (>=20), daily rhythm (>=48 h), 30-min failure forecast
                    (>=200 snapshots, only reported if it beats persistence)
    [6/7] optimise  target levels, priority score, min-cost transport LP, capacity-20 van route
                    (nearest-neighbour + 2-opt, max 2 loads per run), before/after simulation,
                    rider-incentive zones
    [7/7] report    rank by severity x impact x confidence, merge overlaps, write outputs

Insight wording follows the data. For example, the elevation card says "hills are NOT the
driver" when the correlation isn't significant.
