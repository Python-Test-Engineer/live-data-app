# STEP_5 — Give it an evidence trail

Part 5 of 6 in the talk build ladder.
Full talk plan: `../TALK_PLAN.html` (or `../TALK_PLAN.md`).

## Goal

Make every sentence traceable to a tool result, and prove the check by rejecting a false claim.

## What changed at this rung

Adds number validation and a Markdown report writer. The false claim is rejected on stage.

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
- `validate_claim` — Check that every number in a claim appears in the cited evidence ids. Returns PASS or REJECT.
- `write_report` — Validate claims and write a traceable Markdown report into this stage's reports/ folder.

## Guardrail added

Every number in prose must exist in the cited evidence; unknown evidence ids fail.

## Demo question

> Write the insight report, and show me a claim you had to reject.

## Expected result with the bundled snapshots (13 Oct 2026)

Four supported claims and one rejected claim ('42 stations will be empty by noon') in reports/INSIGHTS.md.

## Teaching point

Code computes. The model reasons. The validator checks the seam.

## Run it

```bash
cd STEP_5
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

Write the insight report, and show me a claim you had to reject.

## Next

STEP_6 hands the same loop to the room and adds fleet-mix analysis.
