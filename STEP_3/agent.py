#!/usr/bin/env python
"""STEP 3 — Give it judgment: actions, not observations

Run the deterministic demo:
    uv run python STEP_3/agent.py

Ask a question through the model (needs OPENROUTER_API_KEY in .env):
    uv run python STEP_3/agent.py --llm -q "Which stations are at risk?"

Use a different data folder:
    uv run python STEP_3/agent.py --data path/to/snapshots
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from harness import Harness, LLMClient, LLMError, have_api_key, run_llm
from tools import DEFAULT_DATA, SPECS, TOOLS

STAGE = "STEP 3 — Give it judgment: actions, not observations"
REPORTS = Path(__file__).resolve().parent / "reports"

SYSTEM = """You are a data intelligence agent analysing Brighton Bikeshare (Beryl) snapshots.

Hard rules:
1. Use the tools. Never calculate a number yourself and never invent one.
2. Every claim must cite at least one evidence_id returned by a tool.
3. State the window, the gaps and the limits behind each claim.
4. Prefer a refusal over a forecast the data cannot support.
5. End with an action: owner, what, where, when, expected impact, confidence and a falsifier.
"""

ROUTES = [
    (("audit", "quality", "duplicate", "missing", "null", "metric", "docks"), "audit_snapshots", {}),
    (("timeline", "panel", "gap", "cadence", "when"), "build_panel", {}),
    (("flow", "drain", "sink", "change", "moving"), "net_flow", {}),
    (("transition", "state"), "state_transitions", {}),
    (("risk", "empty", "fail", "urgent", "soon", "lock"), "failure_risk", {}),
    (("move", "rebalance", "surplus", "deficit", "route"), "rebalance_plan", {}),
    (("action", "should", "recommend", "priority", "fix"), "rank_actions", {}),
    (("forecast", "predict", "next hour", "tomorrow"), "forecast_gate", {}),
    (("fleet", "e-bike", "ebike", "scooter", "vehicle", "mix", "type"), "fleet_mix", {}),
]


def build_harness(args: argparse.Namespace) -> Harness:
    if args.data:
        os.environ["BIKESHARE_DATA"] = str(Path(args.data).resolve())
    return Harness(TOOLS, SPECS, max_steps=args.max_steps, verbose=not args.quiet)


def route(harness: Harness, question: str) -> dict:
    text = question.lower()
    for keywords, tool, payload in ROUTES:
        if tool in TOOLS and any(word in text for word in keywords):
            return harness.call(tool, payload)
    fallback = "audit_snapshots" if "audit_snapshots" in TOOLS else next(iter(TOOLS))
    return harness.call(fallback, {})


def ask(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print(f"Q: {args.question}\n")
    if args.llm:
        if not have_api_key():
            print("No OPENROUTER_API_KEY / OPENROUTER_KEY found; falling back to the deterministic demo.")
            demo(harness, args)
            return
        try:
            client = LLMClient(model=args.model)
            answer, _messages = run_llm(harness, SYSTEM, args.question, client, args.max_steps)
        except LLMError as exc:
            print(f"Model unavailable: {exc}")
            print("Falling back to the deterministic demo.\n")
            demo(harness, args)
            return
        print("\n--- model answer ---\n")
        print(answer)
        print("\nEvidence ledger:")
        for row in harness.ledger.summaries():
            print(f"  {row['evidence_id']}  {row['tool']:<18} {row['summary']}")
        return

    result = route(harness, args.question)
    print("\n--- result ---")
    print(json.dumps(result["data"], indent=2, default=str)[:5000])
    print("\n(Deterministic router. Use --llm for model-driven tool choice.)")


def demo(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print("Question: what should we do before the next morning peak?\n")
    risk = harness.call("failure_risk")
    plan = harness.call("rebalance_plan")
    actions = harness.call("rank_actions")

    print("\n--- Current failures ---")
    print(
        f"{risk['data']['state_counts']['EMPTY']} empty, "
        f"{risk['data']['state_counts']['LOW']} low, "
        f"{risk['data']['state_counts']['FULL']} full"
    )
    print("Top risk:")
    for row in risk["data"]["top_risk"][:5]:
        print(f"  {row['risk_score']:.2f}  {row['name']:<38} {row['reason']}")

    print("\n--- Rebalance plan ---")
    for move in plan["data"]["moves"]:
        print(
            f"  {move['bikes']:>2} bikes  {move['from_name']:<34} -> {move['to_name']:<34} "
            f"{move['km']:.2f} km"
        )
    print(
        f"  Total: {plan['data']['total_bikes']} bikes, {plan['data']['total_km']} km, "
        f"{plan['data']['deficits_helped']} deficit stations helped"
    )

    print("\n--- Ranked actions ---")
    for action in actions["data"]["actions"]:
        print(f"\n[{action['id']}] {action['owner'].upper()}  (confidence: {action['confidence']})")
        print(f"  Do:      {action['action']}")
        print(f"  Where:   {action['where']}")
        print(f"  When:    {action['when']}")
        print(f"  Impact:  {action['expected_impact']}")
        print(f"  Falsify: {action['falsifier']}")
        print(f"  Limits:  {action['limits']}")

    result = {"risk": risk["data"], "plan": plan["data"], "actions": actions["data"]}
    (REPORTS / "stage3_actions.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {REPORTS / 'stage3_actions.json'}")
    print("\nTakeaway: an insight is decision-shaped — owner, place, deadline, impact, confidence, falsifier.")
    if args.json:
        print(json.dumps(actions, indent=2, default=str))

def main() -> None:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("-q", "--question", help="question to ask; omit for the stage demo")
    parser.add_argument("--llm", action="store_true", help="let the model choose tools (needs an API key)")
    parser.add_argument("--model", help="OpenRouter model override")
    parser.add_argument("--data", help=f"snapshot folder (default: {DEFAULT_DATA})")
    parser.add_argument("--max-steps", type=int, default=8, help="tool-call loop limit")
    parser.add_argument("--json", action="store_true", help="also print the structured result")
    parser.add_argument("--quiet", action="store_true", help="do not print every tool call")
    args = parser.parse_args()

    REPORTS.mkdir(exist_ok=True)
    harness = build_harness(args)
    if args.question:
        ask(harness, args)
    else:
        demo(harness, args)


if __name__ == "__main__":
    main()
