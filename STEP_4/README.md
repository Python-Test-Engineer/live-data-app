# STEP_4 — Give it restraint: the forecast gate

Self-contained stage of the talk build. Start with `PLAN.md` for the stage
contract, then run the demo.

```bash
uv run python agent.py
```

What is here:

| File | Purpose |
|---|---|
| `PLAN.md` | the stage plan, expected result, teaching point and audience prompt |
| `README.md` | this quick start |
| `agent.py` | the stage's deterministic demo and optional model loop |
| `harness.py` | tool registry, evidence ledger, step limit, OpenRouter client |
| `tools.py` | the tools this stage is allowed to use |
| `reports/` | output written by the demo (created at runtime) |

Data defaults to `../data/snapshots`; override with `--data`.

Expected: status=insufficient_data: 2.75 h, 7 snapshots, 1 day. The agent reports persistence MAE (about 0.47 bikes at 5-minute steps) but refuses the 60-minute claim and falls back to risk at the current drain.
