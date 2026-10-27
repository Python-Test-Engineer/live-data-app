# STEP_5 — Give it an evidence trail

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

Expected: Four supported claims and one rejected claim ('42 stations will be empty by noon') in reports/INSIGHTS.md.
