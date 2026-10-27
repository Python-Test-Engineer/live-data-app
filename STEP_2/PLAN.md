# STEP_2 — Give it time: levels become flows

Part 2 of 6 in the talk build ladder.
Full talk plan: `../TALK_PLAN.html` (or `../TALK_PLAN.md`).

## Goal

Teach the agent to compare moments, not just read one snapshot.

## What changed at this rung

Adds a deduplicated panel, signed net flow, state transitions and a risk ranking.

## The agent's powers at this stage

- `list_snapshots` — List every snapshot file with its observation time, feed lag, counts and duplicate status.
- `read_snapshot` — Read one snapshot: schema, sample rows and key counts.
- `profile_columns` — Profile every column: type, nulls, numeric range or top values.
- `audit_snapshots` — Audit data quality before analysis: docks floor, soft capacity, duplicates, feed lag, outages, gaps.
- `build_panel` — Build the deduplicated station-by-time panel and show cadence, gaps and state counts per moment.
- `net_flow` — Signed bike change per station between the first and last snapshot in a window: drains vs sinks.
- `state_transitions` — Observed EMPTY/LOW/OK/FULL transition matrix and per-station failure probabilities.
- `failure_risk` — Rank stations by how soon a rider is locked out or cannot dock, with a reason and extrapolated minutes.

## Guardrail added

Every rate uses elapsed time and reports gaps; no fake regular grid.

## Demo question

> Which stations are failing riders, and which are merely busy?

## Expected result with the bundled snapshots (13 Oct 2026)

7 deduped snapshots over 2.75 h. Fastest drain: Lewes Road & Edinburgh Road at -3.27 bikes/h. Fastest sink: Richmond Place at +5.08 bikes/h. 14 empty and 17 full at the last snapshot.

## Teaching point

The station with the fewest bikes is not always the one to fix first.

## Run it

```bash
cd STEP_2
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

Which stations are failing riders, and which are merely busy?

## Next

STEP_3 turns the risk list into moves and owner-shaped actions.
