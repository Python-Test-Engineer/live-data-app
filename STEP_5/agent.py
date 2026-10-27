#!/usr/bin/env python
"""STEP 5 — Give it an evidence trail

Run the deterministic demo:
    uv run python STEP_5/agent.py

Ask a question through the model (needs OPENROUTER_API_KEY in .env):
    uv run python STEP_5/agent.py --llm -q "Which stations are at risk?"

Use a different data folder:
    uv run python STEP_5/agent.py --data path/to/snapshots
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

STAGE = "STEP 5 — Give it an evidence trail"
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
    print("Question: write the insight report, and show me a claim you had to reject.\n")
    audit = harness.call("audit_snapshots")
    flow = harness.call("net_flow")
    risk = harness.call("failure_risk")
    plan = harness.call("rebalance_plan")

    a = audit["data"]["metrics"]
    drains = flow["data"]["top_drains"]
    sinks = flow["data"]["top_sinks"]
    p = plan["data"]

    claims = [
        {
            "text": (
                f"{a['docks4_share']:.1%} of rows report exactly 4 free docks, and "
                f"{a['docks4_stations']} stations never report anything else."
            ),
            "evidence_ids": [audit["evidence_id"]],
            "action": {"owner": "data / product", "what": "replace docks == 0 with docks <= 4 AND occupancy >= 0.75", "when": "next release"},
            "impact": "a FULL alert that can actually fire",
            "confidence": "high",
            "limits": ["occupancy still relies on a soft capacity field"],
            "falsifier": "a future snapshot with num_docks_available == 0",
        },
        {
            "text": (
                f"{a['duplicate_observations']} observation time appears in more than one file; "
                f"the panel keeps {a['n_unique_snapshots']} snapshots from {a['n_files']} files."
            ),
            "evidence_ids": [audit["evidence_id"]],
            "action": {"owner": "data engineering", "what": "deduplicate on last_reported before any rate calculation", "when": "now"},
            "impact": "removes a doubled fleet and empty count at that moment",
            "confidence": "high",
            "limits": ["only catches exact observation-time duplicates"],
            "falsifier": "two different snapshots share a last_reported value",
        },
        {
            "text": (
                f"The fastest drain loses {abs(drains[0]['rate_per_hour']):.2f} bikes per hour "
                f"({drains[0]['name']}); the fastest sink gains {sinks[0]['rate_per_hour']:.2f} per hour "
                f"({sinks[0]['name']})."
            ),
            "evidence_ids": [flow["evidence_id"]],
            "action": {"owner": "operations", "what": "pre-stock the drain stations and use the sink stations as sources", "when": "before 07:00"},
            "impact": "reduces the morning lock-out window",
            "confidence": "medium",
            "limits": ["2.75 h, one weekday", "one 134-minute collection gap"],
            "falsifier": "the same stations still drain after a full week of data",
        },
        {
            "text": (
                f"Moving {p['total_bikes']} bikes in {len(p['moves'])} moves restores at least one bike "
                f"to {p['deficits_helped']} stations."
            ),
            "evidence_ids": [plan["evidence_id"]],
            "action": {"owner": "operations", "what": "run the nearest-source rebalance plan", "when": "before the next weekday peak"},
            "impact": f"{p['deficits_helped']} stations helped over {p['total_km']} km",
            "confidence": "medium",
            "limits": ["greedy matching, not optimal transport", "no van capacity or traffic"],
            "falsifier": "helped stations are still empty two hours after the move",
        },
        {
            "text": "42 stations will be empty by noon.",
            "evidence_ids": [risk["evidence_id"]],
            "action": {"owner": "nobody", "what": "do not publish this", "when": "never"},
            "impact": "unsupported",
            "confidence": "none",
            "limits": ["invented number"],
            "falsifier": "the number is not in the evidence",
        },
    ]

    print("\n--- Claim validation ---")
    for claim in claims:
        check = harness.call(
            "validate_claim", {"claim": claim["text"], "evidence_ids": claim["evidence_ids"]}
        )
        print(f"  {check['summary']}")

    report = harness.call(
        "write_report",
        {
            "title": "Brighton Bikeshare — evidence-backed insight report",
            "claims": claims,
            "filename": "INSIGHTS.md",
        },
    )
    print(f"\nReport: {report['data']['path']}")
    print(f"Written: {report['data']['written']}   Rejected: {len(report['data']['rejected'])}")
    for rejected in report["data"]["rejected"]:
        print(f"  REJECTED: {rejected['text']}  ({rejected['explanation']})")

    result = {
        "claims": claims,
        "report": report["data"],
    }
    (REPORTS / "stage5_claims.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("\nTakeaway: code computes, the model reasons, the validator checks the seam.")
    if args.json:
        print(json.dumps(report, indent=2, default=str))

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
