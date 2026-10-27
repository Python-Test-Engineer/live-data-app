# STEP_3 — Give it judgment: actions, not observations

Part 3 of 6 in the talk build ladder.
Full talk plan: `../TALK_PLAN.html` (or `../TALK_PLAN.md`).

## Goal

Turn a finding into a decision: who does what, where, by when, with what expected effect.

## What changed at this rung

Adds surplus-to-deficit matching, distance costing and a ranked action list.

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

## Guardrail added

Every action names an owner, a deadline, a confidence and a falsifier.

## Demo question

> What should we do before the next morning peak?

## Expected result with the bundled snapshots (13 Oct 2026)

A 20-bike plan from surplus stations to deficit stations, plus data, maintenance and network actions. The top ops move is nearest-source greedy, not an optimal solve.

## Teaching point

An insight is decision-shaped. 'Utilisation is 51%' is not an action.

## Run it

```bash
cd STEP_3
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

What should we do before the next morning peak?

## Next

STEP_4 adds the power to refuse: the forecast gate.
