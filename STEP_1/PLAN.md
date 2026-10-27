# STEP_1 — The smallest agent: audit before analysis

Part 1 of 6 in the talk build ladder.
Full talk plan: `../TALK_PLAN.html` (or `../TALK_PLAN.md`).

## Goal

Build the smallest useful agent: it can look at the files, but it cannot yet analyse a time series.

## What changed at this rung

This is the first rung. It combines the baseline dashboard and the read-only auditor.

## The agent's powers at this stage

- `list_snapshots` — List every snapshot file with its observation time, feed lag, counts and duplicate status.
- `read_snapshot` — Read one snapshot: schema, sample rows and key counts.
- `profile_columns` — Profile every column: type, nulls, numeric range or top values.
- `audit_snapshots` — Audit data quality before analysis: docks floor, soft capacity, duplicates, feed lag, outages, gaps.

## Guardrail added

Read-only tools, a named registry, a step limit and an evidence ledger.

## Demo question

> Before analysing anything, what would make a conclusion unsafe?

## Expected result with the bundled snapshots (13 Oct 2026)

50.8% of rows report exactly 4 free docks; 46 stations never report anything else; docks==0 never occurs. One observation appears in two identical files. Feed lag is 5.4-10.2 minutes.

## Teaching point

The first useful output is a warning about the data, not a chart.

## Run it

```bash
cd STEP_1
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

Before analysing anything, what would make a conclusion unsafe?

## Next

STEP_2 gives the agent a clock: panel, flow, states and risk.
