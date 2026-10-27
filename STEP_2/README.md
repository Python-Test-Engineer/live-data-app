# STEP_2 — Give it time: levels become flows

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

Expected: 7 deduped snapshots over 2.75 h. Fastest drain: Lewes Road & Edinburgh Road at -3.27 bikes/h. Fastest sink: Richmond Place at +5.08 bikes/h. 14 empty and 17 full at the last snapshot.
