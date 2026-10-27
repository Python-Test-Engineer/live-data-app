#!/usr/bin/env python
"""STEP 2 — Give it time: levels become flows

Run the deterministic demo:
    uv run python STEP_2/agent.py

Ask a question through the model (needs OPENROUTER_API_KEY in .env):
    uv run python STEP_2/agent.py --llm -q "Which stations are at risk?"

Use a different data folder:
    uv run python STEP_2/agent.py --data path/to/snapshots
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

STAGE = "STEP 2 — Give it time: levels become flows"
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
    print("Question: which stations are failing riders, and which are merely busy?\n")
    panel = harness.call("build_panel")
    flow = harness.call("net_flow")
    risk = harness.call("failure_risk")

    print("\n--- Timeline (deduplicated) ---")
    for row in panel["data"]["timeline"]:
        gap = "" if row["gap_from_previous_min"] is None else f"  gap {row['gap_from_previous_min']:.0f} min"
        print(
            f"{row['snapshot_ts'][11:16]}  bikes {row['bikes']:>4}  empty {row['empty']:>2}  "
            f"low {row['low']:>2}  full {row['full']:>2}{gap}"
        )

    print("\n--- Fastest drains (bikes/hour) ---")
    for row in flow["data"]["top_drains"][:6]:
        print(f"  {row['rate_per_hour']:+6.2f}/h  {row['name']:<38} {row['first_bikes']:>2} -> {row['last_bikes']:>2}")

    print("\n--- Fastest sinks (bikes/hour) ---")
    for row in flow["data"]["top_sinks"][:6]:
        print(f"  {row['rate_per_hour']:+6.2f}/h  {row['name']:<38} {row['first_bikes']:>2} -> {row['last_bikes']:>2}")

    print("\n--- Failure risk now ---")
    print(f"states: {risk['data']['state_counts']}")
    for row in risk["data"]["top_risk"][:8]:
        if row["failure_mode"] == "EMPTY_NOW":
            minutes = "now"
        elif row["minutes_to_empty"] is None:
            minutes = "-"
        else:
            minutes = f"{row['minutes_to_empty']} min"
        print(
            f"  {row['risk_score']:.2f}  {row['failure_mode']:<11} {row['name']:<36} "
            f"bikes {row['bikes']:>2}  rate {row['rate_per_hour']:+5.2f}/h  ~{minutes}"
        )

    print("\n--- About to fail, not failed yet ---")
    for row in risk["data"]["about_to_fail"][:8]:
        minutes = row["minutes_to_empty"] if row["minutes_to_empty"] is not None else "-"
        print(
            f"  {row['failure_mode']:<11} {row['name']:<36} bikes {row['bikes']:>2}  "
            f"rate {row['rate_per_hour']:+5.2f}/h  ~{minutes} min to empty"
        )

    result = {"panel": panel["data"], "flow": flow["data"], "risk": risk["data"]}
    (REPORTS / "stage2_risk.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {REPORTS / 'stage2_risk.json'}")
    print("\nTakeaway: read flows, not levels. A station can be busy and balanced, or quiet and failing.")
    if args.json:
        print(json.dumps(risk, indent=2, default=str))

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
