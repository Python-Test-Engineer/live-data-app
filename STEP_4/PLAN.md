# STEP_4 — Give it restraint: the forecast gate

Part 4 of 6 in the talk build ladder.
Full talk plan: `../TALK_PLAN.html` (or `../TALK_PLAN.md`).

## Goal

Make the agent check whether a forecast is supportable, and refuse when it is not.

## What changed at this rung

Adds a persistence baseline, a backtest, data-sufficiency thresholds and a refusal path.

## The agent's powers at this stage

- `list_snapshots` — List every snapshot file with its observation time, feed lag, counts and duplicate status.
- `read_snapshot` — Read one snapshot: schema, sample rows and key counts.
- `profile_columns` — Profile every column: type, nulls, numeric range or top values.
- `audit_snapshots` — Audit data quality before analysis: docks floor, soft capacity, duplicates, feed lag, outages, gaps.
- `build_panel` — Build the deduplicated station-by-time panel and show cadence, gaps and state counts per moment.
- `net_flow` — Signed bike change per station between the first and last snapshot in a window: drains vs sinks.
- `state_transitions` — Observed EMPTY/LOW/OK/FULL transition matrix and per-station failure probabilities.
- `failure_risk` — Rank stations by how soon a rider is locked out or cannot dock, with a reason and extrapolated minutes.
- `rebalance_plan` — Match surplus stations to deficit stations, nearest first, and cost the moves in bikes and km.
- `rank_actions` — Turn findings into owner-shaped actions ranked by impact and confidence.
- `forecast_gate` — Check whether a forecast is supportable. Returns insufficient_data / baseline_only / no_skill and why.

## Guardrail added

No forecast unless it has enough history AND beats persistence.

## Demo question

> Which stations will be empty in 60 minutes?

## Expected result with the bundled snapshots (13 Oct 2026)

status=insufficient_data: 2.75 h, 7 snapshots, 1 day. The agent reports persistence MAE (about 0.47 bikes at 5-minute steps) but refuses the 60-minute claim and falls back to risk at the current drain.

## Teaching point

A defensible refusal is more convincing than an invented forecast.

## Run it

```bash
cd STEP_4
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

Which stations will be empty in 60 minutes?

## Next

STEP_5 adds the evidence trail and a validator that can reject a false claim.
