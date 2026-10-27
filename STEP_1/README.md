# STEP_1 — The smallest agent: audit before analysis

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

Expected: 50.8% of rows report exactly 4 free docks; 46 stations never report anything else; docks==0 never occurs. One observation appears in two identical files. Feed lag is 5.4-10.2 minutes.
