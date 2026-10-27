# STEP_1 → STEP_6: the live build ladder

Six self-contained folders for the talk. Each one has the stage plan, the code,
and the evidence it produces. Move through them in order and the agent gains one
capability at a time.

The talk's Step 0 (the baseline dashboard) is folded into **STEP_1**, so the six
folders match the six build rungs rather than seven.

| Folder | New power | Demo result |
|---|---|---|
| `STEP_1` | Can look: audit the files before analysis | 7 findings, 3 high severity; the docks=4 floor, soft capacity, duplicate snapshot, feed lag, outages |
| `STEP_2` | Can compare moments: panel, flow, state, risk | 7 deduped snapshots over 2.75 h; drains/sinks; 14 empty, 17 full; one station ~55 min from empty |
| `STEP_3` | Can act: rebalance plan + ranked actions | 20 bikes in 7 moves over 3.26 km; data, maintenance and network actions |
| `STEP_4` | Can refuse: forecast gate | `insufficient_data`; persistence MAE 0.466 bikes, but no 60-minute forecast is claimed |
| `STEP_5` | Can be audited: number validator + report | 4 claims pass, 1 invented claim rejected, `reports/INSIGHTS.md` written |
| `STEP_6` | Can be re-aimed: fleet mix + full report | E-bike share 36.3%; 30.0% south → 44.4% north; `reports/FULL_REPORT.md` |

## Run one stage

```bash
cd STEP_1
uv run python agent.py
```

Or from the repo root:

```bash
uv run python STEP_1/agent.py
```

Useful flags (every stage):

```bash
uv run python STEP_3/agent.py -q "what should we do before the peak?"
uv run python STEP_6/agent.py --llm -q "which stations need maintenance?"
uv run python STEP_6/agent.py --data ../data/snapshots
uv run python STEP_5/agent.py --json
```

`--llm` uses the OpenRouter key in `.env`; without it, the deterministic router
still selects a tool so the demo works offline. The default (no `-q`) runs the
stage's scripted demo.

## What is in each folder

| File | Purpose |
|---|---|
| `PLAN.md` | the stage contract: goal, powers, guardrail, expected result, teaching point, audience prompt |
| `README.md` | quick start |
| `agent.py` | stage demo + optional model loop |
| `harness.py` | tool registry, evidence ledger, step limit, OpenRouter client |
| `tools.py` | only the tools this stage is allowed to use (cumulative) |
| `reports/` | generated output from the demo |

## The rule that does not change

Every tool returns a `window` (with gaps), `data` (computed numbers), `caveats`,
a one-line `summary`, and an `evidence_id` added by the harness. The model may
choose tools and write prose, but it may not invent a number. `STEP_5` adds the
validator that proves it.

## Rebuild the folders

The folders are generated from one source so the shared harness and tool code
cannot drift:

```bash
uv run python tools/build_steps.py
```

Edit the generated files directly if you want to customise a single stage; edit
`tools/build_steps.py` only if you want the change in every stage.

## Docs

- `TALK_PLAN.md` / `TALK_PLAN.html` — the full 60-minute run sheet
- `data/QUESTIONS.md` — questions to hand to the room
